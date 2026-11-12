import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.handover import Handover, ReadinessSimulation
from app.models.knowledge import (
    Decision,
    Dependency,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    RiskItem,
)
from app.models.workspace import Project
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity
from app.services.graph_service import GraphService

logger = logging.getLogger("team_obsidian.simulator")


class ScenarioSpec(BaseModel):
    id: str
    title: str
    category: str  # spof_incident, adr_tradeoff, dependency_outage
    severity: str = "high"
    prompt: str
    expected_concepts: List[str] = Field(default_factory=list)
    reference_hint: str = ""


class ScenarioBundle(BaseModel):
    scenarios: List[ScenarioSpec] = Field(default_factory=list)


class ScenarioGrade(BaseModel):
    scenario_id: str
    score: float
    strengths: List[str] = Field(default_factory=list)
    missed_concepts: List[str] = Field(default_factory=list)
    feedback: str


class SimulationEvaluationBundle(BaseModel):
    overall_feedback: str
    grades: List[ScenarioGrade] = Field(default_factory=list)


def _gather_project_context(db: Session, handover: Handover) -> Dict[str, Any]:
    pid = handover.project_id
    proj = db.query(Project).filter(Project.id == pid).first()
    decisions = db.query(Decision).filter(Decision.project_id == pid).limit(8).all()
    risks = db.query(RiskItem).filter(RiskItem.project_id == pid).limit(8).all()
    deps = db.query(Dependency).filter(Dependency.project_id == pid).limit(10).all()
    gaps = db.query(KnowledgeGap).filter(KnowledgeGap.project_id == pid).limit(6).all()

    entities = db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == pid).all()
    relationships = db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == pid).all()
    ent_dicts = [
        {
            "id": e.id,
            "name": e.name,
            "entity_type": e.entity_type,
            "confidence": e.confidence,
            "properties": e.properties or {},
        }
        for e in entities
    ]
    rel_dicts = [
        {
            "id": r.id,
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
            "context": r.context,
            "confidence": r.confidence,
        }
        for r in relationships
    ]
    ent_name_by_id = {e["id"]: e["name"] for e in ent_dicts}

    graph_svc = GraphService()
    graph = graph_svc.build_graph(ent_dicts, rel_dicts)
    raw_spofs = graph_svc.detect_single_points_of_failure(ent_dicts, rel_dicts)[:5]
    spofs = []
    for sp in raw_spofs:
        cid = sp.get("component_id")
        downstream_ids = graph_svc.calculate_blast_radius(graph, cid) if cid else []
        spofs.append({
            **sp,
            "name": sp.get("component_name") or "Core Component",
            "downstream_blast_radius": sp.get("downstream_impact_count", len(downstream_ids)),
            "affected_downstream": [ent_name_by_id.get(did, did) for did in downstream_ids[:6]],
        })

    return {
        "project_name": proj.name if proj else "Project",
        "decisions": decisions,
        "risks": risks,
        "dependencies": deps,
        "gaps": gaps,
        "spofs": spofs,
    }


