import gc
import logging
import os
import re
import uuid
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.permissions import get_effective_project, get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.integration import Document, DocumentChunk
from app.models.knowledge import EmbeddingRecord
from app.models.workspace import User
from app.schemas.integration import DocumentResponse
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity
from app.services.document_parser import document_parser
from app.services.knowledge_extractor import extract_and_persist_project_knowledge
from app.services.storage_service import storage_service

logger = logging.getLogger("team_obsidian.documents")
router = APIRouter(prefix="/documents", tags=["Document Library"])

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "pdf", "docx", "doc", "xlsx", "xls", "txt", "md", "csv",
    "html", "htm", "json", "yaml", "yml", "log", "rst", "sql", "xml",
    "png", "jpg", "jpeg", "webp",
}
DANGEROUS_EXTENSIONS = {"exe", "bat", "sh", "cmd", "ps1", "dll", "vbs", "jar", "bin", "msi", "js", "php"}


def _clean_text(value: Optional[str], max_len: Optional[int] = None) -> str:
    cleaned = (value or "").replace("\x00", "").strip()
    if max_len is not None:
        return cleaned[:max_len]
    return cleaned


def _safe_disk_name(sha_prefix: str, filename: str) -> str:
    stem, ext = os.path.splitext(filename)
    clean_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "document"
    clean_ext = re.sub(r"[^A-Za-z0-9]+", "", ext.lstrip("."))[:16]
    suffix = f".{clean_ext}" if clean_ext else ""
    max_path_total = 220
    budget = max(16, min(80, max_path_total - len(UPLOAD_DIR) - len(sha_prefix) - len(suffix) - 4))
    return f"{sha_prefix}_{clean_stem[:budget]}{suffix}"


def _fit_filename(raw_name: str, max_len: int = 255) -> str:
    cleaned = _clean_text(raw_name) or "uploaded_doc"
    if len(cleaned) <= max_len:
        return cleaned
    stem, ext = os.path.splitext(cleaned)
    if ext and len(ext) < max_len - 1:
        return f"{stem[:max_len - len(ext)]}{ext}"
    return cleaned[:max_len]


def _ascii_header_filename(raw_name: str, fallback: str = "document.bin") -> str:
    cleaned = (raw_name or fallback).replace('"', "").replace("\r", "").replace("\n", "")
    ascii_only = re.sub(r"[^\x20-\x7E]", "_", cleaned).strip()
    return ascii_only or fallback


