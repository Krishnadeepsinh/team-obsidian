import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import IS_POSTGRES, get_db
from app.core.permissions import get_effective_project, verify_project_access
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.knowledge import (
    AssistantConversation,
    AssistantMessage,
    Decision,
    EmbeddingRecord,
    KnowledgeGap,
)
from app.models.workspace import User
from app.schemas.knowledge import (
    AssistantConversationDetail,
    AssistantConversationSummary,
    AssistantMessageOut,
    AssistantPromoteRequest,
    AssistantQueryRequest,
    AssistantQueryResponse,
)
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity

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
    "onto", "upon", "off", "per", "via",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _derive_title(question: str) -> str:
    clean = re.sub(r"\s+", " ", (question or "").strip())
    if not clean:
        return "New Conversation"
    return clean if len(clean) <= 72 else clean[:69].rstrip() + "..."


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


def _resolve_project_id(req_project_id: Optional[str], current_user: User, db: Session) -> Optional[str]:
    if req_project_id and req_project_id != "default":
        verify_project_access(req_project_id, current_user, db)
        return req_project_id
    eff = get_effective_project(None, current_user, db)
    return eff.id if eff else None


def _load_owned_conversation(
    conversation_id: str,
    current_user: User,
    db: Session,
    project_id: Optional[str] = None,
) -> AssistantConversation:
    conv = db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first()
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if project_id and conv.project_id != project_id:
        raise HTTPException(status_code=404, detail="Conversation does not belong to the selected project")
    verify_project_access(conv.project_id, current_user, db)
    return conv


def _retrieve_hybrid_context(
    project_id: str,
    question: str,
    departing_focus: Optional[str],
    all_evidences: List[Evidence],
    db: Session,
) -> List[Dict[str, Any]]:
    q_vec = ai_engine.generate_embedding(question)

    # 1. Vector similarity retrieval (native pgvector cosine distance on Postgres, or EmbeddingRecord backfill on SQLite)
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
            try:
                batch_texts = [f"{ev.source_title}\n{ev.excerpt}" for ev in missing_evs]
                batch_vecs = ai_engine.generate_embeddings_batch(batch_texts)
                if len(batch_vecs) == len(missing_evs):
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
            except Exception:
                db.rollback()

        for ev in all_evidences:
            ev_vec = existing_embeddings.get(ev.id)
            if ev_vec:
                semantic_scores[ev.id] = ai_engine.cosine_similarity(q_vec, ev_vec)

    # 2. Hybrid scoring: combine semantic vector similarity + exact token overlap + focus match
    raw_words = re.findall(r"[a-zA-Z0-9_#\-]+", question.lower())
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

        focus_boost = 0.08 if (departing_focus and departing_focus.lower() in haystack) else 0.0
        hybrid_score = (0.65 * sem) + (0.35 * keyword_ratio) + focus_boost

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
    return [item["doc"] for item in scored_docs[:6]]


