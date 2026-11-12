import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.permissions import normalize_role
from app.models.evidence import Evidence
from app.models.handover import (
    ExitInterviewQuestion,
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
    KnowledgeDriftEvent,
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
from app.services.identity_resolver import build_project_identity_map, resolve_author_name

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

        # Synthesize all 16 sections with section-specific evidence & atomic per-claim provenance
        identity_map = build_project_identity_map(project_id, db)
        exit_qa = (
            db.query(ExitInterviewQuestion)
            .filter(
                ExitInterviewQuestion.handover_id == handover.id,
                ExitInterviewQuestion.status == "answered",
            )
            .all()
        )
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
            identity_map=identity_map,
            exit_qa=exit_qa,
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

            for claim_item in sec_spec["claims"]:
                if isinstance(claim_item, dict):
                    c_text = claim_item["claim_text"]
                    c_evs = claim_item.get("evidence_ids") or []
                    c_conf = claim_item.get("confidence", sec_spec["confidence"])
                    c_status = claim_item.get("verification_status", sec_spec["verification_status"])
                else:
                    c_text = str(claim_item)
                    c_evs = sec_spec["evidence_ids"]
                    c_conf = sec_spec["confidence"]
                    c_status = sec_spec["verification_status"]
                db.add(
                    HandoverClaim(
                        handover_id=handover.id,
                        section_id=sec_record.id,
                        claim_text=c_text,
                        verification_status=c_status,
                        confidence=c_conf,
                        evidence_ids=c_evs,
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
        identity_map: Optional[Dict[str, Any]] = None,
        exit_qa: Optional[List[ExitInterviewQuestion]] = None,
    ) -> List[Dict[str, Any]]:
        """Assemble each of the 16 sections using multi-platform records, identity stitching, and atomic claim provenance."""
        ev_map = {e.id: e for e in evidences}
        ev_by_sr_id: Dict[str, List[str]] = {}
        for e in evidences:
            if e.source_record_id:
                ev_by_sr_id.setdefault(e.source_record_id, []).append(e.id)

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

        atomic_claims: Dict[int, List[Dict[str, Any]]] = {}

        def _add_claim(sec_num: int, claim_text: str, c_ev_ids: List[str], fallback_status: Optional[str] = None) -> None:
            valid_evs = [eid for eid in dict.fromkeys(c_ev_ids) if eid in ev_map][:8]
            if valid_evs:
                st, cnf = _sec_status(valid_evs, True)
            else:
                st = fallback_status or "Needs Human Verification"
                cnf = 0.35 if st != "Unknown / Missing Evidence" else 0.0
            atomic_claims.setdefault(sec_num, []).append({
                "claim_text": claim_text.strip()[:800],
                "evidence_ids": valid_evs,
                "confidence": round(min(0.99, max(0.0, cnf)), 2),
                "verification_status": st,
            })

        # Cross-platform identity resolution for departing member matching
        dep_canonical = (resolve_author_name(departing_name, identity_map) or departing_name).lower()
        dep_lower = departing_name.lower()

        def _matches_departing(raw_author: Optional[str]) -> bool:
            if not raw_author:
                return False
            raw_low = raw_author.lower()
            if dep_lower in raw_low or dep_canonical in raw_low:
                return True
            resolved = (resolve_author_name(raw_author, identity_map) or raw_author).lower()
            return resolved == dep_canonical or dep_lower in resolved

        dep_tasks = [t for t in tasks if _matches_departing(t.owner) or t.is_departing_owner]
        completed_tasks = [t for t in tasks if t.status == "completed"]
        open_tasks = [t for t in tasks if t.status != "completed"]

        # Multi-platform PR/MR & commit partitioning (GitHub + GitLab)
        merged_prs = [
            sr
            for sr in source_records
            if sr.source_type in ("github_pr", "gitlab_mr")
            and (
                (sr.metadata_json or {}).get("state") in ("merged", "closed")
                or bool((sr.metadata_json or {}).get("merged_at"))
            )
        ]
        open_prs = [
            sr
            for sr in source_records
            if sr.source_type in ("github_pr", "gitlab_mr")
            and (sr.metadata_json or {}).get("state") in ("open", "opened")
        ]
        commits = [sr for sr in source_records if sr.source_type in ("github_commit", "gitlab_commit")]

        entity_dicts = [{"id": e.id, "name": e.name, "entity_type": e.entity_type, "confidence": e.confidence} for e in entities]
        rel_dicts = [
            {
                "source_entity_id": r.source_entity_id,
                "target_entity_id": r.target_entity_id,
                "relation_type": r.relation_type,
                "confidence": r.confidence,
            }
            for r in relationships
        ]
        spofs = graph_service.detect_single_points_of_failure(entity_dicts, rel_dicts)

        proj_name = project.name if project else "Workspace Project"
        proj_desc = (project.description or "No project description recorded.") if project else ""

        # Map Exit Interview verified answers by target section
        qa_by_sec: Dict[int, List[ExitInterviewQuestion]] = {}
        for qa in exit_qa or []:
            if (qa.answer_text or "").strip():
                sec_no = int(qa.section_number or 2)
                qa_by_sec.setdefault(sec_no, []).append(qa)

        # Section 1: Project Overview (multi-platform priority evidence)
        s1_priority_types = (
            "document", "notion_page", "confluence_page", "github_pr", "gitlab_mr",
            "github_ast", "gitlab_ast", "jira_issue", "linear_issue", "exit_interview",
        )
        s1_evs = [e.id for e in evidences if e.source_type in s1_priority_types][:8]
        if not s1_evs and evidences:
            s1_evs = [e.id for e in evidences[:8]]
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

        # Section 2: Employee Responsibilities (identity-resolved across platforms)
        dep_resps = [r for r in responsibilities if _matches_departing(r.owner)]
        dep_authored_evs = [e for e in evidences if _matches_departing(e.source_author)]
        s2_evs = list(dict.fromkeys(_collect_ev_ids(dep_resps) + [e.id for e in dep_authored_evs[:8]]))
        s2_lines = []
        if dep_resps:
            s2_lines.append(f"Documented areas owned by **{departing_name}**:")
            for r in dep_resps:
                line = f"**{r.domain}** (Criticality: {r.criticality.upper()}): {r.scope} | Backup: {r.backup_owner or 'None assigned'}"
                s2_lines.append(f"- {line}")
                _add_claim(2, line, list(r.evidence_ids or []))
        if dep_authored_evs:
            s2_lines.append(f"\nAuthored/maintained source artifacts linked to **{departing_name}** ({len(dep_authored_evs)} found):")
            for e in dep_authored_evs[:8]:
                line = f"[{e.source_type}] {e.source_title}"
                s2_lines.append(f"- {line}")
                _add_claim(2, line, [e.id])
        if not s2_lines and not qa_by_sec.get(2):
            s2_lines.append(
                f"**Unknown / Missing Evidence:** No explicit responsibilities or authored records matched `{departing_name}` in current project sources. "
                "Human review required to confirm service ownership."
            )
        s2_status, s2_conf = _sec_status(s2_evs, bool(dep_resps or dep_authored_evs or qa_by_sec.get(2)))

        # Section 3: Completed Work (Tasks + Merged GitHub PRs / GitLab MRs + Commits)
        s3_evs = list(dict.fromkeys(_collect_ev_ids(completed_tasks) + [eid for pr in merged_prs for eid in ev_by_sr_id.get(pr.id, [])] + [eid for c in commits[:6] for eid in ev_by_sr_id.get(c.id, [])]))
        s3_lines = []
        for t in completed_tasks[:10]:
            line = f"**Task Completed:** {t.title} (Owner: {t.owner}) — {t.description or ''}"
            s3_lines.append(f"- {line}")
            _add_claim(3, line, list(t.evidence_ids or []))
        for pr in merged_prs[:10]:
            line = f"**Merged PR/MR:** [{pr.title}]({pr.url or '#'}) by {pr.author or 'contributor'}"
            s3_lines.append(f"- {line}")
            _add_claim(3, line, ev_by_sr_id.get(pr.id, []))
        for c in commits[:6]:
            if not merged_prs:
                line = f"**Commit:** {c.title} ({c.author or 'contributor'})"
                s3_lines.append(f"- {line}")
                _add_claim(3, line, ev_by_sr_id.get(c.id, []))
        if not s3_lines:
            s3_lines.append("**Unknown / Missing Evidence:** No completed tasks, merged PRs/MRs, or commits have been ingested yet.")
        s3_status, s3_conf = _sec_status(s3_evs, bool(completed_tasks or merged_prs or commits))

        # Section 4: Work in Progress (Open GitHub PRs / GitLab MRs + Active Tasks)
        wip_tasks = [t for t in tasks if t.status in ("in_progress", "blocked")]
        s4_evs = list(dict.fromkeys(_collect_ev_ids(wip_tasks) + [eid for pr in open_prs for eid in ev_by_sr_id.get(pr.id, [])]))
        s4_lines = []
        for pr in open_prs[:10]:
            line = f"**Open PR/MR:** [{pr.title}]({pr.url or '#'}) by {pr.author or 'contributor'}"
            s4_lines.append(f"- {line}")
            _add_claim(4, line, ev_by_sr_id.get(pr.id, []))
        for t in wip_tasks[:10]:
            line = f"**{t.status.upper()}:** {t.title} (Owner: {t.owner}) — {t.description or ''}"
            s4_lines.append(f"- {line}")
            _add_claim(4, line, list(t.evidence_ids or []))
        if not s4_lines:
            s4_lines.append("No open pull/merge requests or in-progress/blocked tasks currently recorded in ingested sources.")
        s4_status, s4_conf = _sec_status(s4_evs, bool(wip_tasks or open_prs))

        # Section 5: Unfinished Tasks & Reassignments
        s5_evs = _collect_ev_ids(open_tasks)
        s5_lines = []
        for t in open_tasks[:15]:
            sugg = t.suggested_reassignment or incoming_name
            line = (
                f"**{t.title}** | Priority: `{t.priority.upper()}` | Status: `{t.status}` | "
                f"Current Owner: {t.owner} → Suggested Successor: **{sugg}**"
                + (f" | Deadline: {t.deadline}" if t.deadline else "")
            )
            s5_lines.append(f"- {line}")
            _add_claim(5, line, list(t.evidence_ids or []))
        if not s5_lines:
            s5_lines.append("No unfinished tasks recorded in this project.")
        s5_status, s5_conf = _sec_status(s5_evs, bool(open_tasks))

        # Section 6: Important Technical Decisions
        s6_evs = _collect_ev_ids(decisions)
        s6_lines = []
        for d in decisions:
            line = f"**{d.title}** ({d.date}) — Decided by: {d.decision_maker} | Component: {d.component or 'General'} | Status: `{d.status}` — {d.summary}"
            s6_lines.append(
                f"- **{d.title}** ({d.date}) — Decided by: {d.decision_maker} | Component: {d.component or 'General'} | Status: `{d.status}`\n"
                f"  Summary: {d.summary}"
            )
            _add_claim(6, line, list(d.evidence_ids or []))
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
            _add_claim(7, f"{d.title} — Reasoning: {reasoning_text} | Trade-offs: {trds}", list(d.evidence_ids or []))
        if not s7_lines:
            s7_lines.append("**Unknown / Missing Evidence:** No decision rationale or rejected alternatives available in current evidence.")
        s7_status, s7_conf = _sec_status(s6_evs, bool(decisions))

        # Section 8: Technical Architecture & Components
        s8_evs = [e.evidence_id for e in tech_entities if e.evidence_id and e.evidence_id in ev_map]
        s8_lines = []
        if tech_entities:
            for e in tech_entities:
                line = f"**`{e.name}`** ({e.entity_type}): {e.description or 'Component in system graph.'}"
                s8_lines.append(f"- {line}")
                _add_claim(8, line, [e.evidence_id] if e.evidence_id else [])
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
            line = (
                f"`{dep.source_component}` → `{dep.target_component}` (`{dep.dependency_type}`, Criticality: `{dep.criticality.upper()}`): "
                f"{dep.description or 'Failure in target impacts source component.'}"
            )
            s9_lines.append(f"- {line}")
            _add_claim(9, line, list(dep.evidence_ids or []))
        if not s9_lines:
            s9_lines.append("**Unknown / Missing Evidence:** No component or external vendor dependencies mapped yet.")
        s9_status, s9_conf = _sec_status(s9_evs, bool(deps))

        # Section 10: Known Issues & Technical Quirks (GitHub + GitLab + Jira + Linear + Sentry + PagerDuty)
        quirk_risks = [r for r in risks if r.category in ("unresolved_bug", "technical_debt", "workaround", "technical_risk")]
        issue_types = ("github_issue", "gitlab_issue", "jira_issue", "linear_issue", "sentry_issue", "pagerduty_incident")
        issue_records = [sr for sr in source_records if sr.source_type in issue_types]
        s10_evs = list(dict.fromkeys(_collect_ev_ids(quirk_risks) + [eid for ir in issue_records for eid in ev_by_sr_id.get(ir.id, [])]))
        s10_lines = []
        for r in quirk_risks:
            line = f"**{r.title}** ({r.severity.upper()}): {r.description}" + (f" Workaround/Mitigation: {r.mitigation_strategy}" if r.mitigation_strategy else "")
            s10_lines.append(f"- {line}")
            _add_claim(10, line, list(r.evidence_ids or []))
        for ir in issue_records[:10]:
            line = f"**[{ir.source_type}]** [{ir.title}]({ir.url or '#'}) — {ir.content[:180]}"
            s10_lines.append(f"- {line}")
            _add_claim(10, line, ev_by_sr_id.get(ir.id, []))
        if not s10_lines:
            s10_lines.append("No known bugs, production incidents, or workarounds found in connected sources.")
        s10_status, s10_conf = _sec_status(s10_evs, bool(quirk_risks or issue_records))

        # Section 11: Risks & Single Points of Failure
        s11_evs = _collect_ev_ids(risks)
        s11_lines = []
        for r in risks:
            line = f"**{r.title}** | Severity: `{r.severity.upper()}` | Likelihood: `{r.likelihood.upper()}` — {r.description}"
            s11_lines.append(
                f"- **{r.title}** | Severity: `{r.severity.upper()}` | Likelihood: `{r.likelihood.upper()}`\n"
                f"  {r.description} | Mitigation: {r.mitigation_strategy or 'No mitigation documented'}"
            )
            _add_claim(11, line, list(r.evidence_ids or []))
        for sp in spofs:
            share_pct = round(float(sp.get("ownership_share", 1.0)) * 100)
            bf = sp.get("effective_bus_factor", 1.0)
            line = (
                f"**Single Point of Failure:** `{sp['component_name']}` ({sp['component_type']}) concentrates {share_pct}% ownership under "
                f"**{sp['sole_owner']}** (Bus Factor: {bf}, downstream blast radius: {sp['downstream_impact_count']} component(s))."
            )
            s11_lines.append(f"- {line}")
            _add_claim(11, line, s11_evs[:2], fallback_status="Needs Human Verification")
        if not s11_lines:
            s11_lines.append("No risks or single points of failure detected from current graph/risk register.")
        s11_status, s11_conf = _sec_status(s11_evs, bool(risks or spofs))

        # Section 12: Knowledge Gaps & Unresolved Questions
        s12_evs = _collect_ev_ids(gaps)
        s12_lines = []
        for g in gaps:
            line = (
                f"**{g.title}** (`{g.gap_type}`, Severity: `{g.severity.upper()}`, Status: `{g.status}`): "
                f"{g.description} | Impact: {g.impact} | Recommended Action: {g.recommended_action}"
            )
            s12_lines.append(f"- {line}")
            _add_claim(12, line, list(getattr(g, "evidence_ids", None) or []), fallback_status="Needs Human Verification")
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
            for list_key in ("repos", "projects", "channels", "targets"):
                val = cfg.get(list_key)
                if isinstance(val, list) and val:
                    return ", ".join(str(x) for x in val[:3])
            for scalar_key in (
                "repo", "project_path", "project_key", "space_key", "team_id",
                "organization", "project", "channel_id", "channel", "database_id",
                "page_id", "target", "workspace", "instance_url",
            ):
                val = cfg.get(scalar_key)
                if val:
                    return str(val)
            return integ.connected_account or "Connected Workspace"

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

        # Section 15: Recommended Day 1-30 Action Plan
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
            f"- Walk through open PRs/MRs ({len(open_prs)}) and active services ({len(tech_entities)} components mapped).\n\n"
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
            _add_claim(16, f"[{e.id[:8]}] {e.source_title} ({e.source_type}, SHA-256 {e.content_hash[:16]})", [e.id])
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
            (12, "Knowledge Gaps & Unresolved Questions", "\n".join(s12_lines), s12_evs, s12_status, s12_conf),
            (13, "Important Contacts & Subject Matter Experts", "\n".join(s13_lines), [], s13_status, s13_conf),
            (14, "Required Access & Permissions", s14_text, s1_evs, s14_status, s14_conf),
            (15, "Recommended Day 1–30 Action Plan", s15_text, s5_evs or s1_evs, s15_status, s15_conf),
            (16, "Evidence References & Audit Trail", "\n".join(s16_lines), s16_evs, s16_status, s16_conf),
        ]

        results: List[Dict[str, Any]] = []
        for sec_num, sec_title, content, sec_evs, sec_status, sec_conf in raw_sections:
            # Append Exit Interview verified clarifications targeting this section
            sec_qas = qa_by_sec.get(sec_num) or []
            if sec_qas:
                qa_lines = ["\n\n**Verified Exit Interview Clarifications:**"]
                for qa in sec_qas:
                    ans = (qa.answer_text or "").strip()
                    qa_lines.append(f"- **Q:** {qa.question_text}\n  **A:** {ans}")
                    c_evs = [qa.evidence_id] if qa.evidence_id and qa.evidence_id in ev_map else []
                    _add_claim(sec_num, f"Exit Interview Clarification: {qa.question_text} -> {ans}", c_evs, fallback_status="Supported by Evidence")
                    if c_evs and qa.evidence_id not in sec_evs:
                        sec_evs = list(sec_evs) + [qa.evidence_id]
                content = content + "\n".join(qa_lines)
                if sec_status == "Unknown / Missing Evidence":
                    sec_status, sec_conf = _sec_status(sec_evs, True)

            spec_claims = atomic_claims.get(sec_num)
            if spec_claims:
                claims: List[Any] = spec_claims[:10]
            else:
                bullet_claims = [
                    re.sub(r"^-\s*(\[[ xX]\]\s*)?", "", ln.strip()).strip()
                    for ln in content.splitlines()
                    if ln.strip().startswith("- ")
                ]
                raw_claims = bullet_claims[:6] if bullet_claims else [ln.strip() for ln in content.splitlines() if ln.strip()][:6]
                if not raw_claims and content.strip():
                    raw_claims = [content.strip()]
                claims = [
                    {
                        "claim_text": c[:800],
                        "evidence_ids": sec_evs[:5],
                        "confidence": round(min(0.99, max(0.0, sec_conf)), 2),
                        "verification_status": sec_status,
                    }
                    for c in raw_claims
                ]

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

    def delta_sync_handover(
        self,
        db: Session,
        handover: Handover,
        actor_user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Incrementally refresh unverified/drifted handover sections while preserving reviewer-verified sections."""
        project_id = handover.project_id
        project = db.query(Project).filter(Project.id == project_id).first()
        integrations = db.query(Integration).filter(Integration.project_id == project_id).all()
        all_source_records = db.query(SourceRecord).filter(SourceRecord.project_id == project_id).all()
        all_documents = db.query(Document).filter(Document.project_id == project_id).all()
        all_evidences = db.query(Evidence).filter(Evidence.project_id == project_id).all()

        evidences, source_records, documents = self._filter_by_selected_sources(
            handover.selected_sources or [],
            all_evidences,
            all_source_records,
            all_documents,
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

        if handover.selected_sources:
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

        identity_map = build_project_identity_map(project_id, db)
        exit_qa = (
            db.query(ExitInterviewQuestion)
            .filter(ExitInterviewQuestion.handover_id == handover.id, ExitInterviewQuestion.status == "answered")
            .all()
        )
        fresh_specs = self._build_16_sections(
            project=project,
            departing_name=handover.departing_employee_name,
            departing_role=handover.departing_employee_role,
            incoming_name=handover.incoming_employee_name,
            incoming_role=handover.incoming_employee_role,
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
            identity_map=identity_map,
            exit_qa=exit_qa,
        )
        fresh_by_num = {s["section_number"]: s for s in fresh_specs}

        existing_secs = (
            db.query(HandoverSection)
            .filter(HandoverSection.handover_id == handover.id)
            .order_by(HandoverSection.section_number.asc())
            .all()
        )
        preserved_sections: List[int] = []
        updated_sections: List[int] = []
        replaced_claim_ids: List[str] = []
        prev_confidence = float(handover.overall_confidence or 0.0)

        for sec in existing_secs:
            spec = fresh_by_num.get(sec.section_number)
            if not spec:
                continue
            # Preserve reviewer-verified sections strictly intact unless contradicted claims live inside
            contradicted_in_sec = (
                db.query(HandoverClaim)
                .filter(HandoverClaim.section_id == sec.id, HandoverClaim.verification_status == "Contradicted")
                .count()
            )
            is_locked_verified = bool(sec.is_verified or sec.verification_status == "Verified by Reviewer")
            if is_locked_verified and contradicted_in_sec == 0:
                preserved_sections.append(sec.section_number)
                continue

            sec.content = spec["content"]
            sec.evidence_ids = spec["evidence_ids"]
            sec.verification_status = spec["verification_status"]
            sec.confidence = spec["confidence"]
            sec.is_verified = False

            old_claim_ids = [
                c_id for (c_id,) in db.query(HandoverClaim.id).filter(HandoverClaim.section_id == sec.id).all()
            ]
            replaced_claim_ids.extend(old_claim_ids)
            db.query(HandoverClaim).filter(HandoverClaim.section_id == sec.id).delete(synchronize_session=False)
            for claim_item in spec["claims"]:
                db.add(
                    HandoverClaim(
                        handover_id=handover.id,
                        section_id=sec.id,
                        claim_text=claim_item["claim_text"],
                        verification_status=claim_item["verification_status"],
                        confidence=claim_item["confidence"],
                        evidence_ids=claim_item["evidence_ids"],
                    )
                )
            updated_sections.append(sec.section_number)

        db.flush()
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
        new_conf, new_breakdown = ai_engine.compute_explainable_confidence(ev_docs_for_conf)
        handover.overall_confidence = new_conf
        handover.confidence_breakdown = new_breakdown

        resolved_drift_events = 0
        if replaced_claim_ids:
            open_claim_drifts = (
                db.query(KnowledgeDriftEvent)
                .filter(
                    KnowledgeDriftEvent.project_id == handover.project_id,
                    KnowledgeDriftEvent.target_entity_type == "handover_claim",
                    KnowledgeDriftEvent.target_entity_id.in_(replaced_claim_ids),
                    KnowledgeDriftEvent.status.in_(["open", "acknowledged"]),
                )
                .all()
            )
            now_dt = datetime.now(timezone.utc)
            for dr in open_claim_drifts:
                dr.status = "resolved"
                dr.resolved_by_user_id = actor_user_id
                dr.resolved_at = now_dt
                resolved_drift_events += 1

        prev_stats = dict(handover.reconstruction_stats or {})
        cleared_warnings = max(int(prev_stats.get("drift_invalidated_claims") or 0), resolved_drift_events)
        remaining_contradicted = (
            db.query(HandoverClaim)
            .filter(HandoverClaim.handover_id == handover.id, HandoverClaim.verification_status == "Contradicted")
            .count()
        )
        prev_stats.update({
            "decisions_analyzed": len(decisions),
            "tasks_extracted": len(tasks),
            "risks_identified": len(risks),
            "gaps_detected": len(gaps),
            "dependencies_mapped": len(deps),
            "entities_graphed": len(entities),
            "source_records_used": len(source_records),
            "documents_used": len(documents),
            "evidences_grounded": len(evidences),
            "drift_invalidated_claims": remaining_contradicted,
            "has_drift_warning": remaining_contradicted > 0,
            "last_delta_sync_at": datetime.now(timezone.utc).isoformat(),
        })
        handover.reconstruction_stats = prev_stats

        v_count = db.query(HandoverVersion).filter(HandoverVersion.handover_id == handover.id).count()
        version_num = v_count + 1
        summary_msg = (
            f"Delta sync refreshed {len(updated_sections)} section(s) while preserving "
            f"{len(preserved_sections)} verified section(s)."
        )
        db.add(
            HandoverVersion(
                handover_id=handover.id,
                version_number=version_num,
                user_id=actor_user_id,
                changed_section=f"Delta Sync ({len(updated_sections)} updated)",
                changelog=summary_msg,
                reason="Living Dossier Delta Sync",
                snapshot={
                    "preserved_sections": preserved_sections,
                    "updated_sections": updated_sections,
                    "previous_confidence": prev_confidence,
                    "new_confidence": new_conf,
                },
                created_by="TEAM OBSIDIAN Delta Sync",
            )
        )
        record_activity(
            db=db,
            action="handover.delta_synced",
            entity_type="handover",
            entity_id=handover.id,
            user_id=actor_user_id,
            project_id=project_id,
            details={"message": summary_msg, "updated_sections": updated_sections},
        )
        db.commit()
        db.refresh(handover)

        return {
            "handover_id": handover.id,
            "version_number": version_num,
            "preserved_sections": preserved_sections,
            "updated_sections": updated_sections,
            "previous_confidence": prev_confidence,
            "new_confidence": new_conf,
            "drift_warnings_cleared": cleared_warnings,
            "summary": summary_msg,
        }


handover_engine = HandoverEngine()
