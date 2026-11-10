import os
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
            elements.append(PageBreak())

        for sec in handover_data.get("sections", []):
            num = sec.get("section_number", "")
            stitle = escape(str(sec.get("title", "")))
            vstat = escape(str(sec.get("verification_status", "Verified by Reviewer" if sec.get("is_verified") else "Needs Human Verification")))
            elements.append(Paragraph(f"Section {num}: {stitle}", section_heading_style))
            elements.append(Paragraph(f"Verification Status: {vstat}", meta_style))

            raw_content = str(sec.get("content", ""))
            for line in raw_content.splitlines():
                clean = escape(line).replace("**", "")
                if clean.strip():
                    elements.append(Paragraph(clean, body_style))

            refs = sec.get("evidence_refs") or []
            if refs:
                elements.append(Paragraph("Supporting Evidence: " + escape("; ".join(refs)), meta_style))

            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E2E8F0"), spaceBefore=4, spaceAfter=6))

        doc.build(elements)
        return output_path


pdf_generator = PDFGenerator()
