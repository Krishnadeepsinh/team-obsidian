from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None

class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ProjectCreate(BaseModel):
    workspace_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    priority: Optional[str] = "medium"
    tags: Optional[List[str]] = []

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None

class ProjectMemberAdd(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    project_role: str = "developer" # owner, admin, tech_lead, developer, pm, qa, reviewer, viewer, departing, incoming
    status: str = "active"

class ProjectMemberResponse(BaseModel):
    id: str
    project_id: str
    user_id: str
    project_role: str
    status: str
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    joined_at: datetime

class ProjectResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    slug: str
    description: Optional[str] = None
    status: str
    priority: str
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    member_count: Optional[int] = 0
    decision_count: Optional[int] = 0
    task_count: Optional[int] = 0
    risk_count: Optional[int] = 0
    evidence_count: Optional[int] = 0

    class Config:
        from_attributes = True

