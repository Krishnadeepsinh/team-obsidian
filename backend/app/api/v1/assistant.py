import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_effective_project, verify_project_access
from app.core.security import get_current_user
from app.models.evidence import Evidence
from app.models.knowledge import (
    AssistantConversation,
    AssistantMessage,
    Decision,
    KnowledgeGap,
)
from app.models.workspace import User
from app.schemas.knowledge import (
    AssistantConversationDetail,
    AssistantConversationSummary,
    AssistantMessageOut,
    AssistantPromoteRequest,
    AssistantQueryRequest,
    AssistantQueryResponse,
)
from app.services.ai_engine import ai_engine
from app.services.assistant.orchestrator import query_orchestrator
from app.services.audit_service import record_activity
from app.services.retrieval_service import retrieve_hybrid_graph_context

router = APIRouter(prefix="/assistant", tags=["AI Project Assistant"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _derive_title(question: str) -> str:
    clean = re.sub(r"\s+", " ", (question or "").strip())
    if not clean:
        return "New Conversation"
    return clean if len(clean) <= 72 else clean[:69].rstrip() + "..."


def _resolve_project_id(req_project_id: Optional[str], current_user: User, db: Session) -> Optional[str]:
    if req_project_id and req_project_id != "default":
        verify_project_access(req_project_id, current_user, db)
        return req_project_id
    eff = get_effective_project(None, current_user, db)
    return eff.id if eff else None


def _load_owned_conversation(
    conversation_id: str,
    current_user: User,
    db: Session,
    project_id: Optional[str] = None,
) -> AssistantConversation:
    conv = db.query(AssistantConversation).filter(AssistantConversation.id == conversation_id).first()
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if project_id and conv.project_id != project_id:
        raise HTTPException(status_code=404, detail="Conversation does not belong to the selected project")
    verify_project_access(conv.project_id, current_user, db)
    return conv


def _retrieve_hybrid_context(
    project_id: str,
    question: str,
    departing_focus: Optional[str],
    all_evidences: Optional[List[Evidence]],
    db: Session,
) -> List[Dict[str, Any]]:
    return retrieve_hybrid_graph_context(
        project_id=project_id,
        question=question,
        departing_focus=departing_focus,
        db=db,
        all_evidences=all_evidences,
        top_k=8,
    )


def _execute_assistant_turn(
    req: AssistantQueryRequest,
    current_user: User,
    db: Session,
) -> AssistantQueryResponse:
    project_id = _resolve_project_id(req.project_id, current_user, db)
    if not project_id:
        return AssistantQueryResponse(
            answer="No accessible project found in your workspace yet. Create a project and connect sources first.",
            citations=[],
            confidence=0.0,
            is_grounded=False,
            model_used=ai_engine.primary_model_name,
            suggested_followups=["Create a project", "Connect GitHub or upload a document"],
        )

    # Resolve or create persistent conversation thread
    if req.conversation_id:
        conv = _load_owned_conversation(req.conversation_id, current_user, db, project_id=project_id)
        if req.departing_focus and not conv.departing_focus:
            conv.departing_focus = req.departing_focus
    else:
        conv = AssistantConversation(
            project_id=project_id,
            user_id=current_user.id,
            title=_derive_title(req.question),
            departing_focus=req.departing_focus,
        )
        db.add(conv)
        db.flush()

    prior_turns = [
        {"role": m.role, "content": m.content}
        for m in (
            db.query(AssistantMessage)
            .filter(AssistantMessage.conversation_id == conv.id)
            .order_by(AssistantMessage.created_at.asc())
            .all()
        )
    ]

    user_msg = AssistantMessage(
        conversation_id=conv.id,
        role="user",
        content=req.question.strip(),
        is_grounded=True,
    )
    db.add(user_msg)
    db.flush()

    all_evidences = db.query(Evidence).filter(Evidence.project_id == project_id).all()
    result = query_orchestrator.process_query(
        question=req.question,
        current_user=current_user,
        project_id=project_id,
        departing_focus=req.departing_focus,
        conversation_history=prior_turns,
        db=db,
    )

    assistant_msg = AssistantMessage(
        conversation_id=conv.id,
        role="assistant",
        content=result["answer"],
        citations_json=result.get("citations") or [],
        confidence=result.get("confidence"),
        confidence_breakdown_json=result.get("confidence_breakdown") or {},
        is_grounded=bool(result.get("is_grounded", False)),
        model_used=result.get("model_used"),
        suggested_followups_json=result.get("suggested_followups") or [],
    )
    db.add(assistant_msg)
    conv.updated_at = _utc_now()
    db.commit()
    db.refresh(assistant_msg)

    return AssistantQueryResponse(
        answer=result["answer"],
        citations=result["citations"],
        confidence=result["confidence"],
        confidence_breakdown=result.get("confidence_breakdown"),
        is_grounded=result["is_grounded"],
        model_used=result["model_used"],
        suggested_followups=result["suggested_followups"],
        response_level=result.get("response_level", 2),
        conversation_id=conv.id,
        message_id=assistant_msg.id,
    )


def _format_sse(event_name: str, payload: Dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


@router.post("/query", response_model=AssistantQueryResponse)
def query_assistant(
    req: AssistantQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask a project question grounded strictly in authorized evidence using Hybrid RAG (pgvector + keyword)."""
    return _execute_assistant_turn(req, current_user, db)


@router.post("/query/stream")
def query_assistant_stream(
    req: AssistantQueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream an evidence-grounded AI Assistant response over Server-Sent Events (SSE) and persist the thread."""
    response_obj = _execute_assistant_turn(req, current_user, db)

    def _event_stream() -> Iterator[str]:
        yield _format_sse(
            "meta",
            {
                "conversation_id": response_obj.conversation_id,
                "message_id": response_obj.message_id,
                "model_used": response_obj.model_used,
            },
        )
        # Stream answer tokens cleanly in small word groups so the UI renders incremental progress
        chunks = re.findall(r"\S+\s*", response_obj.answer or "")
        if not chunks:
            yield _format_sse("token", {"text": response_obj.answer or ""})
        else:
            step = 3
            for i in range(0, len(chunks), step):
                yield _format_sse("token", {"text": "".join(chunks[i : i + step])})

        yield _format_sse("done", response_obj.model_dump())

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=List[AssistantConversationSummary])
def list_conversations(
    project_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List saved AI Assistant conversations for the current user in the active project."""
    resolved_pid = _resolve_project_id(project_id, current_user, db)
    if not resolved_pid:
        return []

    convs = (
        db.query(AssistantConversation)
        .filter(
            AssistantConversation.project_id == resolved_pid,
            AssistantConversation.user_id == current_user.id,
        )
        .order_by(AssistantConversation.updated_at.desc())
        .limit(50)
        .all()
    )
    if not convs:
        return []

    counts_rows = (
        db.query(AssistantMessage.conversation_id, func.count(AssistantMessage.id))
        .filter(AssistantMessage.conversation_id.in_([c.id for c in convs]))
        .group_by(AssistantMessage.conversation_id)
        .all()
    )
    counts = {cid: int(cnt) for cid, cnt in counts_rows}

    return [
        AssistantConversationSummary(
            id=c.id,
            project_id=c.project_id,
            title=c.title,
            departing_focus=c.departing_focus,
            message_count=counts.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in convs
    ]


@router.get("/conversations/{conversation_id}", response_model=AssistantConversationDetail)
def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return a single conversation and all ordered messages owned by the current user."""
    conv = _load_owned_conversation(conversation_id, current_user, db)
    msgs = (
        db.query(AssistantMessage)
        .filter(AssistantMessage.conversation_id == conv.id)
        .order_by(AssistantMessage.created_at.asc())
        .all()
    )
    return AssistantConversationDetail(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title,
        departing_focus=conv.departing_focus,
        messages=[
            AssistantMessageOut(
                id=m.id,
                conversation_id=m.conversation_id,
                role=m.role,
                content=m.content,
                citations=m.citations_json or [],
                confidence=m.confidence,
                confidence_breakdown=m.confidence_breakdown_json or None,
                is_grounded=bool(m.is_grounded),
                model_used=m.model_used,
                suggested_followups=m.suggested_followups_json or [],
                created_at=m.created_at,
            )
            for m in msgs
        ],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a saved AI Assistant conversation owned by the current user."""
    conv = _load_owned_conversation(conversation_id, current_user, db)
    db.delete(conv)
    db.commit()
    return {"status": "deleted", "conversation_id": conversation_id}


@router.post("/promote")
def promote_assistant_insight(
    req: AssistantPromoteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote an AI Assistant finding directly into a persisted Decision (ADR) or Knowledge Gap."""
    eff_proj = get_effective_project(req.project_id, current_user, db, require_write=True)
    if not eff_proj:
        raise HTTPException(status_code=400, detail="No accessible project found.")

    clean_type = (req.target_type or "").strip().lower()
    clean_title = (req.title or "").strip()[:480]
    clean_content = (req.content or "").strip()
    if not clean_title or not clean_content:
        raise HTTPException(status_code=400, detail="Title and content are required.")

    ev_ids = [eid for eid in (req.evidence_ids or []) if eid]

    if clean_type == "decision":
        d = Decision(
            project_id=eff_proj.id,
            created_by_user_id=current_user.id,
            title=clean_title,
            summary=clean_content[:1200],
            reasoning=clean_content,
            decision_maker=current_user.name or current_user.email,
            date=_utc_now().strftime("%Y-%m-%d"),
            component=req.component or "Architecture",
            decision_type="technical",
            status="accepted",
            verification_status="Supported by Evidence" if ev_ids else "Verified by Reviewer",
            evidence_ids=ev_ids,
            confidence=0.9 if ev_ids else 0.75,
        )
        db.add(d)
        db.flush()
        record_activity(
            db=db,
            action="decision.promoted_from_assistant",
            entity_type="decision",
            entity_id=d.id,
            user_id=current_user.id,
            project_id=eff_proj.id,
            actor_email=current_user.email,
            details={"message": f"Promoted AI Assistant insight to Decision '{d.title}'"},
        )
        db.commit()
        return {"status": "created", "target_type": "decision", "id": d.id, "title": d.title}

    if clean_type == "gap":
        sev = (req.severity or "high").strip().lower()
        if sev not in {"critical", "high", "medium", "low"}:
            sev = "high"
        g = KnowledgeGap(
            project_id=eff_proj.id,
            title=clean_title,
            description=clean_content,
            gap_type="assistant_flagged",
            severity=sev,
            priority=sev,
            impact="Identified during AI Assistant knowledge verification.",
            business_impact="May delay smooth project transition if left undocumented.",
            technical_impact="Requires owner review and source evidence linkage.",
            recommended_action="Assign an owner to document and verify missing context.",
            assigned_reviewer=current_user.name or current_user.email,
        )
        db.add(g)
        db.flush()
        record_activity(
            db=db,
            action="gap.promoted_from_assistant",
            entity_type="knowledge_gap",
            entity_id=g.id,
            user_id=current_user.id,
            project_id=eff_proj.id,
            actor_email=current_user.email,
            details={"message": f"Logged Knowledge Gap '{g.title}' from AI Assistant"},
        )
        db.commit()
        return {"status": "created", "target_type": "gap", "id": g.id, "title": g.title}

    raise HTTPException(status_code=400, detail="target_type must be 'decision' or 'gap'")
