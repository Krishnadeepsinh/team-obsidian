import hashlib
import json
import os
import re
from html import escape
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


class PDFGenerator:
    """Enterprise Handover Dossier PDF Generator using ReportLab."""

    @staticmethod
    def compute_document_digest(handover_data: Dict[str, Any]) -> str:
        """Compute deterministic SHA-256 tamper-evident digest over dossier sections and claim states."""
        canonical_payload = {
            "title": str(handover_data.get("title", "")),
            "employee_name": str(handover_data.get("employee_name", "")),
            "project_name": str(handover_data.get("project_name", "")),
            "status": str(handover_data.get("status", "")),
            "sections": [
                {
                    "section_number": sec.get("section_number"),
                    "title": str(sec.get("title", "")),
                    "verification_status": str(sec.get("verification_status", "")),
                    "content": str(sec.get("content", "")),
                    "claims": [
                        {
                            "claim_text": str(c.get("claim_text", "")),
                            "verification_status": str(c.get("verification_status", "")),
                            "confidence": round(float(c.get("confidence", 0.0)), 4),
                            "evidence_count": int(c.get("evidence_count", len(c.get("evidence_ids") or []))),
                        }
                        for c in (sec.get("claims") or [])
                    ],
                }
                for sec in (handover_data.get("sections") or [])
            ],
        }
        serialized = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def generate_handover_pdf(self, handover_data: Dict[str, Any], output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=45,
            leftMargin=45,
            topMargin=45,
            bottomMargin=45,
        )

        styles = getSampleStyleSheet()
        primary_color = colors.HexColor("#1E1238")
        accent_color = colors.HexColor("#7C3AED")
        text_dark = colors.HexColor("#0F172A")
        text_muted = colors.HexColor("#475569")
        card_bg = colors.HexColor("#F8F9FD")

        title_style = ParagraphStyle(
            "ObsidianTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=primary_color,
            spaceAfter=6,
        )
        subtitle_style = ParagraphStyle(
            "ObsidianSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=14,
            textColor=text_muted,
            spaceAfter=14,
        )
        section_heading_style = ParagraphStyle(
            "ObsidianSectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=accent_color,
            spaceBefore=12,
            spaceAfter=4,
        )
        meta_style = ParagraphStyle(
            "ObsidianMeta",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=11,
            textColor=text_muted,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "ObsidianBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=13.5,
            textColor=text_dark,
            spaceAfter=6,
        )

        elements = []
        elements.append(Paragraph("TEAM OBSIDIAN — KNOWLEDGE HANDOVER DOSSIER", title_style))
        elements.append(
            Paragraph(
                f"{escape(str(handover_data.get('title', 'Project Handover')))} | "
                f"Project: {escape(str(handover_data.get('project_name', 'Project')))}",
                subtitle_style,
            )
        )
        elements.append(HRFlowable(width="100%", thickness=1.5, color=accent_color, spaceAfter=12))

        meta_rows = [
            ["Departing Specialist", f"{handover_data.get('departing_employee_name')} ({handover_data.get('departing_employee_role')})"],
            ["Incoming Successor", f"{handover_data.get('incoming_employee_name')} ({handover_data.get('incoming_employee_role')})"],
            ["Dossier Status", str(handover_data.get("status", "needs_review")).upper()],
            ["Evidence Confidence", f"{int(float(handover_data.get('overall_confidence', 0.0)) * 100)}%"],
            ["Generated Date", str(handover_data.get("created_at", ""))],
        ]
        meta_table = Table(meta_rows, colWidths=[160, 355])
        meta_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (0, -1), card_bg),
                ("TEXTCOLOR", (0, 0), (-1, -1), text_dark),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("PADDING", (0, 0), (-1, -1), 6),
            ])
        )
        elements.append(meta_table)
        elements.append(Spacer(1, 12))

        approvals = handover_data.get("approvals") or []
        if approvals:
            elements.append(Paragraph("Stakeholder Sign-Off Status", section_heading_style))
            app_rows = [["Role", "Approver", "Status", "Signed Date"]]
            for a in approvals:
                app_rows.append([
                    str(a.get("role", "")).replace("_", " ").title(),
                    str(a.get("approver_name", "")),
                    str(a.get("status", "pending")).upper(),
                    str(a.get("signed_at", "Pending")),
                ])
            app_table = Table(app_rows, colWidths=[125, 165, 110, 115])
            app_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), primary_color),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("PADDING", (0, 0), (-1, -1), 5),
                ])
            )
            elements.append(app_table)

        spofs = handover_data.get("spofs") or []
        if spofs:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Executive Bus-Factor & Single Points of Failure", section_heading_style))
            spof_rows = [[
                Paragraph("<b>Module / Entity</b>", body_style),
                Paragraph("<b>Severity</b>", body_style),
                Paragraph("<b>Primary Owner</b>", body_style),
                Paragraph("<b>Eff. Bus Factor</b>", body_style),
            ]]
            for spof in spofs[:12]:
                owners = spof.get("sole_owners") or [o.get("name") for o in (spof.get("owner_breakdown") or []) if o.get("name")]
                owner_str = ", ".join(str(x) for x in owners[:3]) if owners else "Unassigned"
                share = spof.get("ownership_share")
                share_label = f" ({round(float(share) * 100)}%)" if share is not None else ""
                eff_bf = spof.get("effective_bus_factor", spof.get("bus_factor", 1))
                spof_rows.append([
                    Paragraph(escape(str(spof.get("module") or spof.get("entity") or "Unknown")), meta_style),
                    Paragraph(escape(str(spof.get("spof_severity") or spof.get("risk_level") or "HIGH").upper()), meta_style),
                    Paragraph(escape(owner_str + share_label), meta_style),
                    Paragraph(escape(f"{float(eff_bf):.2f}"), meta_style),
                ])
            spof_table = Table(spof_rows, colWidths=[175, 80, 175, 85])
            spof_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE9FE")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 4),
                ])
            )
            elements.append(spof_table)

        if approvals or spofs:
            elements.append(PageBreak())

        for sec in handover_data.get("sections", []):
            num = sec.get("section_number", "")
            stitle = escape(str(sec.get("title", "")))
            vstat = escape(str(sec.get("verification_status", "Verified by Reviewer" if sec.get("is_verified") else "Needs Human Verification")))
            elements.append(Paragraph(f"Section {num}: {stitle}", section_heading_style))
            elements.append(Paragraph(f"Verification Status: {vstat}", meta_style))

            raw_content = str(sec.get("content", ""))
            for line in raw_content.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("- [ ] "):
                    stripped = "[ ] " + stripped[6:]
                elif stripped.startswith("- [x] ") or stripped.startswith("- [X] "):
                    stripped = "[x] " + stripped[6:]
                elif stripped.startswith("- "):
                    stripped = "• " + stripped[2:]
                clean = escape(stripped)
                clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
                clean = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", clean)
                clean = re.sub(r"`([^`]+)`", r'<font name="Courier" size="8.8">\1</font>', clean)
                elements.append(Paragraph(clean, body_style))

            claims = sec.get("claims") or []
            if claims:
                claim_rows = [[
                    Paragraph("<b>Atomic Claim</b>", meta_style),
                    Paragraph("<b>Status</b>", meta_style),
                    Paragraph("<b>Conf.</b>", meta_style),
                    Paragraph("<b>Evidence</b>", meta_style),
                ]]
                for clm in claims[:10]:
                    ctext = str(clm.get("claim_text", "")).strip()
                    if len(ctext) > 150:
                        ctext = ctext[:147].rstrip() + "..."
                    ev_cnt = int(clm.get("evidence_count", len(clm.get("evidence_ids") or [])))
                    conf_val = float(clm.get("confidence", 0.0))
                    claim_rows.append([
                        Paragraph(escape(ctext), meta_style),
                        Paragraph(escape(str(clm.get("verification_status", "Needs Verification"))), meta_style),
                        Paragraph(escape(f"{round(conf_val * 100)}%"), meta_style),
                        Paragraph(escape(f"{ev_cnt} ref(s)"), meta_style),
                    ])
                claim_table = Table(claim_rows, colWidths=[275, 115, 55, 70])
                claim_table.setStyle(
                    TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), card_bg),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("PADDING", (0, 0), (-1, -1), 4),
                    ])
                )
                elements.append(Spacer(1, 4))
                elements.append(claim_table)
                elements.append(Spacer(1, 4))

            refs = sec.get("evidence_refs") or []
            if refs:
                elements.append(Paragraph("Supporting Evidence: " + escape("; ".join(refs)), meta_style))

            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceBefore=4, spaceAfter=6))

        document_digest = self.compute_document_digest(handover_data)
        handover_data["document_sha256"] = document_digest
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Audit Integrity & Tamper-Evident Digest", section_heading_style))
        elements.append(
            Paragraph(
                f'Document SHA-256: <font name="Courier" size="8.5">{escape(document_digest)}</font>',
                meta_style,
            )
        )

        doc.build(elements)
        return output_path


pdf_generator = PDFGenerator()
