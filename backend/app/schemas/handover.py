from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class ApproverConfig(BaseModel):
    role: str
    approver_name: str
    approver_user_id: Optional[str] = None
    is_required: bool = True


class HandoverReconstructRequest(BaseModel):
    project_id: Optional[str] = None
    departing_employee_name: str
    departing_employee_role: str
    incoming_employee_name: str
    incoming_employee_role: str
    target_date: Optional[str] = None
    selected_source_ids: Optional[List[str]] = []
    selected_sources: Optional[List[str]] = []
    selected_categories: Optional[List[str]] = ["Architecture", "Decisions", "Tasks", "Risks", "Gaps"]
    approvers: Optional[List[ApproverConfig]] = None


class SectionEditRequest(BaseModel):
    content: str
    is_verified: Optional[bool] = None
    verification_status: Optional[str] = None
    reason: Optional[str] = None


class SectionReviewRequest(BaseModel):
    action: str  # verify, approve, reject, request_changes
    verification_status: Optional[str] = None
    notes: Optional[str] = None


class ClaimVerifyRequest(BaseModel):
    verification_status: str
    review_notes: Optional[str] = None


class SectionCommentRequest(BaseModel):
    author: Optional[str] = None
    text: str


class HandoverApprovalRequest(BaseModel):
    approver_name: Optional[str] = None
    role: str
    status: str  # approved, rejected, changes_requested, acknowledged
    notes: Optional[str] = None


class HandoverStatusRequest(BaseModel):
    status: str  # published, archived, in_review
    reason: Optional[str] = None


class SimulatorEvaluateRequest(BaseModel):
    candidate_name: Optional[str] = None
    answers: Dict[str, str] = {}
    follow_ups: Optional[Dict[str, str]] = None
    scenarios: Optional[List[Dict[str, Any]]] = None


class ExitInterviewAnswerRequest(BaseModel):
    answer_text: str
    resolve_linked_gap: bool = True


class ExitInterviewQuestionResponse(BaseModel):
    id: str
    handover_id: str
    project_id: str
    section_number: Optional[int] = None
    knowledge_gap_id: Optional[str] = None
    question_text: str
    answer_text: Optional[str] = None
    status: str
    priority: str
    evidence_id: Optional[str] = None
    answered_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HandoverDeltaSyncResponse(BaseModel):
    handover_id: str
    version_number: int
    preserved_sections: List[int]
    updated_sections: List[int]
    previous_confidence: float
    new_confidence: float
    drift_warnings_cleared: int
    summary: str


class HandoverClaimResponse(BaseModel):
    id: str
    handover_id: str
    section_id: str
    claim_text: str
    verification_status: str
    confidence: float
    evidence_ids: List[str]
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HandoverSectionResponse(BaseModel):
    id: str
    handover_id: str
    section_number: int
    title: str
    content: str
    is_verified: bool
    verification_status: Optional[str] = "Needs Human Verification"
    confidence: Optional[float] = 0.0
    evidence_ids: List[str]
    comments: List[Dict[str, Any]]
    claims: Optional[List[HandoverClaimResponse]] = []
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HandoverApprovalResponse(BaseModel):
    id: str
    handover_id: str
    approver_user_id: Optional[str] = None
    approver_name: str
    role: str
    status: str
    is_required: Optional[bool] = True
    notes: Optional[str] = None
    signed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HandoverVersionResponse(BaseModel):
    id: str
    handover_id: str
    version_number: int
    user_id: Optional[str] = None
    changed_section: Optional[str] = None
    previous_content: Optional[str] = None
    new_content: Optional[str] = None
    reason: Optional[str] = None
    changelog: Optional[str] = None
    created_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HandoverResponse(BaseModel):
    id: str
    project_id: str
    title: str
    departing_employee_name: str
    departing_employee_role: str
    incoming_employee_name: str
    incoming_employee_role: str
    status: str
    target_date: Optional[str] = None
    selected_sources: List[str]
    selected_categories: List[str]
    reconstruction_stats: Dict[str, Any]
    overall_confidence: float
    confidence_breakdown: Optional[Dict[str, Any]] = {}
    pdf_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sections: Optional[List[HandoverSectionResponse]] = []
    approvals: Optional[List[HandoverApprovalResponse]] = []
    versions: Optional[List[HandoverVersionResponse]] = []

    model_config = ConfigDict(from_attributes=True)
