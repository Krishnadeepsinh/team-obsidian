import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.integration import Integration, SourceEvent, SourceRecord
from app.models.knowledge import EmbeddingRecord
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity


def chunk_structured_content(
    text: str,
    source_type: str = "",
    target_chars: int = 2200,
    overlap_chars: int = 320,
) -> List[Dict[str, Any]]:
    """Split source content into lossless semantic + sliding-window chunks preserving diffs, headings, threads, and traces."""
    cleaned = (text or "").strip()
    if not cleaned:
        return [
            {
                "chunk_index": 0,
                "total_chunks": 1,
                "content": "",
                "content_hash": hashlib.sha256(b"").hexdigest(),
            }
        ]
    if len(cleaned) <= target_chars:
        return [
            {
                "chunk_index": 0,
                "total_chunks": 1,
                "content": cleaned,
                "content_hash": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
            }
        ]

    st = (source_type or "").lower()
    if st in ("github_pr", "gitlab_mr", "github_commit", "gitlab_commit"):
        blocks = re.split(r"(?=\ndiff --git |\n@@ |\nFiles Touched:)", cleaned)
    elif st in ("confluence_page", "notion_page", "document", "github_ast", "gitlab_ast", "github_ast_module", "gitlab_ast_module"):
        blocks = re.split(r"(?=\n#{1,4}\s|\n--- )", cleaned)
    elif st == "slack_message":
        blocks = re.split(r"(?=\n\[|\nThread Reply|\n---)", cleaned)
    elif st == "sentry_issue":
        blocks = re.split(r"(?=\nTraceback|\n  File |\nException|\n\n+)", cleaned)
    else:
        blocks = re.split(r"\n\n+", cleaned)

    raw_chunks: List[str] = []
    current = ""
    step_advance = max(200, target_chars - overlap_chars)
    for block in blocks:
        if not block or not block.strip():
            continue
        if current and len(current) + len(block) + 2 <= target_chars:
            current += "\n" + block
        elif not current and len(block) <= target_chars:
            current = block
        else:
            if current.strip():
                raw_chunks.append(current.strip())
                current = ""
            pos = 0
            b_len = len(block)
            while b_len - pos > target_chars:
                # Try breaking cleanly on newline near the window boundary
                win_end = pos + target_chars
                nl_pos = block.rfind("\n", pos + step_advance // 2, win_end)
                cut = nl_pos if nl_pos > pos else win_end
                raw_chunks.append(block[pos:cut].strip())
                pos = max(pos + 200, cut - overlap_chars)
            rem = block[pos:].strip()
            if rem:
                current = rem
    if current.strip():
        raw_chunks.append(current.strip())

    if not raw_chunks:
        raw_chunks = [cleaned[:target_chars]]

    total = len(raw_chunks)
    out: List[Dict[str, Any]] = []
    for idx, ch in enumerate(raw_chunks):
        prefix = ""
        if idx > 0 and overlap_chars > 0:
            prev_tail = raw_chunks[idx - 1][-overlap_chars:].strip()
            if prev_tail and prev_tail not in ch[: overlap_chars + 40]:
                prefix = prev_tail + "\n...\n"
        combined = f"{prefix}{ch}".strip()
        out.append(
            {
                "chunk_index": idx,
                "total_chunks": total,
                "content": combined,
                "content_hash": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
            }
        )
    return out


def upsert_source_records(
    db: Session,
    integration: Integration,
    raw_records: List[Dict[str, Any]],
    actor_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
) -> Dict[str, int]:
    """Idempotently persist normalized source records, lossless hierarchical chunks, and asymmetric embeddings."""
    added = 0
    updated = 0
    skipped = 0

    for r in raw_records:
        ext_id = str(r["external_id"])[:255]
        src_type = str(r["source_type"])[:50]
        sha256 = r["sha256"]

        existing = (
            db.query(SourceRecord)
            .filter(
                SourceRecord.project_id == integration.project_id,
                SourceRecord.source_type == src_type,
                SourceRecord.external_id == ext_id,
            )
            .first()
        )

        if existing:
            if existing.sha256_hash == sha256:
                skipped += 1
                continue
            existing.title = r["title"][:500]
            existing.author = r.get("author")
            existing.url = r.get("url")
            existing.content = r["content"]
            existing.sha256_hash = sha256
            existing.raw_payload = r.get("raw_payload") or {}
            existing.metadata_json = r.get("metadata") or {}
            existing.source_timestamp = r.get("source_timestamp")
            existing.updated_at = datetime.now(timezone.utc)
            rec = existing
            updated += 1
            ev = _sync_hierarchical_evidences(db, integration, rec, is_update=True)
        else:
            rec = SourceRecord(
                integration_id=integration.id,
                project_id=integration.project_id,
                external_id=ext_id,
                source_type=src_type,
                title=r["title"][:500],
                author=r.get("author"),
                url=r.get("url"),
                content=r["content"],
                sha256_hash=sha256,
                raw_payload=r.get("raw_payload") or {},
                metadata_json=r.get("metadata") or {},
                source_timestamp=r.get("source_timestamp"),
            )
            db.add(rec)
            db.flush()
            ev = _sync_hierarchical_evidences(db, integration, rec, is_update=False)
            added += 1

        # Chunk-level & parent-level asymmetric RETRIEVAL_DOCUMENT embeddings queued/persisted
        _sync_chunk_embeddings(db, integration.project_id, rec, ev)

    db.flush()
    integration.items_synced = (
        db.query(SourceRecord).filter(SourceRecord.integration_id == integration.id).count()
    )

    event = SourceEvent(
        integration_id=integration.id,
        event_type="sync_completed",
        status="success",
        records_added=added,
        records_updated=updated,
        records_skipped=skipped,
        details={
            "provider": integration.provider,
            "records_added": added,
            "records_updated": updated,
            "records_skipped": skipped,
        },
    )
    db.add(event)

    if added > 0 or updated > 0:
        record_activity(
            db=db,
            action="integration.synced",
            entity_type="integration",
            entity_id=integration.id,
            user_id=actor_user_id,
            project_id=integration.project_id,
            actor_email=actor_email,
            details={
                "message": f"Synced {integration.name}: +{added} new, {updated} updated, {skipped} unchanged",
            },
        )

    return {"added": added, "updated": updated, "skipped": skipped}


def _sync_hierarchical_evidences(
    db: Session,
    integration: Integration,
    rec: SourceRecord,
    is_update: bool = False,
) -> List[Evidence]:
    """Create or update parent + child hierarchical Evidence chunks so long source records are never truncated."""
    chunks = chunk_structured_content(rec.content, rec.source_type)
    total = len(chunks)

    existing_evs = (
        db.query(Evidence)
        .filter(Evidence.source_record_id == rec.id)
        .order_by(Evidence.chunk_index.asc())
        .all()
    )

    parent_ev = next((e for e in existing_evs if getattr(e, "parent_evidence_id", None) is None), None)
    if parent_ev is None and existing_evs:
        parent_ev = existing_evs[0]

    first_chunk = chunks[0]
    first_text = first_chunk["content"] or rec.content
    meta_base = dict(rec.metadata_json or {})

    if parent_ev:
        parent_ev.source_title = rec.title
        parent_ev.source_url = rec.url
        parent_ev.source_author = rec.author
        parent_ev.source_timestamp = rec.source_timestamp
        parent_ev.excerpt = first_text[:1200]
        parent_ev.full_text = rec.content
        parent_ev.chunk_index = 0
        parent_ev.total_chunks = total
        parent_ev.content_hash = rec.sha256_hash
        if is_update:
            parent_ev.verification_status = "Needs Human Verification"
            parent_ev.ai_interpretation = (
                f"Updated source record ingested from {integration.name} ({rec.source_type}, {total} chunk(s))."
            )
    else:
        parent_ev = Evidence(
            project_id=integration.project_id,
            source_record_id=rec.id,
            parent_evidence_id=None,
            chunk_index=0,
            total_chunks=total,
            source_type=rec.source_type,
            source_id=rec.id,
            source_title=rec.title,
            source_url=rec.url,
            source_author=rec.author,
            source_timestamp=rec.source_timestamp,
            claim_type="source_record",
            excerpt=first_text[:1200],
            full_text=rec.content,
            content_hash=rec.sha256_hash,
            confidence=0.75,
            verification_status="Supported by Evidence",
            ai_interpretation=f"Ingested source record from {integration.name} ({rec.source_type}, {total} chunk(s)).",
            metadata_json=meta_base,
        )
        db.add(parent_ev)
        db.flush()

    ev_list: List[Evidence] = [parent_ev]
    child_by_idx = {
        e.chunk_index: e
        for e in existing_evs
        if e.id != parent_ev.id
    }

    for chunk in chunks[1:]:
        idx = chunk["chunk_index"]
        ch_text = chunk["content"]
        child_title = f"{rec.title[:460]} [Part {idx + 1}/{total}]"
        child_meta = {**meta_base, "chunk_index": idx, "total_chunks": total}
        ch_ev = child_by_idx.pop(idx, None)
        if ch_ev:
            ch_ev.parent_evidence_id = parent_ev.id
            ch_ev.source_title = child_title
            ch_ev.source_url = rec.url
            ch_ev.source_author = rec.author
            ch_ev.source_timestamp = rec.source_timestamp
            ch_ev.excerpt = ch_text[:1200]
            ch_ev.full_text = ch_text
            ch_ev.chunk_index = idx
            ch_ev.total_chunks = total
            ch_ev.content_hash = chunk["content_hash"]
            ch_ev.metadata_json = child_meta
            if is_update:
                ch_ev.verification_status = "Needs Human Verification"
        else:
            ch_ev = Evidence(
                project_id=integration.project_id,
                source_record_id=rec.id,
                parent_evidence_id=parent_ev.id,
                chunk_index=idx,
                total_chunks=total,
                source_type=rec.source_type,
                source_id=rec.id,
                source_title=child_title,
                source_url=rec.url,
                source_author=rec.author,
                source_timestamp=rec.source_timestamp,
                claim_type="source_chunk",
                excerpt=ch_text[:1200],
                full_text=ch_text,
                content_hash=chunk["content_hash"],
                confidence=0.75,
                verification_status="Supported by Evidence",
                ai_interpretation=f"Chunk {idx + 1}/{total} of '{rec.title[:160]}' ({rec.source_type}).",
                metadata_json=child_meta,
            )
            db.add(ch_ev)
            db.flush()
        ev_list.append(ch_ev)

    # Remove obsolete trailing chunk rows & their embeddings if record shrank
    for stale_ev in child_by_idx.values():
        db.query(EmbeddingRecord).filter(
            EmbeddingRecord.project_id == integration.project_id,
            EmbeddingRecord.entity_id == stale_ev.id,
        ).delete(synchronize_session=False)
        db.delete(stale_ev)

    return ev_list


def _sync_chunk_embeddings(
    db: Session,
    project_id: str,
    rec: SourceRecord,
    evidences: List[Evidence],
) -> None:
    if not evidences:
        return
    parent_id = evidences[0].id
    texts = [
        f"{ev.source_title}\n{(ev.full_text if idx > 0 else (ev.full_text or ev.excerpt))[:2800]}"
        for idx, ev in enumerate(evidences)
    ]
    vecs = ai_engine.generate_embeddings_batch(texts, task_type="RETRIEVAL_DOCUMENT")
    if len(vecs) != len(evidences):
        return

    for idx, (ev, txt, vec) in enumerate(zip(evidences, texts, vecs)):
        ent_type = "evidence" if idx == 0 else "evidence_chunk"
        _upsert_embedding(
            db=db,
            project_id=project_id,
            entity_type=ent_type,
            entity_id=ev.id,
            text_content=txt,
            vec=vec,
            parent_id=parent_id,
            chunk_index=idx,
            task_type="RETRIEVAL_DOCUMENT",
        )


def _create_evidence_for_record(db: Session, integration: Integration, rec: SourceRecord) -> Evidence:
    return _sync_hierarchical_evidences(db, integration, rec, is_update=False)[0]


def _upsert_embedding(
    db: Session,
    project_id: str,
    entity_type: str,
    entity_id: str,
    text_content: str,
    vec: Optional[List[float]] = None,
    parent_id: Optional[str] = None,
    chunk_index: int = 0,
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> None:
    if vec is None:
        vec = ai_engine.generate_embedding(text_content, task_type=task_type)
    existing = (
        db.query(EmbeddingRecord)
        .filter(
            EmbeddingRecord.project_id == project_id,
            EmbeddingRecord.entity_type == entity_type,
            EmbeddingRecord.entity_id == entity_id,
        )
        .first()
    )
    if existing:
        existing.text_content = text_content
        existing.embedding = vec
        existing.embedding_vector = vec
        existing.parent_id = parent_id
        existing.chunk_index = chunk_index
        existing.task_type = task_type
    else:
        db.add(
            EmbeddingRecord(
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                parent_id=parent_id,
                chunk_index=chunk_index,
                task_type=task_type,
                text_content=text_content,
                embedding=vec,
                embedding_vector=vec,
            )
        )