@router.get("", response_model=List[DocumentResponse])
def list_documents(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Document)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = query.filter(Document.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return []
        query = query.filter(Document.project_id.in_(p_ids))
    return query.order_by(Document.created_at.desc()).all()


def _run_background_extraction(project_id: str, actor_user_id: str, doc_id: str) -> None:
    """Extract structured knowledge graph items in a standalone DB session after upload responds."""
    bg_db = SessionLocal()
    try:
        extract_and_persist_project_knowledge(bg_db, project_id, actor_user_id=actor_user_id)
    except Exception as exc:
        bg_db.rollback()
        logger.warning("Post-upload knowledge extraction skipped for doc %s: %s", doc_id, exc)
    finally:
        bg_db.close()
        gc.collect()


@router.post("/upload", response_model=DocumentResponse)
def upload_document(
    background_tasks: BackgroundTasks,
    project_id: str = Form(""),
    title: str = Form(""),
    extract_knowledge: bool = Form(True),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload PDF, DOCX, XLSX, CSV, TXT, MD, HTML, JSON, YAML, SQL, or LOG; parse, chunk, hash, index embeddings, and create traceable evidence."""
    raw_filename = os.path.basename(file.filename or "uploaded_doc")
    filename = _fit_filename(raw_filename, 255)
    ext = (filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt")[:20]

    if ext in DANGEROUS_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported or dangerous file type '.{ext}'. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = file.file.read(settings.MAX_UPLOAD_BYTES + 1)
    file_size = len(file_bytes)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if file_size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File size exceeds maximum permitted limit of {settings.MAX_UPLOAD_MB} MB.",
        )

    eff_proj = get_effective_project(project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=404, detail="No accessible project found. Create a project first.")
    project_id = eff_proj.id

    sha256 = document_parser.calculate_sha256(file_bytes)

    # Deduplicate identical uploaded files within the same project
    existing_doc = (
        db.query(Document)
        .filter(Document.project_id == project_id, Document.sha256_hash == sha256)
        .first()
    )
    if existing_doc:
        return existing_doc

    try:
        parsed = document_parser.parse_file(filename, file_bytes)
        extracted_text = _clean_text(parsed.get("text") or "")
        chunks = document_parser.chunk_sections(parsed.get("sections") or [], fallback_text=extracted_text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse document '{filename}': {exc}")

    clean_title = _clean_text(title, 255) or _clean_text(os.path.splitext(filename)[0], 255) or filename
    author_label = _clean_text(current_user.name or current_user.email, 255) or "Workspace Member"

    stored = storage_service.save_document_bytes(
        project_id=project_id,
        sha256_hash=sha256,
        filename=filename,
        file_bytes=file_bytes,
        content_type=file.content_type,
    )
    meta = dict(parsed.get("metadata") or {})
    meta["storage_backend"] = stored.get("backend", "local")

    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        project_id=project_id,
        user_id=current_user.id,
        title=clean_title,
        filename=filename,
        file_type=ext,
        mime_type=_clean_text(file.content_type, 120) or None,
        file_size_bytes=file_size,
        storage_path=stored.get("storage_path"),
        storage_bucket=stored.get("storage_bucket"),
        storage_key=stored.get("storage_key"),
        sha256_hash=sha256,
        status="processed",
        extracted_text=extracted_text,
        chunk_count=len(chunks),
        page_count=parsed.get("page_count"),
        sheet_names=[_clean_text(str(s), 255) for s in (parsed.get("sheet_names") or []) if _clean_text(str(s))],
        metadata_json=meta,
        uploaded_by=author_label,
    )
    db.add(doc)
    db.flush()

    # Pre-compute semantic embeddings once per chunk in a single batch
    chunk_texts = [_clean_text(c.get("content")) for c in chunks]
    non_empty_texts = [t for t in chunk_texts if t]
    vectors: List[List[float]] = []
    if non_empty_texts:
        try:
            vectors = ai_engine.generate_embeddings_batch(non_empty_texts)
        except Exception as exc:
            logger.warning("Embedding generation failed during upload of doc %s: %s", doc_id, exc)
            vectors = []

    vec_idx = 0
    chunk_recs: List[DocumentChunk] = []
    evidences: List[Evidence] = []
    embedding_recs: List[EmbeddingRecord] = []

    for c, chunk_content in zip(chunks, chunk_texts):
        if not chunk_content:
            continue
        chunk_id = str(uuid.uuid4())
        ev_id = str(uuid.uuid4())
        sheet_name = _clean_text(c.get("sheet_name"), 255) or None
        heading = _clean_text(c.get("heading"), 500) or None
        paragraph_ref = _clean_text(c.get("paragraph_ref"), 255) or None

        chunk_recs.append(
            DocumentChunk(
                id=chunk_id,
                document_id=doc_id,
                project_id=project_id,
                chunk_index=c["chunk_index"],
                page_number=c.get("page_number"),
                sheet_name=sheet_name,
                heading=heading,
                paragraph_ref=paragraph_ref,
                start_char=c["start_char"],
                end_char=c["end_char"],
                content=chunk_content,
                sha256_hash=c["sha256"],
            )
        )

        loc_parts = [filename]
        if c.get("page_number"):
            loc_parts.append(f"Page {c['page_number']}")
        if sheet_name:
            loc_parts.append(f"Sheet {sheet_name}")
        if heading:
            loc_parts.append(heading[:120])
        loc_label = " • ".join(loc_parts)

        source_title = _clean_text(f"Doc: {clean_title} ({loc_label})", 500) or clean_title
        evidences.append(
            Evidence(
                id=ev_id,
                project_id=project_id,
                document_id=doc_id,
                chunk_id=chunk_id,
                source_type="document",
                source_id=doc_id,
                source_title=source_title,
                source_url=f"/documents?doc={doc_id}"[:1000],
                source_author=author_label,
                claim_type="document_chunk",
                excerpt=chunk_content[:800],
                ai_interpretation=f"Extracted chunk #{c['chunk_index'] + 1} from '{filename}' ({loc_label[:200]}).",
                confidence=0.80,
                verification_status="Supported by Evidence",
                content_hash=c["sha256"],
                metadata_json={
                    "filename": filename,
                    "page_number": c.get("page_number"),
                    "sheet_name": sheet_name,
                    "heading": heading,
                    "paragraph_ref": paragraph_ref,
                    "chunk_index": c["chunk_index"],
                },
            )
        )

        if vec_idx < len(vectors):
            vec = vectors[vec_idx]
            vec_idx += 1
            embedding_recs.append(
                EmbeddingRecord(
                    project_id=project_id,
                    entity_type="evidence",
                    entity_id=ev_id,
                    text_content=f"{clean_title} ({loc_label})\n{chunk_content}",
                    embedding=vec,
                    embedding_vector=vec,
                )
            )

    doc.chunk_count = len(chunk_recs)
    if chunk_recs:
        db.add_all(chunk_recs)
        db.flush()
    if evidences:
        db.add_all(evidences)
        db.flush()
    if embedding_recs:
        db.add_all(embedding_recs)

    record_activity(
        db=db,
        action="document.uploaded",
        entity_type="document",
        entity_id=doc_id,
        user_id=current_user.id,
        project_id=project_id,
        actor_email=current_user.email,
        details={"message": f"Uploaded '{clean_title}' ({filename}, {len(chunk_recs)} chunks)"},
    )
    db.commit()
    db.refresh(doc)

    if extract_knowledge and chunk_recs:
        background_tasks.add_task(_run_background_extraction, project_id, current_user.id, doc_id)

    gc.collect()
    return doc


@router.get("/{document_id}/chunks")
def get_document_chunks(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    verify_project_access(doc.project_id, current_user, db)
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    return [
        {
            "id": c.id,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
            "sheet_name": c.sheet_name,
            "heading": c.heading,
            "paragraph_ref": c.paragraph_ref,
            "content": c.content,
            "sha256_hash": c.sha256_hash,
        }
        for c in chunks
    ]


@router.get("/{document_id}/download")
def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    verify_project_access(doc.project_id, current_user, db)
    ascii_name = _ascii_header_filename(doc.filename, f"document.{doc.file_type or 'bin'}")
    raw_bytes = storage_service.read_document_bytes(
        storage_bucket=getattr(doc, "storage_bucket", None),
        storage_key=getattr(doc, "storage_key", None),
        storage_path=doc.storage_path,
    )
    if raw_bytes is not None:
        raw_mime = (doc.mime_type or "application/octet-stream").lower()
        safe_media_type = (
            "application/octet-stream"
            if any(tok in raw_mime for tok in ("html", "xml", "svg", "javascript", "ecmascript"))
            else (doc.mime_type or "application/octet-stream")
        )
        return Response(
            content=raw_bytes,
            media_type=safe_media_type,
            headers={
                "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(doc.filename or ascii_name)}",
                "X-Content-Type-Options": "nosniff",
                "X-Obsidian-Source": "supabase-storage" if getattr(doc, "storage_key", None) else "local-storage",
            },
        )

    # Cloud/ephemeral container fallback: reconstruct text from persisted PostgreSQL chunks
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=404, detail="Stored file not found on disk and no indexed chunks exist.")

    reconstructed = "\n\n".join(
        [f"# {doc.title} ({doc.filename})\n# SHA-256: {doc.sha256_hash}\n"]
        + [f"## Chunk {c.chunk_index + 1}\n{c.content}" for c in chunks]
    )
    raw_base = os.path.splitext(doc.filename or doc.title or "document")[0]
    download_name = f"{raw_base}_chunks.txt"
    ascii_download = _ascii_header_filename(download_name, "document_chunks.txt")
    return Response(
        content=reconstructed.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_download}\"; filename*=UTF-8''{quote(download_name)}",
            "X-Content-Type-Options": "nosniff",
            "X-Obsidian-Source": "database-chunks",
        },
    )


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    verify_project_access(doc.project_id, current_user, db, require_write=True)

    # Clean up linked evidence & embeddings
    linked_evs = db.query(Evidence).filter(Evidence.document_id == doc.id).all()
    ev_ids = [e.id for e in linked_evs]
    if ev_ids:
        db.query(EmbeddingRecord).filter(
            EmbeddingRecord.entity_type == "evidence", EmbeddingRecord.entity_id.in_(ev_ids)
        ).delete(synchronize_session=False)
        db.query(Evidence).filter(Evidence.id.in_(ev_ids)).delete(synchronize_session=False)

    storage_service.delete_document_bytes(
        storage_bucket=getattr(doc, "storage_bucket", None),
        storage_key=getattr(doc, "storage_key", None),
        storage_path=doc.storage_path,
    )

    title = doc.title
    pid = doc.project_id
    db.delete(doc)
    record_activity(
        db=db,
        action="document.deleted",
        entity_type="document",
        entity_id=document_id,
        user_id=current_user.id,
        project_id=pid,
        actor_email=current_user.email,
        details={"message": f"Deleted document '{title}'"},
    )
    db.commit()
    return {"status": "success", "message": f"Document '{title}' deleted."}
