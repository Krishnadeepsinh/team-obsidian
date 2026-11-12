import io
import os
import sys
import uuid
from unittest.mock import patch

import docx
import openpyxl
import pymupdf
from fastapi.testclient import TestClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.database import SessionLocal, init_db
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.integration import Document
from app.models.knowledge import KnowledgeEntity
from app.models.workspace import Organization, Project, ProjectMember, User, Workspace
from app.services.ai_engine import (
    ExtractedDecision,
    ExtractedDependency,
    ExtractedEntity,
    ExtractedGap,
    ExtractedRisk,
    StructuredKnowledgeBundle,
)
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

client = TestClient(app)


def _create_isolated_user_and_project():
    init_db()
    db = SessionLocal()
    tag = uuid.uuid4().hex[:10]
    org = Organization(name=f"DocTest Org {tag}", slug=f"doctest-org-{tag}", tier="standard")
    db.add(org)
    db.flush()

    ws = Workspace(org_id=org.id, name="DocTest Workspace", slug=f"doctest-ws-{tag}")
    db.add(ws)
    db.flush()

    user = User(
        org_id=org.id,
        personal_workspace_id=ws.id,
        email=f"doctest_{tag}@example.com",
        name="Doc Test Engineer",
        role="tech_lead",
        password_hash=get_password_hash("StrongPass2026!"),
    )
    db.add(user)
    db.flush()

    proj = Project(
        workspace_id=ws.id,
        name=f"Doc Upload Project {tag}",
        slug=f"doc-upload-{tag}",
        description="Isolated project for document parser & upload tests",
        status="active",
    )
    db.add(proj)
    db.flush()

    db.add(ProjectMember(project_id=proj.id, user_id=user.id, project_role="tech_lead", status="active"))
    db.commit()
    token = create_access_token({"sub": user.id, "email": user.email, "role": user.role, "project_id": proj.id})
    headers = {"Authorization": f"Bearer {token}"}
    pid = proj.id
    uid = user.id
    oid = org.id
    db.close()
    return headers, pid, uid, oid


def _cleanup_org(org_id: str):
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.id == org_id).first()
        if org:
            db.delete(org)
            db.commit()
    finally:
        db.close()


