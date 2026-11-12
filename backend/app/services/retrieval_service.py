"""Multi-Entity Hybrid Graph-RAG retrieval service for Team Obsidian."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import IS_POSTGRES
from app.models.evidence import Evidence
from app.models.knowledge import (
    Decision,
    Dependency,
    EmbeddingRecord,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    Responsibility,
    RiskItem,
    TaskItem,
)
from app.services.ai_engine import ai_engine

logger = logging.getLogger(__name__)

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
    "onto", "upon", "off", "per", "via", "tell", "explain", "show", "give",
    "know", "project", "system", "code", "work", "does",
}


def extract_tokens(text_value: str) -> List[str]:
    """Extract normalized ordered tokens plus sub-tokens split on separators."""
    raw = re.findall(r"[a-zA-Z0-9_#\-]+", (text_value or "").lower())
    tokens: List[str] = []
    for tok in raw:
        tokens.append(tok)
        for part in re.split(r"[_\-#]+", tok):
            if len(part) >= 2 and part != tok:
                tokens.append(part)
    return tokens


def _meaningful_terms(text_value: str) -> List[str]:
    return [t for t in extract_tokens(text_value) if len(t) >= 3 and t not in STOPWORDS]


def _serialize_ts(val: Any) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _evidence_entity_type(ev: Evidence) -> str:
    if getattr(ev, "parent_evidence_id", None) or (getattr(ev, "chunk_index", 0) or 0) > 0:
        return "evidence_chunk"
    return "evidence"


def _build_evidence_index_text(ev: Evidence) -> str:
    body = (getattr(ev, "full_text", None) or ev.excerpt or "").strip()
    meta_bits = [
        f"Title: {ev.source_title or ''}",
        f"Source: {ev.source_type or ''}",
        f"Author: {ev.source_author or 'unknown'}",
    ]
    if getattr(ev, "chunk_index", 0) is not None and (getattr(ev, "total_chunks", 1) or 1) > 1:
        meta_bits.append(f"Chunk: {ev.chunk_index + 1}/{ev.total_chunks}")
    header = " | ".join(meta_bits)
    interp = f"\nInterpretation: {ev.ai_interpretation}" if ev.ai_interpretation else ""
    return f"{header}\n{body[:2400]}{interp}".strip()


def _build_candidate_pool(
    project_id: str,
    db: Session,
    all_evidences: Optional[List[Evidence]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Evidence], List[KnowledgeEntity], List[KnowledgeRelationship]]:
    """Collect unified retrievable items across Evidence chunks and structured KT entities."""
    evidences = (
        all_evidences
        if all_evidences is not None
        else db.query(Evidence).filter(Evidence.project_id == project_id).all()
    )
    evidence_by_id: Dict[str, Evidence] = {ev.id: ev for ev in evidences}
    children_by_parent: Dict[str, List[Evidence]] = defaultdict(list)
    for ev in evidences:
        pid = getattr(ev, "parent_evidence_id", None)
        if pid:
            children_by_parent[pid].append(ev)
    for pid in children_by_parent:
        children_by_parent[pid].sort(key=lambda c: getattr(c, "chunk_index", 0) or 0)

    candidates: List[Dict[str, Any]] = []

    for ev in evidences:
        etype = _evidence_entity_type(ev)
        raw_full = (getattr(ev, "full_text", None) or ev.excerpt or "").strip()
        # Parent-window context expansion: pull parent / sibling text if chunk is part of a parent
        parent_id = getattr(ev, "parent_evidence_id", None)
        if parent_id and parent_id in evidence_by_id:
            parent_ev = evidence_by_id[parent_id]
            parent_body = (getattr(parent_ev, "full_text", None) or parent_ev.excerpt or "").strip()
            sibling_list = children_by_parent.get(parent_id, [])
            cur_idx = getattr(ev, "chunk_index", 0) or 0
            window_parts = [f"Title: {ev.source_title}"]
            if parent_body and parent_body != raw_full:
                window_parts.append(f"Overview: {parent_body[:380]}")
            for sib in sibling_list:
                s_idx = getattr(sib, "chunk_index", 0) or 0
                if abs(s_idx - cur_idx) <= 1:
                    sib_txt = (getattr(sib, "full_text", None) or sib.excerpt or "").strip()
                    if sib_txt:
                        window_parts.append(sib_txt)
            full_context = "\n\n".join(window_parts)[:1400]
        elif ev.id in children_by_parent and len(raw_full) < 900:
            child_snippets = [
                (getattr(c, "full_text", None) or c.excerpt or "").strip()
                for c in children_by_parent[ev.id][:2]
            ]
            combined = "\n\n".join([raw_full] + [s for s in child_snippets if s and s != raw_full])
            full_context = combined[:1400]
        else:
            full_context = raw_full[:1400]

        if ev.ai_interpretation and ev.ai_interpretation not in full_context and len(full_context) < 1200:
            full_context = f"{full_context}\nInterpretation: {ev.ai_interpretation}"[:1400]

        candidates.append(
            {
                "key": f"{etype}:{ev.id}",
                "entity_type": etype,
                "entity_id": ev.id,
                "parent_id": parent_id,
                "chunk_index": getattr(ev, "chunk_index", 0) or 0,
                "evidence_id": ev.id,
                "source_type": ev.source_type or "document",
                "source_title": ev.source_title or "Untitled Evidence",
                "source_url": ev.source_url,
                "source_author": ev.source_author,
                "source_timestamp": _serialize_ts(ev.source_timestamp or ev.created_at),
                "verification_status": ev.verification_status or "unverified",
                "excerpt": (ev.excerpt or raw_full)[:500],
                "full_context": full_context or (ev.excerpt or "")[:1400],
                "index_text": _build_evidence_index_text(ev),
                "confidence": float(ev.confidence if ev.confidence is not None else 0.7),
                "evidence_ids": [ev.id],
                "owner_hint": ev.source_author or "",
                "component_hint": "",
            }
        )

    def _pick_evidence_meta(ev_ids: Any) -> Tuple[str, Optional[str]]:
        if isinstance(ev_ids, list):
            for eid in ev_ids:
                if eid in evidence_by_id:
                    ev_obj = evidence_by_id[eid]
                    return eid, ev_obj.source_url
        return "", None

    for d in db.query(Decision).filter(Decision.project_id == project_id).all():
        linked_eid, linked_url = _pick_evidence_meta(d.evidence_ids)
        full_ctx = (
            f"Decision: {d.title}\n"
            f"Component: {d.component or 'General'} | Maker: {d.decision_maker or 'Unknown'} | Status: {d.status}\n"
            f"Summary: {d.summary or ''}\n"
            f"Reasoning: {d.reasoning or ''}\n"
            f"Tradeoffs: {d.tradeoffs or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"decision:{d.id}",
                "entity_type": "decision",
                "entity_id": d.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": linked_eid or d.id,
                "source_type": "decision",
                "source_title": f"[Decision] {d.title}",
                "source_url": linked_url,
                "source_author": d.decision_maker,
                "source_timestamp": _serialize_ts(d.date or d.created_at),
                "verification_status": d.verification_status or "ai_drafted",
                "excerpt": (d.summary or d.reasoning or d.title)[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": float(d.confidence if d.confidence is not None else 0.8),
                "evidence_ids": list(d.evidence_ids or []),
                "owner_hint": d.decision_maker or "",
                "component_hint": d.component or "",
            }
        )

    for r in db.query(RiskItem).filter(RiskItem.project_id == project_id).all():
        linked_eid, linked_url = _pick_evidence_meta(r.evidence_ids)
        comps = ", ".join(r.related_components or [])
        full_ctx = (
            f"Risk ({r.severity}/{r.category}): {r.title}\n"
            f"Owner: {r.owner or 'Unassigned'} | Components: {comps or 'General'} | Status: {r.status}\n"
            f"Description: {r.description or ''}\n"
            f"Mitigation: {r.mitigation_strategy or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"risk:{r.id}",
                "entity_type": "risk",
                "entity_id": r.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": linked_eid or r.id,
                "source_type": "risk",
                "source_title": f"[Risk] {r.title}",
                "source_url": linked_url,
                "source_author": r.owner,
                "source_timestamp": _serialize_ts(r.created_at),
                "verification_status": r.verification_status or "ai_drafted",
                "excerpt": (r.description or r.title)[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": 0.8,
                "evidence_ids": list(r.evidence_ids or []),
                "owner_hint": r.owner or "",
                "component_hint": comps,
            }
        )

    for g in db.query(KnowledgeGap).filter(KnowledgeGap.project_id == project_id).all():
        linked_eid, linked_url = _pick_evidence_meta(g.evidence_ids)
        full_ctx = (
            f"Knowledge Gap ({g.severity}/{g.gap_type}): {g.title}\n"
            f"Status: {g.status} | Reviewer: {g.assigned_reviewer or 'Unassigned'}\n"
            f"Description: {g.description or ''}\n"
            f"Impact: {g.impact or ''}\n"
            f"Recommended Action: {g.recommended_action or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"gap:{g.id}",
                "entity_type": "gap",
                "entity_id": g.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": linked_eid or g.id,
                "source_type": "gap",
                "source_title": f"[Knowledge Gap] {g.title}",
                "source_url": linked_url,
                "source_author": g.assigned_reviewer,
                "source_timestamp": _serialize_ts(g.created_at),
                "verification_status": g.status or "open",
                "excerpt": (g.description or g.impact or g.title)[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": 0.85,
                "evidence_ids": list(g.evidence_ids or []),
                "owner_hint": g.assigned_reviewer or "",
                "component_hint": g.gap_type or "",
            }
        )

    for dep in db.query(Dependency).filter(Dependency.project_id == project_id).all():
        linked_eid, linked_url = _pick_evidence_meta(dep.evidence_ids)
        full_ctx = (
            f"Dependency: {dep.source_component} -> {dep.target_component} ({dep.dependency_type})\n"
            f"Criticality: {dep.criticality} | Owner: {dep.owner or 'Unknown'}\n"
            f"Description: {dep.description or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"dependency:{dep.id}",
                "entity_type": "dependency",
                "entity_id": dep.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": linked_eid or dep.id,
                "source_type": "dependency",
                "source_title": f"[Dependency] {dep.source_component} -> {dep.target_component}",
                "source_url": linked_url,
                "source_author": dep.owner,
                "source_timestamp": _serialize_ts(dep.created_at),
                "verification_status": dep.verification_status or "ai_drafted",
                "excerpt": (dep.description or f"{dep.source_component} depends on {dep.target_component}")[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": 0.8,
                "evidence_ids": list(dep.evidence_ids or []),
                "owner_hint": dep.owner or "",
                "component_hint": f"{dep.source_component} {dep.target_component}",
            }
        )

    for task in db.query(TaskItem).filter(TaskItem.project_id == project_id).all():
        linked_eid, linked_url = _pick_evidence_meta(task.evidence_ids)
        full_ctx = (
            f"Task ({task.priority}/{task.status}): {task.title}\n"
            f"Owner: {task.owner or 'Unassigned'} | Component: {task.component or 'General'}\n"
            f"Reassignment: {task.suggested_reassignment or 'None'}\n"
            f"Description: {task.description or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"task:{task.id}",
                "entity_type": "task",
                "entity_id": task.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": linked_eid or task.id,
                "source_type": "task",
                "source_title": f"[Task] {task.title}",
                "source_url": linked_url,
                "source_author": task.owner,
                "source_timestamp": _serialize_ts(task.updated_at or task.created_at),
                "verification_status": task.verification_status or "ai_drafted",
                "excerpt": (task.description or task.title)[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": float(task.confidence if task.confidence is not None else 0.78),
                "evidence_ids": list(task.evidence_ids or []),
                "owner_hint": task.owner or "",
                "component_hint": task.component or "",
            }
        )

    for resp in db.query(Responsibility).filter(Responsibility.project_id == project_id).all():
        linked_eid, linked_url = _pick_evidence_meta(resp.evidence_ids)
        full_ctx = (
            f"Responsibility: {resp.domain}\n"
            f"Primary Owner: {resp.owner} | Backup Owner: {resp.backup_owner or 'NONE (SPOF)'} | Criticality: {resp.criticality}\n"
            f"Scope: {resp.scope or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"responsibility:{resp.id}",
                "entity_type": "responsibility",
                "entity_id": resp.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": linked_eid or resp.id,
                "source_type": "responsibility",
                "source_title": f"[Ownership] {resp.domain} ({resp.owner})",
                "source_url": linked_url,
                "source_author": resp.owner,
                "source_timestamp": _serialize_ts(resp.created_at),
                "verification_status": resp.verification_status or "ai_drafted",
                "excerpt": (resp.scope or f"{resp.owner} owns {resp.domain}")[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": 0.85,
                "evidence_ids": list(resp.evidence_ids or []),
                "owner_hint": f"{resp.owner} {resp.backup_owner or ''}",
                "component_hint": resp.domain,
            }
        )

    entities = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).all()
    relationships = (
        db.query(KnowledgeRelationship)
        .filter(KnowledgeRelationship.project_id == project_id)
        .all()
    )
    for ent in entities:
        ev_obj = evidence_by_id.get(ent.evidence_id) if ent.evidence_id else None
        full_ctx = (
            f"Knowledge Entity ({ent.entity_type}): {ent.name}\n"
            f"Description: {ent.description or ''}"
        ).strip()[:1400]
        candidates.append(
            {
                "key": f"knowledge_entity:{ent.id}",
                "entity_type": "knowledge_entity",
                "entity_id": ent.id,
                "parent_id": None,
                "chunk_index": 0,
                "evidence_id": ent.evidence_id or ent.id,
                "source_type": f"graph:{ent.entity_type}",
                "source_title": f"[{ent.entity_type.title()}] {ent.name}",
                "source_url": ev_obj.source_url if ev_obj else None,
                "source_author": ev_obj.source_author if ev_obj else None,
                "source_timestamp": _serialize_ts(ent.updated_at or ent.created_at),
                "verification_status": ent.verification_status or "ai_drafted",
                "excerpt": (ent.description or ent.name)[:500],
                "full_context": full_ctx,
                "index_text": full_ctx,
                "confidence": float(ent.confidence if ent.confidence is not None else 0.75),
                "evidence_ids": [ent.evidence_id] if ent.evidence_id else [],
                "owner_hint": ent.name if ent.entity_type == "person" else "",
                "component_hint": ent.name,
            }
        )

    return candidates, evidence_by_id, entities, relationships


def _ensure_candidate_embeddings(
    project_id: str,
    candidates: List[Dict[str, Any]],
    db: Session,
) -> Dict[Tuple[str, str], EmbeddingRecord]:
    """Ensure every candidate entity has a normalized RETRIEVAL_DOCUMENT embedding."""
    existing_records = (
        db.query(EmbeddingRecord)
        .filter(EmbeddingRecord.project_id == project_id)
        .all()
    )
    emb_map: Dict[Tuple[str, str], EmbeddingRecord] = {
        (rec.entity_type, rec.entity_id): rec for rec in existing_records
    }

    missing: List[Dict[str, Any]] = []
    for cand in candidates:
        key = (cand["entity_type"], cand["entity_id"])
        rec = emb_map.get(key)
        # Re-use legacy 'evidence' records if present for evidence_chunk to avoid duplicate calls
        if rec is None and cand["entity_type"] == "evidence_chunk":
            rec = emb_map.get(("evidence", cand["entity_id"]))
            if rec is not None:
                emb_map[key] = rec
        if rec is None or not rec.embedding:
            missing.append(cand)

    if missing:
        try:
            vectors = ai_engine.generate_embeddings_batch(
                [c["index_text"] for c in missing],
                task_type="RETRIEVAL_DOCUMENT",
            )
            for cand, vec in zip(missing, vectors):
                existing = emb_map.get((cand["entity_type"], cand["entity_id"]))
                if existing is not None:
                    existing.text_content = cand["index_text"][:2000]
                    existing.embedding = vec
                    existing.embedding_vector = vec
                    existing.task_type = "RETRIEVAL_DOCUMENT"
                    existing.parent_id = cand.get("parent_id")
                    existing.chunk_index = cand.get("chunk_index", 0)
                else:
                    rec = EmbeddingRecord(
                        project_id=project_id,
                        entity_type=cand["entity_type"],
                        entity_id=cand["entity_id"],
                        parent_id=cand.get("parent_id"),
                        chunk_index=cand.get("chunk_index", 0),
                        task_type="RETRIEVAL_DOCUMENT",
                        text_content=cand["index_text"][:2000],
                        embedding=vec,
                        embedding_vector=vec,
                    )
                    db.add(rec)
                    emb_map[(cand["entity_type"], cand["entity_id"])] = rec
            db.flush()
        except Exception as exc:
            logger.warning("Failed indexing missing retrieval embeddings: %s", exc)

    return emb_map


def _compute_dense_scores(
    project_id: str,
    query_vector: List[float],
    candidates: List[Dict[str, Any]],
    emb_map: Dict[Tuple[str, str], EmbeddingRecord],
    db: Session,
) -> Dict[str, float]:
    """Compute vector cosine similarity (pgvector on Postgres, exact cosine in Python on SQLite)."""
    dense_scores: Dict[str, float] = {}
    if not query_vector or not any(query_vector):
        return dense_scores

    if IS_POSTGRES:
        try:
            vec_literal = "[" + ",".join(f"{v:.6f}" for v in query_vector) + "]"
            pg_rows = db.execute(
                text(
                    """
                    SELECT entity_type, entity_id, 1 - (embedding_vector <=> CAST(:qvec AS vector)) AS similarity
                    FROM embedding_records
                    WHERE project_id = :pid AND embedding_vector IS NOT NULL
                    ORDER BY embedding_vector <=> CAST(:qvec AS vector)
                    LIMIT 60
                    """
                ),
                {"qvec": vec_literal, "pid": project_id},
            ).fetchall()
            pg_map = {(r[0], r[1]): float(r[2] or 0.0) for r in pg_rows}
            for cand in candidates:
                sim = pg_map.get((cand["entity_type"], cand["entity_id"]))
                if sim is not None:
                    dense_scores[cand["key"]] = sim
            if dense_scores:
                return dense_scores
        except Exception as exc:
            logger.debug("pgvector fast path unavailable, using Python cosine fallback: %s", exc)

    for cand in candidates:
        rec = emb_map.get((cand["entity_type"], cand["entity_id"]))
        if rec and rec.embedding:
            dense_scores[cand["key"]] = float(ai_engine.cosine_similarity(query_vector, rec.embedding))

    return dense_scores


def _compute_bm25_scores(
    query_terms: List[str],
    candidates: List[Dict[str, Any]],
) -> Tuple[Dict[str, float], Dict[str, int]]:
    """Compute corpus BM25 (k1=1.5, b=0.75) plus exact meaningful term hit counts."""
    if not query_terms or not candidates:
        return {}, {}

    k1 = 1.5
    b = 0.75
    n_docs = len(candidates)
    doc_tokens: Dict[str, Counter] = {}
    doc_lengths: Dict[str, int] = {}
    df: Counter = Counter()

    for cand in candidates:
        toks = extract_tokens(
            f"{cand['source_title']} {cand['full_context']} {cand.get('owner_hint', '')} {cand.get('component_hint', '')}"
        )
        counts = Counter(toks)
        doc_tokens[cand["key"]] = counts
        doc_lengths[cand["key"]] = max(len(toks), 1)
        for term in counts.keys():
            df[term] += 1

    avgdl = sum(doc_lengths.values()) / max(n_docs, 1)
    unique_terms = list(dict.fromkeys(query_terms))

    bm25_scores: Dict[str, float] = {}
    hit_counts: Dict[str, int] = {}

    for cand in candidates:
        key = cand["key"]
        counts = doc_tokens[key]
        dl = doc_lengths[key]
        score = 0.0
        hits = 0
        for term in unique_terms:
            tf = counts.get(term, 0)
            if tf <= 0:
                continue
            hits += 1
            n_q = df.get(term, 0)
            idf = math.log(1.0 + (n_docs - n_q + 0.5) / (n_q + 0.5))
            denom = tf + k1 * (1.0 - b + b * (dl / max(avgdl, 1.0)))
            score += idf * ((tf * (k1 + 1.0)) / max(denom, 1e-9))
        bm25_scores[key] = score
        hit_counts[key] = hits

    return bm25_scores, hit_counts


def _expand_graph_neighborhood(
    question: str,
    query_terms: List[str],
    departing_focus: Optional[str],
    candidates: List[Dict[str, Any]],
    evidence_by_id: Dict[str, Evidence],
    entities: List[KnowledgeEntity],
    relationships: List[KnowledgeRelationship],
    seed_keys: List[str],
) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """Perform 1-hop knowledge graph expansion across entities, relationships, and evidence links."""
    graph_boosts: Dict[str, float] = defaultdict(float)
    synthetic_graph_docs: List[Dict[str, Any]] = []

    if not entities:
        return graph_boosts, synthetic_graph_docs

    entity_by_id = {e.id: e for e in entities}
    seed_evidence_ids = set()
    seed_terms = set(query_terms)
    if departing_focus:
        seed_terms.update(_meaningful_terms(departing_focus))

    cand_by_key = {c["key"]: c for c in candidates}
    for key in seed_keys:
        cand = cand_by_key.get(key)
        if not cand:
            continue
        for eid in cand.get("evidence_ids") or []:
            seed_evidence_ids.add(eid)
        seed_terms.update(_meaningful_terms(cand.get("component_hint", "")))

    matched_entity_ids: set[str] = set()
    for ent in entities:
        ent_tokens = set(extract_tokens(f"{ent.name} {ent.description or ''}"))
        if (seed_terms & ent_tokens) or (ent.evidence_id and ent.evidence_id in seed_evidence_ids):
            matched_entity_ids.add(ent.id)

    if not matched_entity_ids:
        return graph_boosts, synthetic_graph_docs

    neighbor_evidence_ids: set[str] = set()
    neighbor_names: set[str] = set()
    summary_lines_by_ent: Dict[str, List[str]] = defaultdict(list)

    for rel in relationships:
        src = entity_by_id.get(rel.source_entity_id)
        tgt = entity_by_id.get(rel.target_entity_id)
        if not src or not tgt:
            continue
        if src.id in matched_entity_ids or tgt.id in matched_entity_ids:
            neighbor_names.add(src.name.lower())
            neighbor_names.add(tgt.name.lower())
            if src.evidence_id:
                neighbor_evidence_ids.add(src.evidence_id)
            if tgt.evidence_id:
                neighbor_evidence_ids.add(tgt.evidence_id)
            if rel.evidence_id:
                neighbor_evidence_ids.add(rel.evidence_id)
            anchor_id = src.id if src.id in matched_entity_ids else tgt.id
            ctx = f" ({rel.context[:120]})" if rel.context else ""
            summary_lines_by_ent[anchor_id].append(
                f"{src.name} [{src.entity_type}] --{rel.relation_type}--> {tgt.name} [{tgt.entity_type}]{ctx}"
            )

    # Boost candidates linked to expanded graph neighbors
    for cand in candidates:
        cand_eids = set(cand.get("evidence_ids") or [])
        if cand_eids & neighbor_evidence_ids:
            graph_boosts[cand["key"]] += 0.25
        comp_lower = (cand.get("component_hint") or "").lower()
        owner_lower = (cand.get("owner_hint") or "").lower()
        if any(n and (n in comp_lower or n in owner_lower) for n in neighbor_names):
            graph_boosts[cand["key"]] += 0.20

    # Create up to 2 compact synthetic 1-hop graph neighborhood docs when relationships exist
    ranked_anchors = sorted(
        summary_lines_by_ent.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    )[:2]
    for anchor_id, lines in ranked_anchors:
        anchor = entity_by_id.get(anchor_id)
        if not anchor or not lines:
            continue
        linked_eid = anchor.evidence_id or anchor.id
        ev_obj = evidence_by_id.get(linked_eid)
        block = f"1-Hop Knowledge Graph around {anchor.name} ({anchor.entity_type}):\n" + "\n".join(
            f"- {line}" for line in lines[:8]
        )
        synthetic_graph_docs.append(
            {
                "key": f"knowledge_graph:{anchor.id}",
                "entity_type": "knowledge_graph",
                "entity_id": anchor.id,
                "evidence_id": linked_eid,
                "source_type": "knowledge_graph",
                "source_title": f"[Graph Neighborhood] {anchor.name}",
                "source_url": ev_obj.source_url if ev_obj else None,
                "source_author": ev_obj.source_author if ev_obj else None,
                "source_timestamp": _serialize_ts(anchor.updated_at or anchor.created_at),
                "verification_status": anchor.verification_status or "ai_drafted",
                "excerpt": "; ".join(lines[:3])[:500],
                "full_context": block[:1400],
                "confidence": 0.86,
                "rrf_score": 0.032 + min(0.015, 0.003 * len(lines)),
            }
        )

    return graph_boosts, synthetic_graph_docs


def _mmr_select(
    ranked_items: List[Dict[str, Any]],
    dense_vectors: Dict[str, List[float]],
    top_k: int,
    lambda_param: float = 0.72,
) -> List[Dict[str, Any]]:
    """Apply Maximal Marginal Relevance (MMR) while limiting duplicate chunks from the same parent."""
    if len(ranked_items) <= top_k:
        return ranked_items

    max_score = max((item["rrf_score"] for item in ranked_items), default=1.0) or 1.0
    selected: List[Dict[str, Any]] = []
    remaining = list(ranked_items)
    parent_counts: Counter = Counter()

    while remaining and len(selected) < top_k:
        best_idx = 0
        best_mmr = -1e9
        for idx, cand in enumerate(remaining):
            rel = cand["rrf_score"] / max_score
            c_parent = cand.get("parent_id") or cand.get("entity_id")
            redundancy = 0.0
            c_vec = dense_vectors.get(cand["key"])
            if selected:
                for sel in selected:
                    s_vec = dense_vectors.get(sel["key"])
                    if c_vec and s_vec:
                        sim = max(0.0, float(ai_engine.cosine_similarity(c_vec, s_vec)))
                    else:
                        c_toks = set(extract_tokens(cand["source_title"] + " " + cand["excerpt"]))
                        s_toks = set(extract_tokens(sel["source_title"] + " " + sel["excerpt"]))
                        union = len(c_toks | s_toks) or 1
                        sim = len(c_toks & s_toks) / union
                    if sim > redundancy:
                        redundancy = sim
            # Mild diversity penalty if picking >2 chunks from the same parent document
            parent_penalty = 0.15 * max(0, parent_counts.get(c_parent, 0) - 1)
            mmr = lambda_param * rel - (1.0 - lambda_param) * redundancy - parent_penalty
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = idx

        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        chosen_parent = chosen.get("parent_id") or chosen.get("entity_id")
        parent_counts[chosen_parent] += 1

    return selected


def retrieve_hybrid_graph_context(
    project_id: str,
    question: str,
    departing_focus: Optional[str],
    db: Session,
    all_evidences: Optional[List[Evidence]] = None,
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    """Multi-Entity Hybrid Graph-RAG retrieval with RRF, 1-hop graph expansion, and MMR."""
    candidates, evidence_by_id, entities, relationships = _build_candidate_pool(
        project_id=project_id,
        db=db,
        all_evidences=all_evidences,
    )
    if not candidates:
        return []

    emb_map = _ensure_candidate_embeddings(project_id=project_id, candidates=candidates, db=db)

    query_terms = _meaningful_terms(question)
    if departing_focus:
        query_terms.extend(_meaningful_terms(departing_focus))

    query_vector = ai_engine.generate_embedding(question, task_type="RETRIEVAL_QUERY")
    dense_scores = _compute_dense_scores(
        project_id=project_id,
        query_vector=query_vector,
        candidates=candidates,
        emb_map=emb_map,
        db=db,
    )
    bm25_scores, hit_counts = _compute_bm25_scores(query_terms=query_terms, candidates=candidates)

    max_dense = max(dense_scores.values(), default=0.0)
    max_hits = max(hit_counts.values(), default=0)

    # Abstain relevance gate: if meaningful terms exist but ZERO lexical hits and weak dense similarity
    if query_terms and max_hits == 0 and max_dense < 0.56:
        return []

    # Build Reciprocal Rank Fusion (RRF) over dense and BM25 rankings
    dense_rank_order = sorted(
        candidates,
        key=lambda c: dense_scores.get(c["key"], 0.0),
        reverse=True,
    )
    bm25_rank_order = sorted(
        candidates,
        key=lambda c: bm25_scores.get(c["key"], 0.0),
        reverse=True,
    )

    dense_rank = {c["key"]: idx + 1 for idx, c in enumerate(dense_rank_order)}
    bm25_rank = {c["key"]: idx + 1 for idx, c in enumerate(bm25_rank_order)}

    seed_keys = [
        c["key"] for c in dense_rank_order[:5] if dense_scores.get(c["key"], 0.0) >= 0.56
    ] + [
        c["key"] for c in bm25_rank_order[:5] if bm25_scores.get(c["key"], 0.0) > 0
    ]
    graph_boosts, synthetic_graph_docs = _expand_graph_neighborhood(
        question=question,
        query_terms=query_terms,
        departing_focus=departing_focus,
        candidates=candidates,
        evidence_by_id=evidence_by_id,
        entities=entities,
        relationships=relationships,
        seed_keys=list(dict.fromkeys(seed_keys)),
    )

    focus_lower = (departing_focus or "").strip().lower()
    rrf_k = 60.0
    scored: List[Dict[str, Any]] = []
    dense_vectors: Dict[str, List[float]] = {}

    for cand in candidates:
        key = cand["key"]
        d_sim = dense_scores.get(key, 0.0)
        b_score = bm25_scores.get(key, 0.0)
        hits = hit_counts.get(key, 0)

        rrf = 1.0 / (rrf_k + dense_rank[key])
        if b_score > 0:
            rrf += 1.0 / (rrf_k + bm25_rank[key])

        if focus_lower and focus_lower in (
            f"{cand.get('source_author', '')} {cand.get('owner_hint', '')} {cand['full_context']}".lower()
        ):
            rrf += 0.012

        rrf += graph_boosts.get(key, 0.0) * 0.04

        strong_lex = hits >= 2 or (hits == 1 and (len(query_terms) <= 2 or d_sim >= 0.40))
        if d_sim >= 0.56 or strong_lex or graph_boosts.get(key, 0.0) > 0:
            lex_signal = min(0.94, 0.62 + 0.09 * hits + min(0.18, b_score * 0.04)) if hits > 0 else 0.0
            rel_score = round(
                min(0.98, max(float(d_sim), lex_signal, 0.72 if graph_boosts.get(key, 0.0) > 0 else 0.0) + 0.04 * min(1.0, graph_boosts.get(key, 0.0))),
                3,
            )
            item = {
                "key": key,
                "entity_type": cand["entity_type"],
                "entity_id": cand["entity_id"],
                "parent_id": cand.get("parent_id"),
                "evidence_id": cand["evidence_id"],
                "source_type": cand["source_type"],
                "source_title": cand["source_title"],
                "source_url": cand["source_url"],
                "source_author": cand["source_author"],
                "source_timestamp": cand["source_timestamp"],
                "verification_status": cand["verification_status"],
                "excerpt": cand["excerpt"],
                "full_context": cand["full_context"],
                "confidence": cand["confidence"],
                "retrieval_score": rel_score,
                "rrf_score": rrf,
            }
            scored.append(item)
            rec = emb_map.get((cand["entity_type"], cand["entity_id"]))
            if rec and rec.embedding:
                dense_vectors[key] = rec.embedding

    # Add synthetic 1-hop graph neighborhood docs if relevant
    for gdoc in synthetic_graph_docs:
        scored.append(gdoc)

    if not scored:
        return []

    scored.sort(key=lambda x: x["rrf_score"], reverse=True)
    selected = _mmr_select(scored[: max(top_k * 3, 18)], dense_vectors=dense_vectors, top_k=top_k)

    results: List[Dict[str, Any]] = []
    for item in selected:
        results.append(
            {
                "id": item["evidence_id"],
                "evidence_id": item["evidence_id"],
                "entity_type": item["entity_type"],
                "source_type": item["source_type"],
                "source_title": item["source_title"],
                "source_url": item["source_url"],
                "source_author": item["source_author"],
                "source_timestamp": item["source_timestamp"],
                "verification_status": item["verification_status"],
                "excerpt": item["excerpt"],
                "full_context": item["full_context"],
                "confidence": item["confidence"],
                "retrieval_score": item.get("retrieval_score", item.get("confidence", 0.78)),
            }
        )
    return results
