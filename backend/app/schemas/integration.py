from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class IntegrationCreate(BaseModel):
    project_id: str
    provider: str  # github, slack, notion, gdrive, manual
    name: str
    auth_type: Optional[str] = "api_token"
    credentials: Optional[Dict[str, Any]] = {}
    config: Optional[Dict[str, Any]] = {}
    is_org_level: Optional[bool] = False


class IntegrationResponse(BaseModel):
    id: str
    project_id: str
    provider: str
    name: str
    status: str
    auth_type: str
    auth_status: Optional[str] = "unverified"
    connected_account: Optional[str] = None
    scopes: Optional[List[str]] = []
    credentials: Optional[Dict[str, Any]] = {}
    config: Dict[str, Any]
    last_sync: Optional[datetime] = None
    error_message: Optional[str] = None
    items_synced: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SourceEventResponse(BaseModel):
    id: str
    integration_id: str
    event_type: str
    status: str
    records_added: int
    records_updated: int
    records_skipped: int
    error_message: Optional[str] = None
    details: Dict[str, Any]
    timestamp: datetime

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: str
    project_id: str
    title: str
    filename: str
    file_type: str
    mime_type: Optional[str] = None
    file_size_bytes: int
    sha256_hash: str
    status: str
    chunk_count: int
    page_count: Optional[int] = None
    sheet_names: Optional[List[str]] = []
    uploaded_by: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SyncResultResponse(BaseModel):
    integration_id: str
    status: str
    items_processed: int
    records_added: int
    records_updated: int = 0
    records_skipped: int = 0
    details: Dict[str, Any]