def test_multiformat_pdf_docx_xlsx_and_yaml_uploads():
    headers, project_id, _, org_id = _create_isolated_user_and_project()
    try:
        # 1. Valid PDF
        pdf_doc = pymupdf.open()
        page = pdf_doc.new_page()
        page.insert_text((72, 72), "Checkout Architecture\nFastAPI + PostgreSQL + Redis Cluster architecture specification.")
        pdf_bytes = pdf_doc.tobytes()
        pdf_doc.close()

        r_pdf = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": "Architecture Spec PDF", "extract_knowledge": "false"},
            files={"file": ("architecture.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_pdf.status_code == 200, r_pdf.text
        pdf_data = r_pdf.json()
        assert pdf_data["chunk_count"] >= 1
        assert pdf_data["page_count"] == 1

        # 2. Image-only / zero-text scanned PDF -> still produces metadata notice chunk & DB download fallback
        scanned = pymupdf.open()
        scanned.new_page()
        scanned_bytes = scanned.tobytes()
        scanned.close()

        r_scan = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": "", "extract_knowledge": "false"},
            files={"file": ("scanned_diagram.pdf", scanned_bytes, "application/pdf")},
        )
        assert r_scan.status_code == 200, r_scan.text
        scan_data = r_scan.json()
        assert scan_data["chunk_count"] >= 1
        assert scan_data["title"] == "scanned_diagram"

        # Simulate ephemeral cloud disk loss: durable Supabase Storage returns original bytes if configured,
        # otherwise reconstructs searchable text from persisted PostgreSQL chunks.
        db_check = SessionLocal()
        has_durable_key = False
        try:
            db_doc = db_check.query(Document).filter(Document.id == scan_data["id"]).first()
            has_durable_key = bool(db_doc and db_doc.storage_key)
            if db_doc and db_doc.storage_path and os.path.exists(db_doc.storage_path):
                os.remove(db_doc.storage_path)
        finally:
            db_check.close()
        r_dl = client.get(f"/api/v1/documents/{scan_data['id']}/download", headers=headers)
        assert r_dl.status_code == 200
        if has_durable_key:
            assert r_dl.headers.get("x-obsidian-source") == "supabase-storage"
            assert r_dl.content.startswith(b"%PDF-")
        else:
            assert ("no selectable embedded text layer" in r_dl.text) or ("Scanned PDF" in r_dl.text)

        # 3. Valid DOCX with heading + table
        d = docx.Document()
        d.add_heading("Runbook Overview", level=1)
        d.add_paragraph("Restart worker queues via celeryctl before rotating API keys.")
        tbl = d.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "Service"
        tbl.cell(0, 1).text = "Owner"
        tbl.cell(1, 0).text = "Billing"
        tbl.cell(1, 1).text = "Platform Team"
        docx_buf = io.BytesIO()
        d.save(docx_buf)

        r_docx = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": "", "title": "Operations Runbook", "extract_knowledge": "false"},
            files={
                "file": (
                    "ops_runbook.docx",
                    docx_buf.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert r_docx.status_code == 200, r_docx.text
        assert r_docx.json()["chunk_count"] >= 1

        # 4. Valid XLSX with populated cells
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Dependencies"
        ws.append(["Component", "Target", "Criticality"])
        ws.append(["Checkout API", "PostgreSQL Pooler", "critical"])
        xlsx_buf = io.BytesIO()
        wb.save(xlsx_buf)
        wb.close()

        r_xlsx = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": "default", "title": "Dependency Matrix", "extract_knowledge": "false"},
            files={
                "file": (
                    "matrix.xlsx",
                    xlsx_buf.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert r_xlsx.status_code == 200, r_xlsx.text
        assert "Dependencies" in (r_xlsx.json().get("sheet_names") or [])

        # 5. Developer YAML artifact
        yaml_bytes = b"service: checkout\nowner: platform\ncriticality: high\n"
        r_yaml = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": "Service Config", "extract_knowledge": "false"},
            files={"file": ("service.yaml", yaml_bytes, "application/x-yaml")},
        )
        assert r_yaml.status_code == 200, r_yaml.text
        assert r_yaml.json()["chunk_count"] >= 1
    finally:
        _cleanup_org(org_id)


def test_legacy_binary_and_dangerous_and_unicode_long_inputs():
    headers, project_id, _, org_id = _create_isolated_user_and_project()
    try:
        # Legacy OLE2 .doc -> clear 400 error instead of 500 BadZipFile
        ole2_bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
        r_old_doc = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": "Legacy Word", "extract_knowledge": "false"},
            files={"file": ("legacy.doc", ole2_bytes, "application/msword")},
        )
        assert r_old_doc.status_code == 400
        assert "Legacy binary .doc" in r_old_doc.json()["detail"]

        # Corrupt PDF -> clean 400 error
        r_bad_pdf = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": "Bad PDF", "extract_knowledge": "false"},
            files={"file": ("broken.pdf", b"not-a-real-pdf", "application/pdf")},
        )
        assert r_bad_pdf.status_code == 400

        # Overlong filename (>255), overlong title (>255), Unicode filename, and NUL bytes in body
        long_title = "Very Long Architecture Specification " * 12
        long_unicode_name = "résumé_" + ("architecture_spec_" * 20) + ".md"
        body_with_nul = "# Heading\x00\nSystem details with embedded\x00 NUL bytes.".encode("utf-8")

        r_long = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": long_title, "extract_knowledge": "false"},
            files={"file": (long_unicode_name, body_with_nul, "text/markdown")},
        )
        assert r_long.status_code == 200, r_long.text
        doc_rec = r_long.json()
        assert len(doc_rec["title"]) <= 255
        assert len(doc_rec["filename"]) <= 255
        assert doc_rec["filename"].endswith(".md")

        db_check = SessionLocal()
        try:
            db_doc = db_check.query(Document).filter(Document.id == doc_rec["id"]).first()
            if db_doc and db_doc.storage_path and os.path.exists(db_doc.storage_path):
                os.remove(db_doc.storage_path)
        finally:
            db_check.close()
        r_chunks = client.get(f"/api/v1/documents/{doc_rec['id']}/chunks", headers=headers)
        assert r_chunks.status_code == 200
        assert "\x00" not in r_chunks.text
        r_dl = client.get(f"/api/v1/documents/{doc_rec['id']}/download", headers=headers)
        assert r_dl.status_code == 200
    finally:
        _cleanup_org(org_id)


def test_upload_succeeds_even_if_knowledge_extraction_fails():
    headers, project_id, _, org_id = _create_isolated_user_and_project()
    try:
        with patch(
            "app.api.v1.documents.extract_and_persist_project_knowledge",
            side_effect=RuntimeError("Simulated Gemini 503 UNAVAILABLE"),
        ):
            r = client.post(
                "/api/v1/documents/upload",
                headers=headers,
                data={"project_id": project_id, "title": "Isolated Extraction Test", "extract_knowledge": "true"},
                files={"file": ("notes.md", b"# Incident Notes\nPrimary DB failover completed.", "text/markdown")},
            )
            assert r.status_code == 200, r.text
            assert r.json()["chunk_count"] >= 1
    finally:
        _cleanup_org(org_id)


def test_knowledge_extractor_truncates_postgresql_bounds():
    headers, project_id, uid, org_id = _create_isolated_user_and_project()
    try:
        r = client.post(
            "/api/v1/documents/upload",
            headers=headers,
            data={"project_id": project_id, "title": "Grounding Doc", "extract_knowledge": "false"},
            files={"file": ("grounding.md", b"# Auth Service\nPostgreSQL primary.", "text/markdown")},
        )
        assert r.status_code == 200

        oversized_bundle = StructuredKnowledgeBundle(
            entities=[
                ExtractedEntity(
                    entity_type="very_long_entity_type_name_" * 5,
                    name="Component-" + ("X" * 300),
                    description="Desc\x00clean",
                    owner="Owner " * 60,
                    evidence_index=1,
                )
            ],
            decisions=[
                ExtractedDecision(
                    title="ADR-" + ("T" * 600),
                    summary="",
                    reasoning="",
                    decision_maker="Maker " * 60,
                    date="2026-11-11-" + ("0" * 80),
                    component="Comp " * 80,
                    decision_type="very_long_decision_type_" * 5,
                    evidence_index=1,
                )
            ],
            risks=[
                ExtractedRisk(
                    title="Risk-" + ("R" * 600),
                    description="",
                    category="very_long_category_" * 5,
                    severity="INVALID_LONG_SEVERITY_" * 3,
                    likelihood="INVALID",
                    impact="",
                    owner="Owner " * 60,
                    mitigation_strategy="Fix",
                    related_components=["C" * 300],
                    evidence_index=1,
                )
            ],
            dependencies=[
                ExtractedDependency(
                    source_component="Src-" + ("S" * 300),
                    target_component="Dst-" + ("D" * 300),
                    dependency_type="long_dep_type_" * 6,
                    description="Dep desc",
                    owner="Owner " * 60,
                    criticality="critical_too_long_string_value",
                    evidence_index=1,
                )
            ],
            knowledge_gaps=[
                ExtractedGap(
                    title="Gap-" + ("G" * 600),
                    description="",
                    gap_type="missing_documentation_" * 5,
                    severity="high_and_very_long_label_exceeding_20",
                    business_impact="",
                    technical_impact="",
                    recommended_action="",
                )
            ],
        )

        db = SessionLocal()
        try:
            with patch(
                "app.services.knowledge_extractor.ai_engine.extract_knowledge_from_records",
                return_value=oversized_bundle,
            ):
                counts = extract_and_persist_project_knowledge(db, project_id, actor_user_id=uid)
                assert counts["entities"] >= 1
                assert counts["decisions"] == 1
                assert counts["risks"] == 1
                assert counts["dependencies"] == 1
                assert counts["gaps"] == 1

            all_entities = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).all()
            assert len(all_entities) >= 1
            for ke in all_entities:
                assert len(ke.entity_type) <= 50
                assert len(ke.name) <= 255
        finally:
            db.close()
    finally:
        _cleanup_org(org_id)

