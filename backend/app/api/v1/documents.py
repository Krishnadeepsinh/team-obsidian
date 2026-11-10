import os
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
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

router = APIRouter(prefix="/documents", tags=["Document Library"])

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "xlsx", "xls", "txt", "md", "csv", "html", "htm", "json"}
DANGEROUS_EXTENSIONS = {"exe", "bat", "sh", "cmd", "ps1", "dll", "vbs", "jar", "bin", "msi", "js", "php"}


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


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    project_id: str = Form(...),
    title: str = Form(...),
    extract_knowledge: bool = Form(True),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload PDF, DOCX, XLSX, CSV, TXT, MD, HTML, or JSON; parse metadata, chunk, hash, index embeddings, and create traceable evidence."""
    filename = os.path.basename(file.filename or "uploaded_doc")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"

    if ext in DANGEROUS_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported or dangerous file type '.{ext}'. Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await file.read()
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
        raise HTTPException(status_code=404, detail="No accessible project found.")
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
        extracted_text = parsed.get("text") or ""
        chunks = document_parser.chunk_sections(parsed.get("sections") or [], fallback_text=extracted_text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse document '{filename}': {exc}")

    safe_filename = f"{sha256[:16]}_{filename}"
    save_path = os.path.join(UPLOAD_DIR, safe_filename)
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    doc = Document(
        project_id=project_id,
        user_id=current_user.id,
        title=title.strip(),
        filename=filename,
        file_type=ext,
        mime_type=file.content_type,
        file_size_bytes=file_size,
        storage_path=save_path,
        sha256_hash=sha256,
        status="processed",
        extracted_text=extracted_text,
        chunk_count=len(chunks),
        page_count=parsed.get("page_count"),
        sheet_names=parsed.get("sheet_names") or [],
        metadata_json=parsed.get("metadata") or {},
        uploaded_by=current_user.name,
    )
    db.add(doc)
    db.flush()

    # Persist overlapping chunks, create traceable Evidence items, and index semantic embeddings
    chunk_texts = [c["content"] for c in chunks if c["content"].strip()]
    vectors = ai_engine.generate_embeddings_batch(chunk_texts) if chunk_texts else []
    vec_idx = 0

    for c in chunks:
        chunk_rec = DocumentChunk(
            document_id=doc.id,
            project_id=project_id,
            chunk_index=c["chunk_index"],
            page_number=c.get("page_number"),
            sheet_name=c.get("sheet_name"),
            heading=c.get("heading"),
            paragraph_ref=c.get("paragraph_ref"),
            start_char=c["start_char"],
            end_char=c["end_char"],
            content=c["content"],
            sha256_hash=c["sha256"],
        )
        db.add(chunk_rec)
        db.flush()

        loc_parts = [filename]
        if c.get("page_number"):
            loc_parts.append(f"Page {c['page_number']}")
        if c.get("sheet_name"):
            loc_parts.append(f"Sheet {c['sheet_name']}")
        if c.get("heading"):
            loc_parts.append(c["heading"])
        loc_label = " • ".join(loc_parts)

        ev = Evidence(
            project_id=project_id,
            document_id=doc.id,
            chunk_id=chunk_rec.id,
            source_type="document",
            source_id=doc.id,
            source_title=f"Doc: {doc.title} ({loc_label})",
            source_url=f"/documents?doc={doc.id}",
            source_author=current_user.name,
            claim_type="document_chunk",
            excerpt=c["content"][:800],
            ai_interpretation=f"Extracted chunk #{c['chunk_index'] + 1} from '{filename}' ({loc_label}).",
            confidence=0.80,
            verification_status="Supported by Evidence",
            content_hash=c["sha256"],
            metadata_json={
                "filename": filename,
                "page_number": c.get("page_number"),
                "sheet_name": c.get("sheet_name"),
                "heading": c.get("heading"),
                "paragraph_ref": c.get("paragraph_ref"),
                "chunk_index": c["chunk_index"],
            },
        )
        db.add(ev)
        db.flush()

        if c["content"].strip() and vec_idx < len(vectors):
            vec = vectors[vec_idx]
            vec_idx += 1
            db.add(
                EmbeddingRecord(
                    project_id=project_id,
                    entity_type="evidence",
                    entity_id=ev.id,
                    text_content=f"{doc.title} ({loc_label})\n{c['content']}",
                    embedding=vec,
                    embedding_vector=vec,
                )
            )

    record_activity(
        db=db,
        action="document.uploaded",
        entity_type="document",
        entity_id=doc.id,
        user_id=current_user.id,
        project_id=project_id,
        actor_email=current_user.email,
        details={"message": f"Uploaded '{doc.title}' ({filename}, {len(chunks)} chunks)"},
    )
    db.commit()
    db.refresh(doc)

    if extract_knowledge and chunks:
        extract_and_persist_project_knowledge(db, project_id, actor_user_id=current_user.id)

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
    if doc.storage_path and os.path.exists(doc.storage_path):
        return FileResponse(doc.storage_path, filename=doc.filename)

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
    safe_base = os.path.splitext(doc.filename or doc.title or "document")[0]
    return Response(
        content=reconstructed.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_base}_chunks.txt"',
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

    if doc.storage_path and os.path.exists(doc.storage_path):
        try:
            os.remove(doc.storage_path)
        except Exception:
            pass

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
