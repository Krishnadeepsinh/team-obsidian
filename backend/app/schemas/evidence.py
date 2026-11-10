from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class EvidenceResponse(BaseModel):
    id: str
    project_id: str
    source_record_id: Optional[str] = None
    source_type: str
    source_id: str
    source_title: str
    source_url: Optional[str] = None
    source_author: Optional[str] = None
    excerpt: str
    ai_interpretation: str
    confidence: float
    verification_status: str # Verified, Needs Review, Uncertain, Conflicting, Rejected
    content_hash: str
    reviewer_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class EvidenceAuditRequest(BaseModel):
    new_status: str # Verified, Rejected, Uncertain, Conflicting
    review_notes: Optional[str] = None
    reviewer_name: Optional[str] = "Admin Reviewer"

class EvidenceReviewResponse(BaseModel):
    id: str
    evidence_id: str
    reviewer_name: Optional[str] = None
    action: str
    previous_status: str
    new_status: str
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