def _execute_assistant_turn(
    req: AssistantQueryRequest,
    current_user: User,
    db: Session,
) -> AssistantQueryResponse:
    project_id = _resolve_project_id(req.project_id, current_user, db)
    if not project_id:
        return AssistantQueryResponse(
            answer="No accessible project found in your workspace yet. Create a project and connect sources first.",
            citations=[],
            confidence=0.0,
            is_grounded=False,
            model_used=ai_engine.primary_model_name,
            suggested_followups=["Create a project", "Connect GitHub or upload a document"],
        )

    # Resolve or create persistent conversation thread
    if req.conversation_id:
        conv = _load_owned_conversation(req.conversation_id, current_user, db, project_id=project_id)
        if req.departing_focus and not conv.departing_focus:
            conv.departing_focus = req.departing_focus
    else:
        conv = AssistantConversation(
            project_id=project_id,
            user_id=current_user.id,
            title=_derive_title(req.question),
            departing_focus=req.departing_focus,
        )
        db.add(conv)
        db.flush()

    prior_turns = [
        {"role": m.role, "content": m.content}
        for m in (
            db.query(AssistantMessage)
            .filter(AssistantMessage.conversation_id == conv.id)
            .order_by(AssistantMessage.created_at.asc())
            .all()
        )
    ]

    user_msg = AssistantMessage(
        conversation_id=conv.id,
        role="user",
        content=req.question.strip(),
        is_grounded=True,
    )
    db.add(user_msg)
    db.flush()

    all_evidences = db.query(Evidence).filter(Evidence.project_id == project_id).all()
    if not all_evidences:
        result: Dict[str, Any] = {
            "answer": "No supporting evidence found in the connected project repositories, documents, or communication channels to answer this question. Please ensure sources are connected and synchronized.",
            "citations": [],
            "confidence": 0.0,
            "confidence_breakdown": None,
            "is_grounded": False,
            "model_used": ai_engine.primary_model_name,
            "suggested_followups": [
                "What documents are currently ingested?",
                "What tasks are currently open?",
                "Who are the team members on this project?",
            ],
        }
    else:
        top_context = _retrieve_hybrid_context(
            project_id=project_id,
            question=req.question,
            departing_focus=req.departing_focus,
            all_evidences=all_evidences,
            db=db,
        )
        result = ai_engine.answer_question(
            question=req.question,
            context_docs=top_context,
            departing_name=req.departing_focus,
            conversation_history=prior_turns,
        )

    assistant_msg = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content=result["answer"],
        citations_json=result.get("citations") or [],
        confidence=result.get("confidence"),
        confidence_breakdown_json=result.get("confidence_breakdown") or {},
        is_grounded=bool(result.get("is_grounded", False)),
        model_used=result.get("model_used"),
        suggested_followups_json=result.get("suggested_followups") or [],
    )
    db.add(assistant_msg)
    conv.updated_at = _utc_now()
    db.commit()
    db.refresh(assistant_msg)

    return AssistantQueryResponse(
        answer=result["answer"],
        citations=result["citations"],
        confidence=result["confidence"],
        confidence_breakdown=result.get("confidence_breakdown"),
        is_grounded=result["is_grounded"],
        model_used=result["model_used"],
        suggested_followups=result["suggested_followups"],
        conversation_id=conv.id,
        message_id=assistant_msg.id,
    )


