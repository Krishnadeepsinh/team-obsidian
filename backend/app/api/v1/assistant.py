import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import IS_POSTGRES, get_db
from app.core.permissions import get_effective_project, verify_project_access
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.knowledge import EmbeddingRecord
from app.models.workspace import User
from app.schemas.knowledge import AssistantQueryRequest, AssistantQueryResponse
from app.services.ai_engine import ai_engine

router = APIRouter(prefix="/assistant", tags=["AI Project Assistant"])

STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her",
    "was", "one", "our", "out", "day", "get", "has", "him", "his", "how", "its",
    "may", "new", "now", "old", "see", "two", "way", "who", "did", "let", "put",
    "say", "she", "too", "use", "why", "over", "such", "into", "than", "then",
    "them", "they", "this", "that", "with", "will", "from", "what", "when",
    "where", "which", "whom", "whose", "were", "been", "being", "have", "does",
    "doing", "done", "would", "could", "should", "there", "their", "about",
    "after", "before", "between", "under", "above", "below", "some", "many",
    "much", "more", "most", "other", "each", "very", "just", "also", "only",
    "into", "onto", "upon", "off", "per", "via",
}


def _extract_tokens(text_value: str) -> set[str]:
    """Extract normalized whole tokens plus sub-tokens split on separators."""
    raw = re.findall(r"[a-zA-Z0-9_#\-]+", text_value.lower())
    tokens: set[str] = set()
    for tok in raw:
        tokens.add(tok)
        for part in re.split(r"[_\-#]+", tok):
            if len(part) >= 2:
                tokens.add(part)
    return tokens


