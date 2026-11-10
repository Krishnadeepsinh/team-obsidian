from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime

class DecisionCreate(BaseModel):
    project_id: Optional[str] = None
    title: str
    summary: str
    reasoning: str
    decision_maker: str
    date: str
    component: Optional[str] = None
    decision_type: Optional[str] = "technical"
    status: Optional[str] = "accepted"
    alternatives: Optional[List[str]] = []
    tradeoffs: Optional[List[str]] = []
    risks: Optional[List[str]] = []
    supersedes: Optional[List[str]] = []
    evidence_ids: Optional[List[str]] = []

class DecisionResponse(BaseModel):
    id: str
    project_id: str
    title: str
    summary: str
    reasoning: str
    decision_maker: str
    date: str
    component: Optional[str] = None
    decision_type: str
    status: str
    alternatives: List[str]
    tradeoffs: List[str]
    risks: List[str]
    supersedes: List[str]
    superseded_by: Optional[str] = None
    confidence: float
    evidence_ids: List[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TaskCreate(BaseModel):
    project_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    owner: str
    priority: Optional[str] = "medium"
    status: Optional[str] = "open"
    deadline: Optional[str] = None
    dependencies: Optional[List[str]] = []
    is_departing_owner: Optional[bool] = False
    suggested_reassignment: Optional[str] = None
    evidence_ids: Optional[List[str]] = []

class TaskResponse(BaseModel):
    id: str
    project_id: str
    title: str
    description: Optional[str] = None
    owner: str
    priority: str
    status: str
    deadline: Optional[str] = None
    dependencies: List[str]
    is_departing_owner: bool
    suggested_reassignment: Optional[str] = None
    confidence: float
    evidence_ids: List[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class RiskCreate(BaseModel):
    project_id: Optional[str] = None
    title: str
    description: str
    category: Optional[str] = "technical_risk"
    severity: Optional[str] = "high"
    likelihood: Optional[str] = "medium"
    mitigation_strategy: Optional[str] = None
    related_components: Optional[List[str]] = []
    evidence_ids: Optional[List[str]] = []

class RiskResponse(BaseModel):
    id: str
    project_id: str
    title: str
    description: str
    category: str
    severity: str
    likelihood: str
    mitigation_strategy: Optional[str] = None
    status: str
    related_components: List[str]
    evidence_ids: List[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class GapCreate(BaseModel):
    project_id: str
    title: str
    description: str
    gap_type: str
    severity: Optional[str] = "high"
    impact: str
    recommended_action: str

class GapResponse(BaseModel):
    id: str
    project_id: str
    title: str
    description: str
    gap_type: str
    severity: str
    impact: str
    recommended_action: str
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DependencyResponse(BaseModel):
    id: str
    project_id: str
    source_component: str
    target_component: str
    dependency_type: str
    description: Optional[str] = None
    owner: Optional[str] = None
    criticality: str
    evidence_ids: List[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AssistantQueryRequest(BaseModel):
    project_id: str
    question: str
    departing_focus: Optional[str] = None

class Citation(BaseModel):
    evidence_id: str
    source_type: str
    source_title: str
    source_url: Optional[str] = None
    source_author: Optional[str] = None
    source_timestamp: Optional[str] = None
    verification_status: Optional[str] = None
    excerpt: str
    confidence: float


class AssistantQueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence: float
    confidence_breakdown: Optional[Dict[str, Any]] = None
    is_grounded: bool
    model_used: str
    suggested_followups: List[str]

