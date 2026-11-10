from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.integration import Integration, SourceEvent, SourceRecord
from app.models.knowledge import EmbeddingRecord
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity


def upsert_source_records(
    db: Session,
    integration: Integration,
    raw_records: List[Dict[str, Any]],
    actor_user_id: Optional[str] = None,
    actor_email: Optional[str] = None,
) -> Dict[str, int]:
    """Idempotently persist normalized source records, update evidence, and index semantic embeddings."""
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

            # Update linked evidence while resetting review status since content changed
            ev = db.query(Evidence).filter(Evidence.source_record_id == rec.id).first()
            if ev:
                ev.source_title = rec.title
                ev.source_url = rec.url
                ev.source_author = rec.author
                ev.source_timestamp = rec.source_timestamp
                ev.excerpt = rec.content[:800]
                ev.content_hash = sha256
                ev.verification_status = "Needs Human Verification"
                ev.ai_interpretation = f"Updated source record ingested from {integration.name} ({src_type})."
            else:
                ev = _create_evidence_for_record(db, integration, rec)
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
            ev = _create_evidence_for_record(db, integration, rec)
            added += 1

        # Refresh semantic embedding record for hybrid RAG
        _upsert_embedding(db, integration.project_id, "evidence", ev.id, f"{rec.title}\n{rec.content[:1500]}")

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


def _create_evidence_for_record(db: Session, integration: Integration, rec: SourceRecord) -> Evidence:
    ev = Evidence(
        project_id=integration.project_id,
        source_record_id=rec.id,
        source_type=rec.source_type,
        source_id=rec.id,
        source_title=rec.title,
        source_url=rec.url,
        source_author=rec.author,
        source_timestamp=rec.source_timestamp,
        claim_type="source_record",
        excerpt=rec.content[:800],
        content_hash=rec.sha256_hash,
        confidence=0.75,
        verification_status="Supported by Evidence",
        ai_interpretation=f"Ingested source record from {integration.name} ({rec.source_type}). Pending human verification for derived claims.",
        metadata_json=rec.metadata_json or {},
    )
    db.add(ev)
    db.flush()
    return ev


def _upsert_embedding(db: Session, project_id: str, entity_type: str, entity_id: str, text_content: str) -> None:
    vec = ai_engine.generate_embedding(text_content)
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
    else:
        db.add(
            EmbeddingRecord(
                project_id=project_id,
                entity_type=entity_type,
                entity_id=entity_id,
                text_content=text_content,
                embedding=vec,
                embedding_vector=vec,
            )
        )

