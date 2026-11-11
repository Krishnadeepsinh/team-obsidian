import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.permissions import normalize_role
from app.models.evidence import Evidence
from app.models.handover import (
    Handover,
    HandoverApproval,
    HandoverClaim,
    HandoverSection,
    HandoverVersion,
)
from app.models.integration import Document, Integration, SourceRecord
from app.models.knowledge import (
    Decision,
    Dependency,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    Responsibility,
    RiskItem,
    TaskItem,
)
from app.models.workspace import Project, ProjectMember, User
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity
from app.services.graph_service import graph_service

logger = logging.getLogger("team_obsidian.handover")


class GeneratedSectionItem(BaseModel):
    section_number: int
    content: str
    claim_statements: List[str] = Field(default_factory=list)
    evidence_indices: List[int] = Field(default_factory=list)
    has_sufficient_evidence: bool = True


class GeneratedDossierPayload(BaseModel):
    sections: List[GeneratedSectionItem] = Field(default_factory=list)


class HandoverEngine:
    """Source-aware, project-aware, evidence-grounded 16-section Handover Engine."""

    SECTION_DEFINITIONS = [
        (1, "Project Overview", "Project purpose, business objectives, technical scope, major components, technologies, and status."),
        (2, "Employee Responsibilities", "Responsibilities, maintained services, owned modules, and operational ownership of the departing member."),
        (3, "Completed Work", "Completed features, merged pull requests, completed tasks, and delivered milestones."),
        (4, "Work in Progress", "Open pull requests, active branches, pending reviews, and ongoing refactors."),
        (5, "Unfinished Tasks & Reassignments", "Outstanding tasks, priority, owner, suggested successor, dependencies, and deadlines."),
        (6, "Important Technical Decisions", "Key architectural and engineering decisions, dates, owners, and supporting evidence."),
        (7, "Decision Reasoning & Alternatives", "Rationale, considered alternatives, rejection reasons, trade-offs, and consequences."),
        (8, "Technical Architecture & Components", "System architecture, services, modules, APIs, databases, infrastructure, and pipelines."),
        (9, "Critical Dependencies", "Internal/external dependencies, third-party vendors, upstream/downstream failure impact."),
        (10, "Known Issues & Technical Quirks", "Known bugs, production incidents, workarounds, technical debt, and non-obvious behavior."),
        (11, "Risks & Single Points of Failure", "Single-owner components, undocumented critical knowledge, security/operational risks, mitigations."),
        (12, "Knowledge Gaps & Unresolved Questions", "Missing runbooks, unclear ownership, unverified assumptions, and open questions."),
        (13, "Important Contacts & Subject Matter Experts", "Authorized project stakeholders, tech leads, PMs, QA, and domain owners."),
        (14, "Required Access & Permissions", "Repositories, environments, cloud consoles, databases, monitoring, and secrets managers (never raw secrets)."),
        (15, "Recommended Day 1–30 Action Plan", "Data-driven Day 1-3, Day 4-7, Day 8-14, and Day 15-30 onboarding roadmap."),
        (16, "Evidence References & Audit Trail", "Traceable evidence IDs, source links, excerpts, authors, timestamps, and SHA-256 hashes."),
    ]

    def _filter_by_selected_sources(
        self,
        source_ids: List[str],
        evidences: List[Evidence],
        source_records: List[SourceRecord],
        documents: List[Document],
    ) -> Tuple[List[Evidence], List[SourceRecord], List[Document]]:
        """Filter records by selected_source_ids (which may be integration IDs, provider names, source record IDs, or document IDs)."""
        if not source_ids:
            return evidences, source_records, documents

        sel = {str(s).strip().lower() for s in source_ids if s}
        filtered_sr = [
            sr
            for sr in source_records
            if sr.id.lower() in sel
            or sr.integration_id.lower() in sel
            or sr.source_type.lower() in sel
            or any(tag in sr.source_type.lower() for tag in sel)
        ]
        filtered_docs = [
            d
            for d in documents
            if d.id.lower() in sel or "document" in sel or "documents" in sel
        ]
        allowed_sr_ids = {sr.id for sr in filtered_sr}
        allowed_doc_ids = {d.id for d in filtered_docs}

        filtered_ev = [
            ev
            for ev in evidences
            if ev.id.lower() in sel
            or (ev.source_record_id and ev.source_record_id in allowed_sr_ids)
            or (ev.document_id and ev.document_id in allowed_doc_ids)
            or ev.source_type.lower() in sel
            or any(tag in ev.source_type.lower() for tag in sel)
        ]
        # Only fall back if caller passed non-matching filters? No: preserve strict filter transparency!
        return filtered_ev, filtered_sr, filtered_docs

    def _build_approvers(
        self,
        db: Session,
        project_id: str,
        departing_name: str,
        incoming_name: str,
        requested_approvers: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Build configurable stakeholder approval chain strictly from request config or actual project members."""
        if requested_approvers:
            return [
                {
                    "role": normalize_role(a["role"]),
                    "approver_name": a["approver_name"],
                    "approver_user_id": a.get("approver_user_id"),
                    "is_required": a.get("is_required", True),
                }
                for a in requested_approvers
            ]

        members = db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all()
        role_lookup: Dict[str, Tuple[str, str]] = {}
        for m in members:
            u = db.query(User).filter(User.id == m.user_id).first()
            if not u:
                continue
            r = normalize_role(m.project_role)
            role_lookup.setdefault(r, (u.name, u.id))

        approvals: List[Dict[str, Any]] = []
        if "tech_lead" in role_lookup:
            name, uid = role_lookup["tech_lead"]
            approvals.append({"role": "tech_lead", "approver_name": name, "approver_user_id": uid, "is_required": True})
        elif "project_owner" in role_lookup:
            name, uid = role_lookup["project_owner"]
            approvals.append({"role": "tech_lead", "approver_name": name, "approver_user_id": uid, "is_required": True})

        if "project_manager" in role_lookup:
            name, uid = role_lookup["project_manager"]
            approvals.append({"role": "project_manager", "approver_name": name, "approver_user_id": uid, "is_required": True})

        dep_uid = role_lookup.get("departing_employee", (None, None))[1]
        inc_uid = role_lookup.get("incoming_employee", (None, None))[1]
        approvals.append({
            "role": "departing_employee",
            "approver_name": departing_name,
            "approver_user_id": dep_uid,
            "is_required": True,
        })
        approvals.append({
            "role": "incoming_employee",
            "approver_name": incoming_name,
            "approver_user_id": inc_uid,
            "is_required": True,
        })
        return approvals

    def reconstruct_and_generate(
        self,
        db: Session,
        project_id: str,
        departing_name: str,
        departing_role: str,
        incoming_name: str,
        incoming_role: str,
        source_ids: List[str],
        categories: List[str],
        target_date: Optional[str] = None,
        approvers: Optional[List[Dict[str, Any]]] = None,
        created_by_user_id: Optional[str] = None,
    ) -> Handover:
        """Synthesize an evidence-grounded 16-section handover dossier strictly from authorized project data."""
        project = db.query(Project).filter(Project.id == project_id).first()
        integrations = db.query(Integration).filter(Integration.project_id == project_id).all()
        all_source_records = db.query(SourceRecord).filter(SourceRecord.project_id == project_id).all()
        all_documents = db.query(Document).filter(Document.project_id == project_id).all()
        all_evidences = db.query(Evidence).filter(Evidence.project_id == project_id).all()

        evidences, source_records, documents = self._filter_by_selected_sources(
            source_ids, all_evidences, all_source_records, all_documents
        )
        allowed_ev_ids = {e.id for e in evidences}

        decisions = db.query(Decision).filter(Decision.project_id == project_id).all()
        tasks = db.query(TaskItem).filter(TaskItem.project_id == project_id).all()
        risks = db.query(RiskItem).filter(RiskItem.project_id == project_id).all()
        gaps = db.query(KnowledgeGap).filter(KnowledgeGap.project_id == project_id).all()
        deps = db.query(Dependency).filter(Dependency.project_id == project_id).all()
        responsibilities = db.query(Responsibility).filter(Responsibility.project_id == project_id).all()
        entities = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).all()
        relationships = db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == project_id).all()

        if source_ids:
            decisions = [d for d in decisions if not d.evidence_ids or any(eid in allowed_ev_ids for eid in d.evidence_ids)]
            tasks = [t for t in tasks if not t.evidence_ids or any(eid in allowed_ev_ids for eid in t.evidence_ids)]
            risks = [r for r in risks if not r.evidence_ids or any(eid in allowed_ev_ids for eid in r.evidence_ids)]
            deps = [dep for dep in deps if not dep.evidence_ids or any(eid in allowed_ev_ids for eid in dep.evidence_ids)]

        members = db.query(ProjectMember).filter(ProjectMember.project_id == project_id).all()
        stakeholders = []
        for m in members:
            u = db.query(User).filter(User.id == m.user_id).first()
            if u:
                stakeholders.append({
                    "name": u.name,
                    "email": u.email,
                    "role": m.project_role,
                    "title": u.title,
                    "department": u.department,
                })

        # Compute explainable confidence from actual evidence coverage & verification
        ev_docs_for_conf = [
            {
                "id": e.id,
                "source_type": e.source_type,
                "source_title": e.source_title,
                "verification_status": e.verification_status,
                "source_timestamp": e.source_timestamp or e.created_at,
                "retrieval_score": e.confidence or 0.7,
            }
            for e in evidences
        ]
        overall_confidence, confidence_breakdown = ai_engine.compute_explainable_confidence(ev_docs_for_conf)

        title = f"{departing_name} → {incoming_name} Knowledge Handover Dossier"
        handover = Handover(
            project_id=project_id,
            title=title,
            departing_employee_name=departing_name,
            departing_employee_role=departing_role,
            incoming_employee_name=incoming_name,
            incoming_employee_role=incoming_role,
            status="needs_review",
            target_date=target_date,
            selected_sources=source_ids,
            selected_categories=categories,
            reconstruction_stats={
                "decisions_analyzed": len(decisions),
                "tasks_extracted": len(tasks),
                "risks_identified": len(risks),
                "gaps_detected": len(gaps),
                "dependencies_mapped": len(deps),
                "entities_graphed": len(entities),
                "source_records_used": len(source_records),
                "documents_used": len(documents),
                "evidences_grounded": len(evidences),
            },
            overall_confidence=overall_confidence,
            confidence_breakdown=confidence_breakdown,
            created_by_user_id=created_by_user_id,
        )
        db.add(handover)
        db.flush()

        # Synthesize all 16 sections with section-specific evidence & claims
        section_specs = self._build_16_sections(
            project=project,
            departing_name=departing_name,
            departing_role=departing_role,
            incoming_name=incoming_name,
            incoming_role=incoming_role,
            integrations=integrations,
            source_records=source_records,
            documents=documents,
            evidences=evidences,
            decisions=decisions,
            tasks=tasks,
            risks=risks,
            gaps=gaps,
            deps=deps,
            responsibilities=responsibilities,
            entities=entities,
            relationships=relationships,
            stakeholders=stakeholders,
        )

        for sec_spec in section_specs:
            sec_record = HandoverSection(
                handover_id=handover.id,
                section_number=sec_spec["section_number"],
                title=sec_spec["title"],
                content=sec_spec["content"],
                is_verified=False,  # Never auto-verify AI-generated claims!
                verification_status=sec_spec["verification_status"],
                confidence=sec_spec["confidence"],
                evidence_ids=sec_spec["evidence_ids"],
                comments=[],
            )
            db.add(sec_record)
            db.flush()

            for claim_text in sec_spec["claims"]:
                db.add(
                    HandoverClaim(
                        handover_id=handover.id,
                        section_id=sec_record.id,
                        claim_text=claim_text,
                        verification_status=sec_spec["verification_status"],
                        confidence=sec_spec["confidence"],
                        evidence_ids=sec_spec["evidence_ids"],
                    )
                )

        # Configurable stakeholder approvals
        approver_list = self._build_approvers(db, project_id, departing_name, incoming_name, approvers)
        for idx, ap in enumerate(approver_list):
            db.add(
                HandoverApproval(
                    handover_id=handover.id,
                    approver_user_id=ap.get("approver_user_id"),
                    approver_name=ap["approver_name"],
                    role=ap["role"],
                    status="pending",
                    is_required=ap.get("is_required", True),
                    order_index=idx,
                )
            )

        db.add(
            HandoverVersion(
                handover_id=handover.id,
                version_number=1,
                user_id=created_by_user_id,
                changed_section="All 16 Sections",
                changelog="Initial evidence-grounded reconstruction generated.",
                reason="Initial dossier generation",
                snapshot={
                    "title": title,
                    "sections_count": 16,
                    "confidence": overall_confidence,
                    "evidences_grounded": len(evidences),
                },
                created_by="TEAM OBSIDIAN Reconstruction Engine",
            )
        )

        record_activity(
            db=db,
            action="handover.generated",
            entity_type="handover",
            entity_id=handover.id,
            user_id=created_by_user_id,
            project_id=project_id,
            details={"message": f"Generated 16-section handover dossier '{title}' (confidence {overall_confidence})"},
        )
        db.commit()
        db.refresh(handover)
        return handover

    def _build_16_sections(
        self,
        project: Optional[Project],
        departing_name: str,
        departing_role: str,
        incoming_name: str,
        incoming_role: str,
        integrations: List[Integration],
        source_records: List[SourceRecord],
        documents: List[Document],
        evidences: List[Evidence],
        decisions: List[Decision],
        tasks: List[TaskItem],
        risks: List[RiskItem],
        gaps: List[KnowledgeGap],
        deps: List[Dependency],
        responsibilities: List[Responsibility],
        entities: List[KnowledgeEntity],
        relationships: List[KnowledgeRelationship],
        stakeholders: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Assemble each of the 16 sections using strictly section-relevant records & evidence."""
        ev_map = {e.id: e for e in evidences}

        def _sec_status(ev_ids: List[str], has_data: bool) -> Tuple[str, float]:
            if not has_data and not ev_ids:
                return "Unknown / Missing Evidence", 0.0
            if ev_ids:
                sec_evs = [
                    {
                        "id": eid,
                        "source_type": ev_map[eid].source_type,
                        "source_title": ev_map[eid].source_title,
                        "verification_status": ev_map[eid].verification_status,
                        "source_timestamp": ev_map[eid].source_timestamp or ev_map[eid].created_at,
                        "retrieval_score": ev_map[eid].confidence or 0.75,
                    }
                    for eid in ev_ids
                    if eid in ev_map
                ]
                if sec_evs:
                    conf, _ = ai_engine.compute_explainable_confidence(sec_evs)
                    return "Supported by Evidence", conf
            return "Needs Human Verification", 0.35

        def _collect_ev_ids(items, attr="evidence_ids") -> List[str]:
            ids: List[str] = []
            for item in items:
                val = getattr(item, attr, None)
                if isinstance(val, list):
                    for eid in val:
                        if eid in ev_map and eid not in ids:
                            ids.append(eid)
                elif isinstance(val, str) and val in ev_map and val not in ids:
                    ids.append(val)
            return ids

        # Partition tasks & source records honestly
        dep_lower = departing_name.lower()
        dep_tasks = [t for t in tasks if dep_lower in (t.owner or "").lower() or t.is_departing_owner]
        completed_tasks = [t for t in tasks if t.status == "completed"]
        open_tasks = [t for t in tasks if t.status != "completed"]

        merged_prs = [
            sr
            for sr in source_records
            if sr.source_type == "github_pr" and (sr.metadata_json or {}).get("state") == "merged"
        ]
        open_prs = [
            sr
            for sr in source_records
            if sr.source_type == "github_pr" and (sr.metadata_json or {}).get("state") == "open"
        ]
        commits = [sr for sr in source_records if sr.source_type == "github_commit"]

        entity_dicts = [{"id": e.id, "name": e.name, "entity_type": e.entity_type} for e in entities]
        rel_dicts = [
            {"source_entity_id": r.source_entity_id, "target_entity_id": r.target_entity_id, "relation_type": r.relation_type}
            for r in relationships
        ]
        spofs = graph_service.detect_single_points_of_failure(entity_dicts, rel_dicts)

        proj_name = project.name if project else "Workspace Project"
        proj_desc = (project.description or "No project description recorded.") if project else ""

        # Section 1: Project Overview
        s1_evs = [e.id for e in evidences if e.source_type in ("document", "notion_page", "github_pr")][:6]
        if not s1_evs and evidences:
            s1_evs = [e.id for e in evidences[:6]]
        tech_entities = [e for e in entities if (e.entity_type or "").lower() in ("system", "service", "component", "database", "infrastructure")]
        s1_lines = [
            f"**Project:** {proj_name} ({project.status if project else 'active'})",
            f"**Description:** {proj_desc}",
            f"**Transition Scope:** Handover from **{departing_name}** ({departing_role}) to **{incoming_name}** ({incoming_role}).",
            f"**Connected Sources:** {', '.join(f'{i.name} ({i.provider})' for i in integrations) if integrations else 'None connected yet.'}",
            f"**Documents Indexed:** {len(documents)} | **Source Records:** {len(source_records)} | **Components Mapped:** {len(tech_entities)}",
        ]
        if tech_entities:
            s1_lines.append("**Major Components:** " + ", ".join(f"`{e.name}` ({e.entity_type})" for e in tech_entities[:12]))
        s1_status, s1_conf = _sec_status(s1_evs, bool(project or tech_entities))

        # Section 2: Employee Responsibilities
        dep_resps = [r for r in responsibilities if dep_lower in (r.owner or "").lower()]
        dep_authored_evs = [e for e in evidences if e.source_author and dep_lower in e.source_author.lower()]
        s2_evs = list(dict.fromkeys(_collect_ev_ids(dep_resps) + [e.id for e in dep_authored_evs[:6]]))
        s2_lines = []
        if dep_resps:
            s2_lines.append(f"Documented areas owned by **{departing_name}**:")
            for r in dep_resps:
                s2_lines.append(f"- **{r.domain}** (Criticality: {r.criticality.upper()}): {r.scope} | Backup: {r.backup_owner or 'None assigned'}")
        if dep_authored_evs:
            s2_lines.append(f"\nAuthored/maintained source artifacts linked to **{departing_name}** ({len(dep_authored_evs)} found):")
            for e in dep_authored_evs[:6]:
                s2_lines.append(f"- [{e.source_type}] {e.source_title}")
        if not s2_lines:
            s2_lines.append(
                f"**Unknown / Missing Evidence:** No explicit responsibilities or authored records matched `{departing_name}` in current project sources. "
                "Human review required to confirm service ownership."
            )
        s2_status, s2_conf = _sec_status(s2_evs, bool(dep_resps or dep_authored_evs))

        # Section 3: Completed Work
        s3_evs = list(dict.fromkeys(_collect_ev_ids(completed_tasks) + [e.id for e in evidences if e.source_record_id in {pr.id for pr in merged_prs}]))
        s3_lines = []
        for t in completed_tasks[:10]:
            s3_lines.append(f"- **Task Completed:** {t.title} (Owner: {t.owner}) — {t.description or ''}")
        for pr in merged_prs[:10]:
            s3_lines.append(f"- **Merged PR:** [{pr.title}]({pr.url or '#'}) by {pr.author or 'contributor'}")
        for c in commits[:6]:
            if not merged_prs:
                s3_lines.append(f"- **Commit:** {c.title} ({c.author or 'contributor'})")
        if not s3_lines:
            s3_lines.append("**Unknown / Missing Evidence:** No completed tasks, merged pull requests, or commits have been ingested yet.")
        s3_status, s3_conf = _sec_status(s3_evs, bool(completed_tasks or merged_prs or commits))

        # Section 4: Work in Progress
        wip_tasks = [t for t in tasks if t.status in ("in_progress", "blocked")]
        s4_evs = list(dict.fromkeys(_collect_ev_ids(wip_tasks) + [e.id for e in evidences if e.source_record_id in {pr.id for pr in open_prs}]))
        s4_lines = []
        for pr in open_prs[:10]:
            s4_lines.append(f"- **Open PR:** [{pr.title}]({pr.url or '#'}) by {pr.author or 'contributor'}")
        for t in wip_tasks[:10]:
            s4_lines.append(f"- **{t.status.upper()}:** {t.title} (Owner: {t.owner}) — {t.description or ''}")
        if not s4_lines:
            s4_lines.append("No open pull requests or in-progress/blocked tasks currently recorded in ingested sources.")
        s4_status, s4_conf = _sec_status(s4_evs, bool(wip_tasks or open_prs))

        # Section 5: Unfinished Tasks & Reassignments
        s5_evs = _collect_ev_ids(open_tasks)
        s5_lines = []
        for t in open_tasks[:15]:
            sugg = t.suggested_reassignment or incoming_name
            s5_lines.append(
                f"- **{t.title}** | Priority: `{t.priority.upper()}` | Status: `{t.status}` | "
                f"Current Owner: {t.owner} → Suggested Successor: **{sugg}**"
                + (f" | Deadline: {t.deadline}" if t.deadline else "")
            )
        if not s5_lines:
            s5_lines.append("No unfinished tasks recorded in this project.")
        s5_status, s5_conf = _sec_status(s5_evs, bool(open_tasks))

        # Section 6: Important Technical Decisions
        s6_evs = _collect_ev_ids(decisions)
        s6_lines = []
        for d in decisions:
            s6_lines.append(
                f"- **{d.title}** ({d.date}) — Decided by: {d.decision_maker} | Component: {d.component or 'General'} | Status: `{d.status}`\n"
                f"  Summary: {d.summary}"
            )
        if not s6_lines:
            s6_lines.append("**Unknown / Missing Evidence:** No Architectural Decision Records (ADRs) extracted or logged yet.")
        s6_status, s6_conf = _sec_status(s6_evs, bool(decisions))

        # Section 7: Decision Reasoning & Alternatives
        s7_lines = []
        for d in decisions:
            reasoning_text = (d.reasoning or "").strip() or (d.summary or "").strip() or "Not documented"
            alts = ", ".join(d.alternatives) if d.alternatives else "None documented"
            trds = ", ".join(d.tradeoffs) if d.tradeoffs else "None documented"
            cons = ", ".join(getattr(d, "consequences", None) or []) or "None documented"
            s7_lines.append(
                f"- **{d.title}**\n"
                f"  - *Reasoning:* {reasoning_text}\n"
                f"  - *Rejected Alternatives:* {alts}\n"
                f"  - *Trade-offs:* {trds} | *Consequences:* {cons}"
            )
        if not s7_lines:
            s7_lines.append("**Unknown / Missing Evidence:** No decision rationale or rejected alternatives available in current evidence.")
        s7_status, s7_conf = _sec_status(s6_evs, bool(decisions))

        # Section 8: Technical Architecture & Components
        s8_evs = [e.evidence_id for e in tech_entities if e.evidence_id and e.evidence_id in ev_map]
        s8_lines = []
        if tech_entities:
            for e in tech_entities:
                s8_lines.append(f"- **`{e.name}`** ({e.entity_type}): {e.description or 'Component in system graph.'}")
        if relationships:
            s8_lines.append("\n**Mapped System Interactions:**")
            ent_name_by_id = {e.id: e.name for e in entities}
            for r in relationships[:20]:
                s8_lines.append(
                    f"- `{ent_name_by_id.get(r.source_entity_id, r.source_entity_id)}` —[{r.relation_type}]→ "
                    f"`{ent_name_by_id.get(r.target_entity_id, r.target_entity_id)}`"
                    + (f" ({r.context})" if r.context else "")
                )
        if not s8_lines:
            s8_lines.append("**Unknown / Missing Evidence:** No architecture components or service relationships extracted yet. Upload architecture specs or sync repositories.")
        s8_status, s8_conf = _sec_status(s8_evs, bool(tech_entities or relationships))

        # Section 9: Critical Dependencies
        s9_evs = _collect_ev_ids(deps)
        s9_lines = []
        for dep in deps:
            s9_lines.append(
                f"- `{dep.source_component}` → `{dep.target_component}` (`{dep.dependency_type}`, Criticality: `{dep.criticality.upper()}`): "
                f"{dep.description or 'Failure in target impacts source component.'}"
            )
        if not s9_lines:
            s9_lines.append("**Unknown / Missing Evidence:** No component or external vendor dependencies mapped yet.")
        s9_status, s9_conf = _sec_status(s9_evs, bool(deps))

        # Section 10: Known Issues & Technical Quirks
        quirk_risks = [r for r in risks if r.category in ("unresolved_bug", "technical_debt", "workaround", "technical_risk")]
        issue_records = [sr for sr in source_records if sr.source_type == "github_issue"]
        s10_evs = list(dict.fromkeys(_collect_ev_ids(quirk_risks) + [e.id for e in evidences if e.source_record_id in {ir.id for ir in issue_records}]))
        s10_lines = []
        for r in quirk_risks:
            s10_lines.append(f"- **{r.title}** ({r.severity.upper()}): {r.description}" + (f" Workaround/Mitigation: {r.mitigation_strategy}" if r.mitigation_strategy else ""))
        for ir in issue_records[:8]:
            s10_lines.append(f"- **Issue:** [{ir.title}]({ir.url or '#'}) — {ir.content[:180]}")
        if not s10_lines:
            s10_lines.append("No known bugs, production incidents, or workarounds found in connected sources.")
        s10_status, s10_conf = _sec_status(s10_evs, bool(quirk_risks or issue_records))

        # Section 11: Risks & Single Points of Failure
        s11_evs = _collect_ev_ids(risks)
        s11_lines = []
        for r in risks:
            s11_lines.append(
                f"- **{r.title}** | Severity: `{r.severity.upper()}` | Likelihood: `{r.likelihood.upper()}`\n"
                f"  {r.description} | Mitigation: {r.mitigation_strategy or 'No mitigation documented'}"
            )
        for sp in spofs:
            s11_lines.append(
                f"- **Single Point of Failure:** `{sp['component_name']}` ({sp['component_type']}) relies solely on **{sp['sole_owner']}** "
                f"(downstream blast radius: {sp['downstream_impact_count']} component(s))."
            )
        if not s11_lines:
            s11_lines.append("No risks or single points of failure detected from current graph/risk register.")
        s11_status, s11_conf = _sec_status(s11_evs, bool(risks or spofs))

        # Section 12: Knowledge Gaps & Unresolved Questions
        s12_lines = []
        for g in gaps:
            s12_lines.append(
                f"- **{g.title}** (`{g.gap_type}`, Severity: `{g.severity.upper()}`, Status: `{g.status}`): "
                f"{g.description} | Impact: {g.impact} | Recommended Action: {g.recommended_action}"
            )
        if not s12_lines:
            s12_lines.append("No unresolved knowledge gaps recorded, though human review should confirm missing runbooks.")
        s12_status, s12_conf = ("Supported by Evidence" if gaps else "Needs Human Verification"), (0.75 if gaps else 0.4)

        # Section 13: Important Contacts & Subject Matter Experts
        s13_lines = []
        for st in stakeholders:
            s13_lines.append(
                f"- **{st['name']}** — Role: `{st['role']}`"
                + (f" ({st['title']})" if st.get("title") else "")
                + (f" | Dept: {st['department']}" if st.get("department") else "")
                + f" | Email: {st['email']}"
            )
        if not s13_lines:
            s13_lines.append(
                f"- **{incoming_name}** ({incoming_role}) — Incoming Successor\n"
                f"- **{departing_name}** ({departing_role}) — Departing Specialist\n"
                "*(Invite additional project members in Team/Projects to populate full SME directory.)*"
            )
        s13_status, s13_conf = ("Supported by Evidence" if stakeholders else "Needs Human Verification"), (0.85 if stakeholders else 0.5)

        def _cfg_target(integ: Integration) -> str:
            cfg = integ.config or {}
            if isinstance(cfg.get("repos"), list) and cfg["repos"]:
                return ", ".join(str(x) for x in cfg["repos"][:3])
            if isinstance(cfg.get("channels"), list) and cfg["channels"]:
                return ", ".join(str(x) for x in cfg["channels"][:3])
            if isinstance(cfg.get("targets"), list) and cfg["targets"]:
                return ", ".join(str(x) for x in cfg["targets"][:3])
            return (
                cfg.get("repo")
                or cfg.get("channel_id")
                or cfg.get("channel")
                or cfg.get("database_id")
                or cfg.get("page_id")
                or cfg.get("target")
                or "Connected Workspace"
            )

        # Section 14: Required Access & Permissions (strictly NO raw secrets/tokens)
        access_targets = []
        for i in integrations:
            cfg_target = _cfg_target(i)
            access_targets.append(f"- [ ] **{i.provider.upper()}** (`{i.name}` — target: `{cfg_target}`): Grant least-privilege access to {incoming_name}")
        for comp in tech_entities[:8]:
            if (comp.entity_type or "").lower() in ("database", "infrastructure", "vendor"):
                access_targets.append(f"- [ ] **{comp.entity_type} Access (`{comp.name}`):** Provision role-based access via IAM/vault (never share raw tokens)")
        if not access_targets:
            access_targets.append(f"- [ ] Confirm required repositories, staging/production environments, databases, and monitoring access for **{incoming_name}**.")
        s14_text = "Access provisioning checklist (passwords, private keys, and raw API tokens are intentionally excluded):\n" + "\n".join(access_targets)
        s14_status, s14_conf = _sec_status(s1_evs, bool(integrations or tech_entities))

        # Section 15: Recommended Day 1-30 Action Plan (derived from actual project artifacts)
        top_repos = ", ".join({_cfg_target(i) if _cfg_target(i) != "Connected Workspace" else i.name for i in integrations}) or proj_name
        top_decisions = ", ".join(d.title for d in decisions[:3]) or "logged project decisions"
        top_open = ", ".join(t.title for t in open_tasks[:3]) or "assigned backlog items"
        top_risk = risks[0].title if risks else (gaps[0].title if gaps else "unverified operational assumptions")
        s15_text = (
            f"**Days 1–3 (Orientation & Access):**\n"
            f"- Review project overview for **{proj_name}** and obtain least-privilege access for {top_repos}.\n"
            f"- Inspect uploaded architecture docs ({len(documents)}) and configure local dev environment.\n\n"
            f"**Days 4–7 (Decisions & Pairing):**\n"
            f"- Review critical ADRs ({top_decisions}) and pair with **{departing_name}** on open questions ({len(gaps)} gap(s)).\n"
            f"- Walk through open PRs ({len(open_prs)}) and active services ({len(tech_entities)} components mapped).\n\n"
            f"**Days 8–14 (Dependencies & Shadowing):**\n"
            f"- Trace {len(deps)} critical dependencies and review mitigation for **{top_risk}**.\n"
            f"- Shadow deployments/runbooks and validate monitoring alerts.\n\n"
            f"**Days 15–30 (Ownership Cutover):**\n"
            f"- Assume ownership of reassigned tasks ({top_open}), resolve open knowledge gaps, and sign successor acknowledgement."
        )
        s15_evs = s5_evs or s1_evs
        if s15_evs:
            s15_status, s15_conf = _sec_status(s15_evs, True)
            if s15_status == "Supported by Evidence":
                s15_status = "Needs Human Verification"
        else:
            s15_status, s15_conf = ("Needs Human Verification", 0.25)

        # Section 16: Evidence References & Audit Trail
        s16_evs = [e.id for e in evidences]
        s16_lines = []
        for e in evidences[:30]:
            ts = (e.source_timestamp or e.created_at).strftime("%Y-%m-%d %H:%M UTC") if (e.source_timestamp or e.created_at) else "N/A"
            s16_lines.append(
                f"- **[{e.id[:8]}] {e.source_title}** (`{e.source_type}`)\n"
                f"  Author: {e.source_author or 'Unknown'} | Date: {ts} | Status: `{e.verification_status}` | SHA-256: `{e.content_hash[:16]}...`\n"
                + (f"  URL: {e.source_url}\n" if e.source_url else "")
                + f"  Excerpt: \"{e.excerpt[:180].replace(chr(10), ' ')}...\""
            )
        if not s16_lines:
            s16_lines.append("**Unknown / Missing Evidence:** No source evidence records have been ingested into this project yet.")
        s16_status, s16_conf = _sec_status(s16_evs, bool(evidences))

        raw_sections = [
            (1, "Project Overview", "\n".join(s1_lines), s1_evs, s1_status, s1_conf),
            (2, "Employee Responsibilities", "\n".join(s2_lines), s2_evs, s2_status, s2_conf),
            (3, "Completed Work", "\n".join(s3_lines), s3_evs, s3_status, s3_conf),
            (4, "Work in Progress", "\n".join(s4_lines), s4_evs, s4_status, s4_conf),
            (5, "Unfinished Tasks & Reassignments", "\n".join(s5_lines), s5_evs, s5_status, s5_conf),
            (6, "Important Technical Decisions", "\n".join(s6_lines), s6_evs, s6_status, s6_conf),
            (7, "Decision Reasoning & Alternatives", "\n".join(s7_lines), s6_evs, s7_status, s7_conf),
            (8, "Technical Architecture & Components", "\n".join(s8_lines), s8_evs, s8_status, s8_conf),
            (9, "Critical Dependencies", "\n".join(s9_lines), s9_evs, s9_status, s9_conf),
            (10, "Known Issues & Technical Quirks", "\n".join(s10_lines), s10_evs, s10_status, s10_conf),
            (11, "Risks & Single Points of Failure", "\n".join(s11_lines), s11_evs, s11_status, s11_conf),
            (12, "Knowledge Gaps & Unresolved Questions", "\n".join(s12_lines), [], s12_status, s12_conf),
            (13, "Important Contacts & Subject Matter Experts", "\n".join(s13_lines), [], s13_status, s13_conf),
            (14, "Required Access & Permissions", s14_text, s1_evs, s14_status, s14_conf),
            (15, "Recommended Day 1–30 Action Plan", s15_text, s5_evs or s1_evs, s15_status, s15_conf),
            (16, "Evidence References & Audit Trail", "\n".join(s16_lines), s16_evs, s16_status, s16_conf),
        ]

        results: List[Dict[str, Any]] = []
        for sec_num, sec_title, content, sec_evs, sec_status, sec_conf in raw_sections:
            bullet_claims = [
                re.sub(r"^-\s*(\[[ xX]\]\s*)?", "", ln.strip()).strip()
                for ln in content.splitlines()
                if ln.strip().startswith("- ")
            ]
            if bullet_claims:
                claims = bullet_claims[:6]
            else:
                claims = [ln.strip() for ln in content.splitlines() if ln.strip()][:6]
                if not claims and content.strip():
                    claims = [content.strip()]
            results.append({
                "section_number": sec_num,
                "title": sec_title,
                "content": content,
                "evidence_ids": sec_evs[:15],
                "verification_status": sec_status,
                "confidence": round(min(0.99, max(0.0, sec_conf)), 2),
                "claims": claims,
            })
        return results


handover_engine = HandoverEngine()
