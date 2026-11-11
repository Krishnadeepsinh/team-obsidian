import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger("team_obsidian.ai")


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


class AIEngine:
    """Enterprise AI Engine using real BAAI/bge-small-en-v1.5 embeddings and Google Gemini (google-genai)."""

    def __init__(self):
        self.primary_model_name = settings.PRIMARY_LLM
        self.secondary_model_name = settings.SECONDARY_LLM
        self.embedding_model_name = settings.EMBEDDING_MODEL
        self.embedding_dimensions = settings.EMBEDDING_DIMENSIONS
        self._embedder = None
        self._genai_client = None

    def _get_embedder(self):
        if self._embedder is None:
            from fastembed import TextEmbedding

            logger.info("Loading semantic embedding model: %s", self.embedding_model_name)
            self._embedder = TextEmbedding(model_name=self.embedding_model_name)
        return self._embedder

    def _get_client(self):
        if self._genai_client is None and settings.GEMINI_API_KEY:
            from google import genai

            self._genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._genai_client

    def _generate_content_with_fallback(self, client, preferred_model: str, contents: str, config: Any):
        """Try preferred Gemini model, falling back on retired (404) or rate-limited (429) Flash tiers."""
        candidates = []
        for m in [
            preferred_model,
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-2.5-flash",
        ]:
            if m and m not in candidates:
                candidates.append(m)

        last_exc: Optional[Exception] = None
        for idx, model_name in enumerate(candidates):
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                return resp, model_name
            except Exception as exc:
                last_exc = exc
                err_s = str(exc)
                is_recoverable = any(
                    marker in err_s
                    for marker in (
                        "404",
                        "NOT_FOUND",
                        "429",
                        "RESOURCE_EXHAUSTED",
                        "503",
                        "UNAVAILABLE",
                        "500",
                        "INTERNAL",
                        "overloaded",
                        "timeout",
                        "timed out",
                        "no longer available",
                    )
                )
                if is_recoverable and idx < len(candidates) - 1:
                    logger.info("Gemini model %s unavailable (%s); trying fallback", model_name, err_s[:100])
                    continue
                raise
        raise last_exc or RuntimeError("No Gemini model candidates succeeded")

    def generate_embedding(self, text: str) -> List[float]:
        """Generate a real 384-dimensional normalized semantic embedding using BAAI/bge-small-en-v1.5."""
        cleaned = (text or "").strip()
        if not cleaned:
            return [0.0] * self.embedding_dimensions
        embedder = self._get_embedder()
        vec = next(embedder.embed([cleaned[:4000]]))
        arr = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        embedder = self._get_embedder()
        cleaned = [(t or "").strip()[:4000] or "empty" for t in texts]
        vectors: List[List[float]] = []
        for raw, vec in zip(texts, embedder.embed(cleaned)):
            if not (raw or "").strip():
                vectors.append([0.0] * self.embedding_dimensions)
                continue
            arr = np.asarray(vec, dtype=np.float32)
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            vectors.append(arr.tolist())
        return vectors

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        if not vec1 or not vec2:
            return 0.0
        v1 = np.asarray(vec1, dtype=np.float32)
        v2 = np.asarray(vec2, dtype=np.float32)
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 == 0 or n2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (n1 * n2))

    def compute_explainable_confidence(
        self,
        context_docs: List[Dict[str, Any]],
        cited_indices: Optional[List[int]] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Derive transparent evidence-based confidence from relevance, independent sources, recency, contradictions, and verification."""
        if not context_docs:
            return 0.0, {
                "evidence_coverage": 0.0,
                "avg_relevance": 0.0,
                "independent_sources": 0,
                "verified_ratio": 0.0,
                "contradictions": 0,
                "explanation": "No authorized evidence retrieved.",
            }

        selected = (
            [context_docs[i - 1] for i in cited_indices if 1 <= i <= len(context_docs)]
            if cited_indices
            else context_docs
        )
        if not selected:
            selected = context_docs

        scores = [min(1.0, max(0.0, float(d.get("retrieval_score", d.get("score", 0.5))))) for d in selected]
        avg_rel = sum(scores) / len(scores)
        unique_sources = len({(d.get("source_type"), d.get("source_title")) for d in selected})
        source_diversity = min(1.0, unique_sources / 3.0)

        verified_states = {"Verified", "Verified by Reviewer", "Supported by Evidence"}
        verified_count = sum(1 for d in selected if d.get("verification_status") in verified_states)
        verified_ratio = verified_count / len(selected)

        contradictions = sum(1 for d in selected if d.get("verification_status") in {"Conflicting", "Contradicted"})

        now = datetime.now(timezone.utc)
        recency_scores = []
        for d in selected:
            ts = d.get("source_timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    ts = None
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                days = max(0, (now - ts).days)
                recency_scores.append(max(0.3, 1.0 - min(days, 365) / 500.0))
            else:
                recency_scores.append(0.65)
        avg_recency = sum(recency_scores) / len(recency_scores)

        raw_conf = (
            0.40 * avg_rel
            + 0.25 * source_diversity
            + 0.20 * verified_ratio
            + 0.15 * avg_recency
            - 0.20 * min(1, contradictions)
        )
        confidence = round(max(0.0, min(0.99, raw_conf)), 2)
        breakdown = {
            "evidence_coverage": round(min(1.0, len(selected) / 4.0), 2),
            "avg_relevance": round(avg_rel, 2),
            "independent_sources": unique_sources,
            "verified_ratio": round(verified_ratio, 2),
            "recency_score": round(avg_recency, 2),
            "contradictions": contradictions,
            "explanation": (
                f"Derived from {len(selected)} evidence item(s) across {unique_sources} distinct source(s), "
                f"mean relevance {avg_rel:.2f}, human/evidence verification ratio {verified_ratio:.2f}, "
                f"and {contradictions} contradiction(s)."
            ),
        }
        return confidence, breakdown

    def answer_question(
        self,
        question: str,
        context_docs: List[Dict[str, Any]],
        departing_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Answer project question strictly grounded in retrieved evidence."""
        if not context_docs:
            return {
                "answer": "No supporting evidence found in the connected project repositories, documents, or communication channels to answer this question. Please ensure sources are connected and synchronized.",
                "citations": [],
                "confidence": 0.0,
                "confidence_breakdown": self.compute_explainable_confidence([])[1],
                "is_grounded": False,
                "model_used": self.primary_model_name,
                "suggested_followups": [
                    "What documents are currently ingested?",
                    "What tasks are currently open?",
                    "Who are the team members on this project?",
                ],
            }

        evidence_block = []
        raw_citations = []
        for idx, doc in enumerate(context_docs[:6], 1):
            excerpt = (doc.get("excerpt") or doc.get("content") or "")[:650]
            ts = doc.get("source_timestamp")
            ts_str = ts.isoformat() if isinstance(ts, datetime) else (str(ts) if ts else "Unknown date")
            author = doc.get("source_author") or "Unknown author"
            evidence_block.append(
                f"[Evidence {idx}] Source: {doc.get('source_title', 'Project Record')} "
                f"| Type: {doc.get('source_type', 'document')} | Author: {author} | Date: {ts_str} "
                f"| Status: {doc.get('verification_status', 'Needs Human Verification')}\n{excerpt}"
            )
            raw_citations.append({
                "evidence_id": doc.get("id", f"ev-{idx}"),
                "source_type": doc.get("source_type", "document"),
                "source_title": doc.get("source_title", "Project Record"),
                "source_url": doc.get("source_url"),
                "source_author": author,
                "source_timestamp": ts_str,
                "verification_status": doc.get("verification_status", "Needs Human Verification"),
                "excerpt": excerpt[:400],
                "confidence": round(float(doc.get("retrieval_score", doc.get("confidence", 0.5))), 2),
            })

        context_str = "\n\n".join(evidence_block)
        client = self._get_client()

        if client is not None:
            try:
                from google.genai import types

                prompt = f"""You are the TEAM OBSIDIAN Evidence-Grounded Knowledge Intelligence Assistant.
Rules:
1. Answer ONLY from the CONTEXT EVIDENCE below. Never use outside knowledge, never guess, and never fabricate names, decisions, links, or ownership.
2. If the provided CONTEXT EVIDENCE does not actually answer the QUESTION, set is_answerable=false and explain clearly what information is missing from the project records.
3. When is_answerable=true, cite supporting evidence inline like [Evidence 1], [Evidence 2], and list those 1-based indices in cited_evidence_indices.
4. Distinguish clearly between verified facts and draft/unverified evidence if relevant.

DEPARTING FOCUS: {departing_name or 'Not specified'}

CONTEXT EVIDENCE:
{context_str}

QUESTION:
{question}
"""
                resp, used_model = self._generate_content_with_fallback(
                    client,
                    self.primary_model_name,
                    prompt,
                    types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AssistantSynthesisOutput,
                        temperature=0.1,
                    ),
                )
                parsed = AssistantSynthesisOutput.model_validate_json(resp.text)
                if not parsed.is_answerable:
                    return {
                        "answer": f"No supporting evidence found in the connected project records to answer this question. {parsed.missing_information_note or ''}".strip(),
                        "citations": [],
                        "confidence": 0.0,
                        "confidence_breakdown": self.compute_explainable_confidence([])[1],
                        "is_grounded": False,
                        "model_used": f"{used_model} (Live)",
                        "suggested_followups": parsed.suggested_followups[:3] or [
                            "Which knowledge gaps currently exist?",
                            "What documents and sources are connected?",
                        ],
                    }

                cited = [i for i in parsed.cited_evidence_indices if 1 <= i <= len(raw_citations)]
                if not cited:
                    cited = list(range(1, min(len(raw_citations), 3) + 1))
                final_citations = [raw_citations[i - 1] for i in cited]
                conf, breakdown = self.compute_explainable_confidence(context_docs, cited)
                return {
                    "answer": parsed.answer.strip(),
                    "citations": final_citations,
                    "confidence": conf,
                    "confidence_breakdown": breakdown,
                    "is_grounded": True,
                    "model_used": f"{used_model} (Live)",
                    "suggested_followups": parsed.suggested_followups[:3] or [
                        f"What risks affect this area?",
                        f"What tasks or decisions relate to this?",
                    ],
                }
            except Exception as exc:
                logger.warning("Gemini live Q&A failed, falling back to extractive evidence synthesis: %s", exc)

        # Strict extractive synthesis fallback when Gemini is offline or rate-limited
        top = context_docs[0]
        top_excerpt = (top.get("excerpt") or top.get("content") or "")[:360]
        lines = [
            f"Based on retrieved project evidence from **{top.get('source_title', 'Project Record')}** [Evidence 1]:",
            f"> \"{top_excerpt}\"",
        ]
        if len(context_docs) > 1:
            sec = context_docs[1]
            lines.append(
                f"\nAdditional supporting record in **{sec.get('source_title', 'Project Record')}** [Evidence 2]:\n"
                f"- {(sec.get('excerpt') or sec.get('content') or '')[:220]}"
            )
        conf, breakdown = self.compute_explainable_confidence(context_docs, [1, 2][: len(raw_citations)])
        return {
            "answer": "\n".join(lines),
            "citations": raw_citations[:3],
            "confidence": conf,
            "confidence_breakdown": breakdown,
            "is_grounded": True,
            "model_used": f"{self.primary_model_name} (Extractive Fallback)",
            "suggested_followups": [
                "What decisions relate to these records?",
                "What knowledge gaps remain open?",
            ],
        }

    def extract_knowledge_from_records(
        self,
        records: List[Dict[str, Any]],
        project_name: str = "Project",
    ) -> StructuredKnowledgeBundle:
        """Use Gemini structured extraction (with heuristic fallback) to extract entities, relationships, ADRs, tasks, risks, dependencies, and gaps."""
        if not records:
            return StructuredKnowledgeBundle()

        snippets = []
        for idx, rec in enumerate(records[:15], 1):
            content = (rec.get("content") or rec.get("excerpt") or "")[:1200]
            snippets.append(
                f"[Evidence {idx}] Title: {rec.get('title')} | Type: {rec.get('source_type')} | "
                f"Author: {rec.get('author') or 'Unknown'} | Date: {rec.get('date') or ''}\n{content}"
            )
        joined = "\n\n".join(snippets)

        client = self._get_client()
        if client is not None:
            try:
                from google.genai import types

                prompt = f"""You are extracting structured software engineering knowledge for TEAM OBSIDIAN from authorized records of project "{project_name}".
Rules:
- Extract ONLY facts explicitly stated in the [Evidence X] items below. Never invent people, systems, dates, alternatives, or risks.
- Every extracted item MUST reference the 1-based evidence_index of the [Evidence X] snippet supporting it.
- Use entity types from: Person, Service, Component, Database, Infrastructure, Vendor, Document, Process.
- Use relationship types from: owns, maintains, depends_on, uses, supports, decided, has_workaround, blocks.
- Flag missing runbooks, unclear owners, or undocumented workarounds in knowledge_gaps only when evidenced by the records.

RECORDS:
{joined}
"""
                resp, _ = self._generate_content_with_fallback(
                    client,
                    self.secondary_model_name,
                    prompt,
                    types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=StructuredKnowledgeBundle,
                        temperature=0.1,
                    ),
                )
                return StructuredKnowledgeBundle.model_validate_json(resp.text)
            except Exception as exc:
                logger.warning("Gemini structured extraction failed, using deterministic extraction: %s", exc)

        # Deterministic structured fallback when Gemini is unavailable
        bundle = StructuredKnowledgeBundle()
        for idx, rec in enumerate(records[:15], 1):
            author = rec.get("author")
            title = rec.get("title") or f"Source {idx}"
            text = rec.get("content") or ""
            if author and author not in ("Unknown", "Notion Author"):
                bundle.entities.append(
                    ExtractedEntity(
                        name=author,
                        entity_type="Person",
                        description=f"Contributor identified in {title}",
                        evidence_index=idx,
                    )
                )
            if re.search(r"\b(decided|selected|chose|adr|instead of|over)\b", text, re.I):
                bundle.decisions.append(
                    ExtractedDecision(
                        title=title[:200],
                        summary=text[:280],
                        reasoning=text[:400],
                        decision_maker=author or "Contributor",
                        date=str(rec.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10],
                        evidence_index=idx,
                    )
                )
            if re.search(r"\b(todo|open|pending|unfinished|wip|fix|bug|issue)\b", text, re.I):
                bundle.tasks.append(
                    ExtractedTask(
                        title=title[:200],
                        description=text[:250],
                        owner=author or "Unassigned",
                        priority="high" if re.search(r"\b(critical|urgent|blocker|prod)\b", text, re.I) else "medium",
                        status="open",
                        evidence_index=idx,
                    )
                )
            if re.search(r"\b(risk|spof|single point|failover|outage|workaround|timeout)\b", text, re.I):
                bundle.risks.append(
                    ExtractedRisk(
                        title=f"Risk noted in {title[:120]}",
                        description=text[:320],
                        severity="high",
                        likelihood="medium",
                        owner=author,
                        evidence_index=idx,
                    )
                )
        return bundle


ai_engine = AIEngine()