@router.post("/query", response_model=AssistantQueryResponse)
def query_assistant(
    req: AssistantQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask a project question grounded strictly in authorized evidence using Hybrid RAG (pgvector + keyword)."""
    if req.project_id and req.project_id != "default":
        verify_project_access(req.project_id, current_user, db)
        project_id = req.project_id
    else:
        eff = get_effective_project(None, current_user, db)
        if not eff:
            return AssistantQueryResponse(
                answer="No accessible project found in your workspace yet. Create a project and connect sources first.",
                citations=[],
                confidence=0.0,
                is_grounded=False,
                model_used=ai_engine.primary_model_name,
                suggested_followups=["Create a project", "Connect GitHub or upload a document"],
            )
        project_id = eff.id

    all_evidences = db.query(Evidence).filter(Evidence.project_id == project_id).all()
    if not all_evidences:
        return AssistantQueryResponse(
            answer="No supporting evidence found in the connected project repositories, documents, or communication channels to answer this question. Please ensure sources are connected and synchronized.",
            citations=[],
            confidence=0.0,
            is_grounded=False,
            model_used=ai_engine.primary_model_name,
            suggested_followups=[
                "What documents are currently ingested?",
                "What tasks are currently open?",
                "Who are the team members on this project?",
            ],
        )

    ev_by_id = {e.id: e for e in all_evidences}
    q_vec = ai_engine.generate_embedding(req.question)

    # 1. Vector similarity retrieval (native pgvector cosine distance on Postgres, or EmbeddingRecord/backfill on SQLite)
    semantic_scores: Dict[str, float] = {}
    if IS_POSTGRES:
        try:
            vec_literal = "[" + ",".join(f"{x:.6f}" for x in q_vec) + "]"
            rows = db.execute(
                text(
                    "SELECT entity_id, 1 - (embedding_vector <=> CAST(:qvec AS vector)) AS sim "
                    "FROM embedding_records "
                    "WHERE project_id = :pid AND entity_type = 'evidence' AND embedding_vector IS NOT NULL "
                    "ORDER BY embedding_vector <=> CAST(:qvec AS vector) LIMIT 20"
                ),
                {"qvec": vec_literal, "pid": project_id},
            ).fetchall()
            for eid, sim in rows:
                semantic_scores[eid] = float(sim or 0.0)
        except Exception:
            db.rollback()
            semantic_scores = {}

    if not semantic_scores:
        existing_embeddings = {
            er.entity_id: er.embedding
            for er in db.query(EmbeddingRecord)
            .filter(EmbeddingRecord.project_id == project_id, EmbeddingRecord.entity_type == "evidence")
            .all()
        }
        missing_evs = [ev for ev in all_evidences if ev.id not in existing_embeddings]
        if missing_evs:
            batch_texts = [f"{ev.source_title}\n{ev.excerpt}" for ev in missing_evs]
            batch_vecs = ai_engine.generate_embeddings_batch(batch_texts)
            for ev, vec in zip(missing_evs, batch_vecs):
                existing_embeddings[ev.id] = vec
                db.add(
                    EmbeddingRecord(
                        project_id=project_id,
                        entity_type="evidence",
                        entity_id=ev.id,
                        text_content=f"{ev.source_title}\n{ev.excerpt}",
                        embedding=vec,
                        embedding_vector=vec,
                    )
                )
            db.flush()

        for ev in all_evidences:
            ev_vec = existing_embeddings.get(ev.id)
            if ev_vec:
                semantic_scores[ev.id] = ai_engine.cosine_similarity(q_vec, ev_vec)

    # 2. Hybrid scoring: combine semantic vector similarity + exact token overlap + focus match
    raw_words = re.findall(r"[a-zA-Z0-9_#\-]+", req.question.lower())
    meaningful_words: List[str] = []
    for w in raw_words:
        if len(w) >= 3 and w not in STOPWORDS and w not in meaningful_words:
            meaningful_words.append(w)

    scored_docs: List[Dict[str, Any]] = []
    for ev in all_evidences:
        sem = max(0.0, semantic_scores.get(ev.id, 0.0))
        haystack = f"{ev.source_title} {ev.excerpt} {ev.ai_interpretation} {ev.source_author or ''}".lower()
        haystack_tokens = _extract_tokens(haystack)
        keyword_hits = sum(1 for w in meaningful_words if w in haystack_tokens)
        keyword_ratio = (keyword_hits / len(meaningful_words)) if meaningful_words else 0.0

        focus_boost = 0.08 if (req.departing_focus and req.departing_focus.lower() in haystack) else 0.0
        hybrid_score = (0.65 * sem) + (0.35 * keyword_ratio) + focus_boost

        # Strict grounding threshold: require strong semantic match OR >=2 exact keywords (or 1 keyword on short queries with supportive semantic similarity)
        strong_keyword_match = keyword_hits >= 2 or (keyword_hits == 1 and (len(meaningful_words) <= 2 or sem >= 0.42))
        if strong_keyword_match or sem >= 0.56:
            scored_docs.append({
                "doc": {
                    "id": ev.id,
                    "source_type": ev.source_type,
                    "source_title": ev.source_title,
                    "source_url": ev.source_url,
                    "source_author": ev.source_author,
                    "source_timestamp": ev.source_timestamp or ev.created_at,
                    "verification_status": ev.verification_status,
                    "excerpt": ev.excerpt,
                    "ai_interpretation": ev.ai_interpretation,
                    "confidence": ev.confidence,
                    "retrieval_score": min(1.0, hybrid_score),
                },
                "score": hybrid_score,
            })

    scored_docs.sort(key=lambda x: x["score"], reverse=True)
    top_context = [item["doc"] for item in scored_docs[:6]]

    db.commit()

    result = ai_engine.answer_question(
        question=req.question,
        context_docs=top_context,
        departing_name=req.departing_focus,
    )

    return AssistantQueryResponse(
        answer=result["answer"],
        citations=result["citations"],
        confidence=result["confidence"],
        confidence_breakdown=result.get("confidence_breakdown"),
        is_grounded=result["is_grounded"],
        model_used=result["model_used"],
        suggested_followups=result["suggested_followups"],
    )