def generate_scenarios_for_handover(db: Session, handover: Handover) -> List[Dict[str, Any]]:
    """Generate 3 project-grounded incident & architecture readiness scenarios for the incoming engineer."""
    ctx = _gather_project_context(db, handover)
    spofs = ctx["spofs"]
    decisions = ctx["decisions"]
    risks = ctx["risks"]
    deps = ctx["dependencies"]

    summary_lines = [
        f"Project: {ctx['project_name']}",
        f"Handover: {handover.departing_employee_name} ({handover.departing_employee_role}) -> {handover.incoming_employee_name} ({handover.incoming_employee_role})",
        "SPOFs: " + (", ".join(f"{s['name']} (blast={s.get('downstream_blast_radius', 0)})" for s in spofs) or "None mapped yet"),
        "Key Decisions: " + ("; ".join(f"{d.title} [{d.component or 'core'}]: {d.summary[:120]}" for d in decisions[:4]) or "None"),
        "Key Risks: " + ("; ".join(f"{r.title} (mitigation: {(r.mitigation_strategy or 'open')[:90]})" for r in risks[:4]) or "None"),
        "Dependencies: " + (", ".join(f"{d.source_component} -> {d.target_component}" for d in deps[:6]) or "None"),
    ]

    client = ai_engine._get_client()
    if client is not None and (spofs or decisions or risks or deps):
        try:
            from google.genai import types

            prompt = (
                "Generate exactly 3 realistic engineering handover readiness simulation scenarios grounded ONLY in the project facts below.\n"
                "Each scenario must test whether the incoming engineer understands critical SPOFs, architectural trade-offs (ADRs), or failure blast radius.\n"
                "Do not invent unrelated infrastructure. Provide 3-5 concrete expected_concepts keywords per scenario.\n\n"
                + "\n".join(summary_lines)
            )
            resp, _ = ai_engine._generate_content_with_fallback(
                client,
                ai_engine.secondary_model_name,
                prompt,
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ScenarioBundle,
                    temperature=0.2,
                ),
            )
            parsed = ScenarioBundle.model_validate_json(resp.text)
            if parsed.scenarios:
                return [s.model_dump() for s in parsed.scenarios[:3]]
        except Exception as exc:
            logger.warning("Gemini scenario generation fallback: %s", str(exc)[:140])

    # Deterministic project-grounded scenarios
    scenarios: List[Dict[str, Any]] = []

    if spofs:
        top_spof = spofs[0]
        downstream = top_spof.get("affected_downstream") or []
        concepts = [top_spof["name"], "rollback", "blast radius"] + downstream[:3]
        scenarios.append({
            "id": "scenario-spof",
            "title": f"Critical Outage Response: {top_spof['name']} Degradation",
            "category": "spof_incident",
            "severity": "critical",
            "prompt": (
                f"During peak traffic, monitoring flags high error rates on single-point-of-failure '{top_spof['name']}' "
                f"(downstream blast radius: {top_spof.get('downstream_blast_radius', 0)} components). "
                "Walk through your immediate triage steps, affected downstream services, and safe recovery / rollback strategy."
            ),
            "expected_concepts": [c for c in concepts if c][:5],
            "reference_hint": f"Key node: {top_spof['name']}; affected downstream: {', '.join(downstream[:4]) or 'core consumers'}.",
        })
    elif risks:
        r0 = risks[0]
        concepts = [w for w in re.findall(r"[A-Za-z0-9_-]{4,}", f"{r0.title} {r0.mitigation_strategy or ''}")[:5]]
        scenarios.append({
            "id": "scenario-risk",
            "title": f"Operational Risk Triggered: {r0.title[:80]}",
            "category": "spof_incident",
            "severity": r0.severity or "high",
            "prompt": (
                f"Risk '{r0.title}' ({r0.severity}) manifests in production: {r0.description[:220]}. "
                "How do you contain the blast radius, apply the documented mitigation, and verify recovery?"
            ),
            "expected_concepts": concepts or ["triage", "mitigation", "rollback"],
            "reference_hint": (r0.mitigation_strategy or r0.description)[:200],
        })
    else:
        scenarios.append({
            "id": "scenario-core-triage",
            "title": "First-Week On-Call Incident Triage",
            "category": "spof_incident",
            "severity": "high",
            "prompt": (
                f"As {handover.incoming_employee_role} stepping in for {handover.departing_employee_name}, "
                f"describe your step-by-step triage plan if the core deployment of '{ctx['project_name']}' stops processing requests."
            ),
            "expected_concepts": ["logs", "health", "rollback", "dependencies"],
            "reference_hint": "Verify logs, health checks, recent changes, downstream dependencies, and safe rollback.",
        })

    if decisions:
        d0 = decisions[0]
        concepts = [w for w in re.findall(r"[A-Za-z0-9_-]{4,}", f"{d0.title} {d0.component or ''} {d0.reasoning[:120]}")[:5]]
        scenarios.append({
            "id": "scenario-adr",
            "title": f"Architecture Trade-off Review: {d0.title[:80]}",
            "category": "adr_tradeoff",
            "severity": "high",
            "prompt": (
                f"A teammate proposes reversing ADR '{d0.title}' ({d0.component or 'core architecture'}). "
                "Explain why the original choice was made, its key trade-offs, and what constraints must hold before changing it."
            ),
            "expected_concepts": concepts or ["tradeoff", "constraint", "evidence"],
            "reference_hint": f"Original rationale: {d0.reasoning[:220]}",
        })
    else:
        scenarios.append({
            "id": "scenario-adr-governance",
            "title": "Architectural Decision Governance",
            "category": "adr_tradeoff",
            "severity": "medium",
            "prompt": (
                f"Before altering core components in '{ctx['project_name']}', how do you verify prior constraints, "
                "document new trade-offs, and prevent knowledge drift across teams?"
            ),
            "expected_concepts": ["decision", "evidence", "verification", "stakeholders"],
            "reference_hint": "Audit prior ADRs, verify supporting evidence, run drift checks, and get peer review.",
        })

    if deps:
        dp = deps[0]
        scenarios.append({
            "id": "scenario-dep",
            "title": f"Dependency Chain Failure: {dp.source_component} -> {dp.target_component}",
            "category": "dependency_outage",
            "severity": "high",
            "prompt": (
                f"Upstream dependency '{dp.target_component}' begins timing out for '{dp.source_component}'. "
                "Explain the impact path, ownership escalation route, and graceful degradation checks."
            ),
            "expected_concepts": [dp.source_component, dp.target_component, "timeout", "fallback", dp.owner or "owner"],
            "reference_hint": f"{dp.description or ''} (Owner: {dp.owner or 'check directory'})",
        })
    else:
        scenarios.append({
            "id": "scenario-gap-closure",
            "title": "Closing Unverified Handover Knowledge Gaps",
            "category": "dependency_outage",
            "severity": "medium",
            "prompt": (
                f"While shadowing {handover.departing_employee_name}, you spot an undocumented runbook or missing backup owner. "
                "What verification evidence must you capture before approving final handover sign-off?"
            ),
            "expected_concepts": ["runbook", "evidence", "owner", "verification"],
            "reference_hint": "Capture reproducible runbook steps, link SHA-256 evidence, assign backup owner, and verify claims.",
        })

    return scenarios[:3]