def _format_sse(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.post("/query", response_model=AssistantQueryResponse)
def query_assistant(
    req: AssistantQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask a project question grounded strictly in authorized evidence using Hybrid RAG (pgvector + keyword)."""
    return _execute_assistant_turn(req, current_user, db)


@router.post("/query/stream")
def query_assistant_stream(
    req: AssistantQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream an evidence-grounded AI Assistant response over Server-Sent Events (SSE) and persist the thread."""
    response_obj = _execute_assistant_turn(req, current_user, db)

    def _event_stream() -> Iterator[str]:
        yield _format_sse(
            "meta",
            {
                "conversation_id": response_obj.conversation_id,
                "message_id": response_obj.message_id,
                "model_used": response_obj.model_used,
            },
        )
        # Stream answer tokens cleanly in small word groups so the UI renders incremental progress
        chunks = re.findall(r"\S+\s*", response_obj.answer or "")
        if not chunks:
            yield _format_sse("token", {"text": response_obj.answer or ""})
        else:
            step = 3
            for i in range(0, len(chunks), step):
                yield _format_sse("token", {"text": "".join(chunks[i : i + step])})

        yield _format_sse("done", response_obj.model_dump())

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=List[AssistantConversationSummary])
def list_conversations(
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List saved AI Assistant conversations for the current user in the active project."""
    resolved_pid = _resolve_project_id(project_id, current_user, db)
    if not resolved_pid:
        return []

    convs = (
        db.query(AssistantConversation)
        .filter(
            AssistantConversation.project_id == resolved_pid,
            AssistantConversation.user_id == current_user.id,
        )
        .order_by(AssistantConversation.updated_at.desc())
        .limit(50)
        .all()
    )
    if not convs:
        return []

    counts_rows = (
        db.query(AssistantMessage.conversation_id, func.count(AssistantMessage.id))
        .filter(AssistantMessage.conversation_id.in_([c.id for c in convs]))
        .group_by(AssistantMessage.conversation_id)
        .all()
    )
    counts = {cid: int(cnt) for cid, cnt in counts_rows}

    return [
        AssistantConversationSummary(
            id=c.id,
            project_id=c.project_id,
            title=c.title,
            departing_focus=c.departing_focus,
            message_count=counts.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in convs
    ]


@router.get("/conversations/{conversation_id}", response_model=AssistantConversationDetail)
def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a single conversation and all ordered messages owned by the current user."""
    conv = _load_owned_conversation(conversation_id, current_user, db)
    msgs = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conv.id)
        .order_by(AssistantMessage.created_at.asc())
        .all()
    )
    return AssistantConversationDetail(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title,
        departing_focus=conv.departing_focus,
        messages=[
            AssistantMessageOut(
                id=m.id,
                conversation_id=m.conversation_id,
                role=m.role,
                content=m.content,
                citations=m.citations_json or [],
                confidence=m.confidence,
                confidence_breakdown=m.confidence_breakdown_json or None,
                is_grounded=bool(m.is_grounded),
                model_used=m.model_used,
                suggested_followups=m.suggested_followups_json or [],
                created_at=m.created_at,
            )
            for m in msgs
        ],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a saved AI Assistant conversation owned by the current user."""
    conv = _load_owned_conversation(conversation_id, current_user, db)
    db.delete(conv)
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}


@router.post("/promote")
def promote_assistant_insight(
    req: AssistantPromoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote an AI Assistant finding directly into a persisted Decision (ADR) or Knowledge Gap."""
    eff_proj = get_effective_project(req.project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=400, detail="No accessible project found.")

    clean_type = (req.target_type or "").strip().lower()
    clean_title = (req.title or "").strip()[:480]
    clean_content = (req.content or "").strip()
    if not clean_title or not clean_content:
        raise HTTPException(status_code=400, detail="Title and content are required.")

    ev_ids = [eid for eid in (req.evidence_ids or []) if eid]

    if clean_type == "decision":
        d = Decision(
            project_id=eff_proj.id,
            created_by_user_id=current_user.id,
            title=clean_title,
            summary=clean_content[:1200],
            reasoning=clean_content,
            decision_maker=current_user.name or current_user.email,
            date=_utc_now().strftime("%Y-%m-%d"),
            component=req.component or "Architecture",
            decision_type="technical",
            status="accepted",
            verification_status="Supported by Evidence" if ev_ids else "Verified by Reviewer",
            evidence_ids=ev_ids,
            confidence=0.9 if ev_ids else 0.75,
        )
        db.add(d)
        db.flush()
        record_activity(
            db=db,
            action="decision.promoted_from_assistant",
            entity_type="decision",
            entity_id=d.id,
            user_id=current_user.id,
            project_id=eff_proj.id,
            actor_email=current_user.email,
            details={"message": f"Promoted AI Assistant insight to Decision '{d.title}'"},
        )
        db.commit()
        return {"status": "created", "target_type": "decision", "id": d.id, "title": d.title}

    if clean_type == "gap":
        sev = (req.severity or "high").strip().lower()
        if sev not in {"critical", "high", "medium", "low"}:
            sev = "high"
        g = KnowledgeGap(
            project_id=eff_proj.id,
            title=clean_title,
            description=clean_content,
            gap_type="assistant_flagged",
            severity=sev,
            priority=sev,
            impact="Identified during AI Assistant knowledge verification.",
            business_impact="May delay smooth project transition if left undocumented.",
            technical_impact="Requires owner review and source evidence linkage.",
            recommended_action="Assign an owner to document and verify missing context.",
            assigned_reviewer=current_user.name or current_user.email,
        )
        db.add(g)
        db.flush()
        record_activity(
            db=db,
            action="gap.promoted_from_assistant",
            entity_type="knowledge_gap",
            entity_id=g.id,
            user_id=current_user.id,
            project_id=eff_proj.id,
            actor_email=current_user.email,
            details={"message": f"Logged Knowledge Gap '{g.title}' from AI Assistant"},
        )
        db.commit()
        return {"status": "created", "target_type": "gap", "id": g.id, "title": g.title}

    raise HTTPException(status_code=400, detail="target_type must be 'decision' or 'gap'")
