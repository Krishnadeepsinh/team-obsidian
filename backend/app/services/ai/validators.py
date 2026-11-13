from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("team_obsidian.ai.validators")


class ExtractedEntity(BaseModel):
    name: str
    entity_type: str  # Person, System, Service, Component, Database, Infrastructure, Vendor, Process, Document
    description: Optional[str] = ""
    owner: Optional[str] = None
    evidence_index: int = 1


class ExtractedRelationship(BaseModel):
    source_name: str
    target_name: str
    relation_type: str  # owns, maintains, depends_on, uses, supports, decided, has_workaround, blocks
    context: Optional[str] = ""
    evidence_index: int = 1


class ExtractedDecision(BaseModel):
    title: str
    summary: str
    reasoning: str
    decision_maker: str
    date: str = ""
    component: Optional[str] = None
    decision_type: str = "technical"
    alternatives: List[str] = Field(default_factory=list)
    tradeoffs: List[str] = Field(default_factory=list)
    consequences: List[str] = Field(default_factory=list)
    evidence_index: int = 1


class ExtractedTask(BaseModel):
    title: str
    description: Optional[str] = ""
    owner: str
    priority: str = "medium"
    status: str = "open"
    component: Optional[str] = None
    deadline: Optional[str] = None
    evidence_index: int = 1


class ExtractedRisk(BaseModel):
    title: str
    description: str
    category: str = "technical_risk"
    severity: str = "high"
    likelihood: str = "medium"
    impact: Optional[str] = ""
    owner: Optional[str] = None
    mitigation_strategy: Optional[str] = None
    related_components: List[str] = Field(default_factory=list)
    evidence_index: int = 1


class ExtractedDependency(BaseModel):
    source_component: str
    target_component: str
    dependency_type: str = "hard_blocker"
    description: Optional[str] = ""
    owner: Optional[str] = None
    criticality: str = "high"
    evidence_index: int = 1


class ExtractedResponsibility(BaseModel):
    owner: str
    domain: str
    scope: str
    criticality: str = "high"
    backup_owner: Optional[str] = None
    evidence_index: int = 1


class ExtractedGap(BaseModel):
    title: str
    description: str
    gap_type: str  # missing_architecture, missing_documentation, unassigned_responsibility, unresolved_question, missing_runbook
    severity: str = "high"
    business_impact: str
    technical_impact: str
    recommended_action: str


class StructuredKnowledgeBundle(BaseModel):
    entities: List[ExtractedEntity] = Field(default_factory=list)
    relationships: List[ExtractedRelationship] = Field(default_factory=list)
    decisions: List[ExtractedDecision] = Field(default_factory=list)
    tasks: List[ExtractedTask] = Field(default_factory=list)
    risks: List[ExtractedRisk] = Field(default_factory=list)
    dependencies: List[ExtractedDependency] = Field(default_factory=list)
    responsibilities: List[ExtractedResponsibility] = Field(default_factory=list)
    knowledge_gaps: List[ExtractedGap] = Field(default_factory=list)


class AssistantSynthesisOutput(BaseModel):
    is_answerable: bool
    answer: str
    cited_evidence_indices: List[int] = Field(default_factory=list)
    missing_information_note: Optional[str] = None
    suggested_followups: List[str] = Field(default_factory=list)


def clean_json_markdown(text: str) -> str:
    """Strip markdown code block fences and isolate the valid JSON object."""
    cleaned = (text or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        return match.group(1).strip()
    
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1].strip()
    return cleaned


def safe_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Robustly parse JSON text, with automatic repair of markdown wrappers and trailing commas."""
    candidate = clean_json_markdown(text)
    try:
        return json.loads(candidate)
    except Exception:
        # Attempt trailing comma cleanup
        repaired = re.sub(r",\s*([\]}])", r"\1", candidate)
        try:
            return json.loads(repaired)
        except Exception:
            return None