def evaluate_simulation_submission(
    db: Session,
    handover: Handover,
    candidate_name: str,
    user_id: Optional[str],
    scenarios: List[Dict[str, Any]],
    answers: Dict[str, str],
) -> ReadinessSimulation:
    """Grade incoming successor responses quantitatively (0-100%) with AI + deterministic concept rubric."""
    eval_items = []
    for sc in scenarios:
        sc_id = str(sc.get("id"))
        ans = (answers.get(sc_id) or "").strip()
        eval_items.append({
            "scenario_id": sc_id,
            "title": sc.get("title", ""),
            "prompt": sc.get("prompt", ""),
            "expected_concepts": sc.get("expected_concepts") or [],
            "reference_hint": sc.get("reference_hint", ""),
            "candidate_answer": ans,
        })

    graded_map: Dict[str, ScenarioGrade] = {}
    overall_feedback = ""

    client = ai_engine._get_client()
    if client is not None and any(it["candidate_answer"] for it in eval_items):
        try:
            from google.genai import types

            prompt_body = "\n\n".join(
                f"Scenario ID: {it['scenario_id']}\nTitle: {it['title']}\nPrompt: {it['prompt']}\n"
                f"Reference Hint: {it['reference_hint']}\nExpected Concepts: {', '.join(it['expected_concepts'])}\n"
                f"Candidate Response: {it['candidate_answer'] or '(no answer provided)'}"
                for it in eval_items
            )
            prompt = (
                "You are grading an engineering handover readiness simulation. Score each scenario 0 to 100.\n"
                "Be strict and accurate: blank or vague one-word answers score <= 25; answers demonstrating triage steps, "
                "affected components/blast radius, ADR constraints, and mitigation score 75-100.\n\n"
                + prompt_body
            )
            resp, _ = ai_engine._generate_content_with_fallback(
                client,
                ai_engine.secondary_model_name,
                prompt,
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SimulationEvaluationBundle,
                    temperature=0.1,
                ),
            )
            parsed = SimulationEvaluationBundle.model_validate_json(resp.text)
            overall_feedback = parsed.overall_feedback
            for g in parsed.grades:
                graded_map[str(g.scenario_id).strip()] = g
        except Exception as exc:
            logger.warning("Gemini simulation grading fallback: %s", str(exc)[:140])

    # Deterministic + AI blended rubric scoring
    responses_out: List[Dict[str, Any]] = []
    total_score = 0.0
    for it in eval_items:
        sc_id = it["scenario_id"]
        ans = it["candidate_answer"]
        expected = [str(c) for c in it["expected_concepts"] if c]
        lower_ans = ans.lower()
        words = re.findall(r"[A-Za-z0-9_-]{3,}", lower_ans)
        matched = [c for c in expected if c.lower() in lower_ans]
        missed = [c for c in expected if c.lower() not in lower_ans]
        concept_ratio = (len(matched) / max(1, len(expected))) if expected else 0.5

        if sc_id in graded_map:
            g = graded_map[sc_id]
            score = max(0.0, min(100.0, float(g.score)))
            if len(words) >= 20 and expected and concept_ratio >= 0.75:
                # Anchor AI rubric so substantive answers covering expected concepts are not penalized by variance
                score = max(score, round(min(92.0, 40.0 + concept_ratio * 42.0 + min(15.0, len(words) * 0.25)), 1))
            responses_out.append({
                "scenario_id": sc_id,
                "title": it["title"],
                "answer": ans,
                "score": round(score, 1),
                "strengths": g.strengths,
                "missed_concepts": g.missed_concepts,
                "feedback": g.feedback,
            })
        else:
            if not ans:
                score = 0.0
                fb = "No response submitted."
            else:
                depth_bonus = min(40.0, len(words) * 1.4)
                score = min(100.0, round(20.0 + concept_ratio * 45.0 + depth_bonus, 1))
                fb = (
                    f"Matched {len(matched)}/{len(expected)} expected architecture concepts."
                    + (f" Consider covering: {', '.join(missed[:3])}." if missed else " Solid operational coverage.")
                )
            responses_out.append({
                "scenario_id": sc_id,
                "title": it["title"],
                "answer": ans,
                "score": score,
                "strengths": [f"Addressed '{m}'" for m in matched] if matched else (["Provided structured operational response"] if len(words) >= 12 else []),
                "missed_concepts": missed,
                "feedback": fb,
            })
        total_score += responses_out[-1]["score"]

    avg_score = round(total_score / max(1, len(responses_out)), 1)
    passed = avg_score >= 70.0
    if not overall_feedback:
        overall_feedback = (
            f"{candidate_name} achieved {avg_score}% readiness "
            f"({'PASSED readiness threshold >= 70%' if passed else 'NEEDS ADDITIONAL REVIEW (< 70% threshold)'})."
        )

    sim = ReadinessSimulation(
        handover_id=handover.id,
        project_id=handover.project_id,
        user_id=user_id,
        candidate_name=candidate_name,
        overall_score=avg_score,
        passed=passed,
        scenarios_json=scenarios,
        responses_json=responses_out,
        summary_feedback=overall_feedback,
    )
    db.add(sim)

    stats = dict(handover.reconstruction_stats or {})
    stats["latest_readiness_score"] = avg_score
    stats["readiness_passed"] = passed
    stats["latest_simulation_at"] = sim.created_at.isoformat() if sim.created_at else None
    handover.reconstruction_stats = stats

    record_activity(
        db=db,
        action="handover.readiness_simulated",
        entity_type="handover",
        entity_id=handover.id,
        user_id=user_id,
        project_id=handover.project_id,
        details={
            "message": f"Readiness simulation scored {avg_score}% ({'PASSED' if passed else 'NEEDS REVIEW'}) for {candidate_name}",
        },
    )
    db.commit()
    db.refresh(sim)
    return sim

