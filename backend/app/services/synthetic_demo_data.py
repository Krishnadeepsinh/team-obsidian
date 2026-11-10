"""Explicitly invoked isolated demonstration workspace seeder (E-Commerce Platform scenario).

Never called automatically during user registration or login. Only creates a clearly
flagged demo workspace (is_demo=True) owned by the requesting user when explicitly invoked.
"""
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.evidence import Evidence
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
from app.models.workspace import Organization, Project, ProjectMember, User, Workspace
from app.services.ai_engine import ai_engine
from app.services.handover_engine import handover_engine


def seed_synthetic_demo_data(db: Session, owner_user: Optional[User] = None) -> dict:
    if not owner_user:
        return {"message": "Authenticated user required to initialize an isolated demo workspace."}

    existing_demo = (
        db.query(Project)
        .filter(Project.creator_id == owner_user.id, Project.is_demo == True)  # noqa: E712
        .first()
    )
    if existing_demo:
        return {
            "status": "already_exists",
            "message": "Isolated Demo Workspace (E-Commerce Platform) already initialized for your account.",
            "project_id": existing_demo.id,
        }

    org_id = owner_user.org_id
    if not org_id:
        org = Organization(
            name=f"{owner_user.name}'s Demo Org",
            slug=f"demo-org-{uuid.uuid4().hex[:6]}",
            owner_id=owner_user.id,
            is_personal=False,
        )
        db.add(org)
        db.flush()
        org_id = org.id

    demo_ws = Workspace(
        org_id=org_id,
        name="Demo Workspace — E-Commerce Platform",
        slug=f"demo-ecom-{uuid.uuid4().hex[:6]}",
        description="Isolated demonstration scenario: Rahul Sharma → Alex Vance",
        owner_id=owner_user.id,
        is_personal=False,
    )
    db.add(demo_ws)
    db.flush()

    proj = Project(
        workspace_id=demo_ws.id,
        creator_id=owner_user.id,
        name="Demo: E-Commerce Platform",
        slug=f"demo-ecommerce-{uuid.uuid4().hex[:6]}",
        description="Demonstration project showcasing payment gateway integration, checkout microservices, Redis locking, and database partitioning.",
        status="transitioning",
        priority="critical",
        tags=["Demo", "E-Commerce", "FastAPI", "PostgreSQL"],
        is_demo=True,
        target_handover_date="2026-11-30",
    )
    db.add(proj)
    db.flush()

    db.add(
        ProjectMember(
            project_id=proj.id,
            user_id=owner_user.id,
            project_role="project_owner",
            status="active",
        )
    )

    demo_integ = Integration(
        project_id=proj.id,
        user_id=owner_user.id,
        provider="manual",
        name="Demo GitHub & Slack Archive",
        status="connected",
        auth_type="demo_snapshot",
        auth_status="unverified",
        connected_account="demo/ecommerce-platform",
        config={"repo": "demo/ecommerce-platform"},
        items_synced=4,
    )
    db.add(demo_integ)
    db.flush()

    demo_records = [
        (
            "github_pr",
            "demo-pr-128",
            "PR #128: Webhook Idempotency & Redis Distributed Locking",
            "Rahul Sharma",
            "https://github.com/example/ecommerce/pull/128",
            "Implemented Redlock-based distributed mutex (5000ms TTL) and HMAC-SHA256 webhook verification in Payment Service to prevent duplicate order capture.",
        ),
        (
            "slack_thread",
            "demo-slack-razorpay",
            "Slack #payments-arch: Razorpay Selection over Stripe",
            "Rahul Sharma",
            "https://slack.com/archives/C_DEMO/p17000001",
            "Thread consensus with Amit Verma (Tech Lead): Selected Razorpay for native UPI Autopay and lower domestic transaction fees (1.8% vs 2.9%). Stripe rejected for Phase 1 domestic rail coverage.",
        ),
        (
            "github_pr",
            "demo-pr-142",
            "PR #142: Monthly PostgreSQL Table Partitioning for Orders",
            "Rahul Sharma",
            "https://github.com/example/ecommerce/pull/142",
            "In-progress zero-downtime monthly range partitioning on orders(created_at) across 42M rows using dual-write shadow triggers.",
        ),
        (
            "github_issue",
            "demo-issue-89",
            "Issue #89: Floating-Point Currency Rounding Discrepancy",
            "Neha Sharma",
            "https://github.com/example/ecommerce/issues/89",
            "QA flagged intermittent 1-paisa rounding mismatch in multi-item discount checkout; temporary workaround truncates after tax aggregation.",
        ),
    ]

    ev_ids = []
    for stype, ext_id, title, author, url, content in demo_records:
        sha = hashlib.sha256(content.encode()).hexdigest()
        sr = SourceRecord(
            integration_id=demo_integ.id,
            project_id=proj.id,
            source_type=stype,
            external_id=ext_id,
            title=title,
            author=author,
            url=url,
            content=content,
            sha256_hash=sha,
            source_timestamp=datetime.now(timezone.utc),
        )
        db.add(sr)
        db.flush()
        ev = Evidence(
            project_id=proj.id,
            source_record_id=sr.id,
            source_type=stype,
            source_id=sr.id,
            source_title=title,
            source_url=url,
            source_author=author,
            excerpt=content,
            ai_interpretation=f"Demonstration source record authored by {author}.",
            confidence=0.92,
            verification_status="Supported by Evidence",
            content_hash=sha,
        )
        db.add(ev)
        db.flush()
        ev_ids.append(ev.id)

    db.add(
        Decision(
            project_id=proj.id,
            created_by_user_id=owner_user.id,
            title="Select Razorpay as Primary Domestic Payment Gateway",
            summary="Adopted Razorpay for domestic UPI, card, and netbanking checkout orchestration.",
            reasoning="Native UPI Autopay support and 1.8% domestic fee structure compared to Stripe.",
            decision_maker="Rahul Sharma & Amit Verma",
            date="2026-09-14",
            component="Payment Service",
            alternatives=["Stripe", "Adyen"],
            tradeoffs=["India-first settlement coupling; cross-border requires secondary adapter"],
            consequences=["Requires HMAC-SHA256 webhook signature verification and Redis idempotency keys"],
            verification_status="Supported by Evidence",
            confidence=0.91,
            evidence_ids=[ev_ids[1]],
        )
    )
    db.add(
        TaskItem(
            project_id=proj.id,
            created_by_user_id=owner_user.id,
            title="Complete PR #142 Orders Table Partition Cutover",
            description="Validate dual-write trigger lag and execute final table swap in staging.",
            owner="Rahul Sharma",
            priority="critical",
            status="in_progress",
            deadline="2026-11-25",
            is_departing_owner=True,
            suggested_reassignment="Alex Vance",
            verification_status="Supported by Evidence",
            confidence=0.9,
            evidence_ids=[ev_ids[2]],
        )
    )
    db.add(
        RiskItem(
            project_id=proj.id,
            created_by_user_id=owner_user.id,
            title="Single Point of Failure on Payment Adapter Ownership",
            description="Only Rahul Sharma maintains Razorpay webhook retry and idempotency tuning.",
            category="single_point_of_failure",
            severity="critical",
            likelihood="high",
            owner="Rahul Sharma",
            mitigation_strategy="Pair Alex Vance on webhook reconciliation runbook before cutover.",
            related_components=["Payment Service", "Razorpay Gateway"],
            verification_status="Supported by Evidence",
            evidence_ids=[ev_ids[0]],
        )
    )
    db.add(
        Dependency(
            project_id=proj.id,
            source_component="Checkout Service",
            target_component="Payment Service",
            dependency_type="hard_blocker",
            description="Synchronous payment intent creation and order confirmation.",
            owner="Rahul Sharma",
            criticality="critical",
            verification_status="Supported by Evidence",
            evidence_ids=[ev_ids[0]],
        )
    )
    db.add(
        Dependency(
            project_id=proj.id,
            source_component="Payment Service",
            target_component="Redis Cache",
            dependency_type="hard_blocker",
            description="Redlock distributed lock and 24h webhook idempotency cache.",
            owner="Rahul Sharma",
            criticality="critical",
            verification_status="Supported by Evidence",
            evidence_ids=[ev_ids[0]],
        )
    )
    db.add(
        Responsibility(
            project_id=proj.id,
            owner="Rahul Sharma",
            domain="Payment Gateway & Checkout Microservices",
            scope="Razorpay adapter, webhook processing, Redis distributed locks, Orders partitioning.",
            criticality="critical",
            backup_owner="Alex Vance",
            verification_status="Supported by Evidence",
            evidence_ids=[ev_ids[0], ev_ids[2]],
        )
    )
    db.add(
        KnowledgeGap(
            project_id=proj.id,
            title="Missing Redis Cluster Failover Runbook",
            description="No documented procedure for manual Redis primary promotion during AZ outage.",
            gap_type="missing_runbook",
            severity="high",
            priority="high",
            impact="Checkout locks fail if Redis master becomes unreachable.",
            business_impact="Blocked order placement during cache outage.",
            technical_impact="Redlock timeouts across checkout pods.",
            recommended_action="Document Sentinel/Cluster failover steps with Rahul Sharma before departure.",
        )
    )

    # Graph entities & relationships matching scenario
    e_rahul = KnowledgeEntity(project_id=proj.id, entity_type="Person", name="Rahul Sharma", description="Departing Senior Backend Developer", confidence=0.95, evidence_id=ev_ids[0])
    e_pay = KnowledgeEntity(project_id=proj.id, entity_type="Service", name="Payment Service", description="Handles payment intents & Razorpay webhooks", confidence=0.94, evidence_id=ev_ids[0])
    e_redis = KnowledgeEntity(project_id=proj.id, entity_type="Infrastructure", name="Redis Cache", description="Distributed locks & idempotency store", confidence=0.92, evidence_id=ev_ids[0])
    e_chk = KnowledgeEntity(project_id=proj.id, entity_type="Service", name="Checkout Service", description="Orchestrates cart-to-order settlement", confidence=0.93, evidence_id=ev_ids[2])
    e_rzp = KnowledgeEntity(project_id=proj.id, entity_type="Vendor", name="Razorpay Gateway", description="Primary domestic payment processor", confidence=0.95, evidence_id=ev_ids[1])
    db.add_all([e_rahul, e_pay, e_redis, e_chk, e_rzp])
    db.flush()

    db.add_all([
        KnowledgeRelationship(project_id=proj.id, source_entity_id=e_rahul.id, target_entity_id=e_pay.id, relation_type="owns", confidence=0.95, evidence_id=ev_ids[0]),
        KnowledgeRelationship(project_id=proj.id, source_entity_id=e_pay.id, target_entity_id=e_redis.id, relation_type="depends_on", confidence=0.92, evidence_id=ev_ids[0]),
        KnowledgeRelationship(project_id=proj.id, source_entity_id=e_chk.id, target_entity_id=e_pay.id, relation_type="uses", confidence=0.93, evidence_id=ev_ids[0]),
        KnowledgeRelationship(project_id=proj.id, source_entity_id=e_pay.id, target_entity_id=e_rzp.id, relation_type="uses", confidence=0.95, evidence_id=ev_ids[1]),
    ])
    db.commit()

    # Generate demo handover with realistic demo stakeholder approvers
    handover_engine.reconstruct_and_generate(
        db=db,
        project_id=proj.id,
        departing_name="Rahul Sharma",
        departing_role="Senior Backend Developer",
        incoming_name="Alex Vance",
        incoming_role="Staff Software Engineer",
        source_ids=[],
        categories=["Architecture", "Decisions", "Tasks", "Risks", "Gaps"],
        target_date="2026-11-30",
        approvers=[
            {"role": "tech_lead", "approver_name": "Amit Verma", "is_required": True},
            {"role": "project_manager", "approver_name": "Priya Nair", "is_required": True},
            {"role": "departing_employee", "approver_name": "Rahul Sharma", "is_required": True},
            {"role": "incoming_employee", "approver_name": "Alex Vance", "is_required": True},
        ],
        created_by_user_id=owner_user.id,
    )

    return {
        "status": "created",
        "message": "Isolated Demo Workspace initialized (Rahul Sharma → Alex Vance).",
        "project_id": proj.id,
        "workspace_id": demo_ws.id,
    }
