import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("ORT_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

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
        self._model_cooldowns: Dict[Tuple[int, str], float] = {}

    @property
    def effective_embedding_model(self) -> str:
        if self._should_use_api_embeddings():
            return "gemini-embedding-001"
        return self.embedding_model_name

    def _should_use_api_embeddings(self) -> bool:
        return bool(settings.GEMINI_API_KEY) and (
            settings.APP_ENV == "production" or "gemini" in (self.embedding_model_name or "").lower()
        )

    def _get_embedder(self):
        if self._embedder is None:
            from fastembed import TextEmbedding

            logger.info("Loading semantic embedding model (single-thread low-RAM): %s", self.embedding_model_name)
            self._embedder = TextEmbedding(model_name=self.embedding_model_name, threads=1)
        return self._embedder

    def _get_client(self):
        if self._genai_client is None and settings.GEMINI_API_KEY:
            from google import genai
            from google.genai import types

            self._genai_client = genai.Client(
                api_key=settings.GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    api_version="v1beta",
                    timeout=8000,
                    client_args={"timeout": 8.0},
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._genai_client

    def _generate_content_with_fallback(self, client, preferred_model: str, contents: str, config: Any):
        """Try preferred Gemini model, falling back on retired (404), overloaded (503), or rate-limited (429) tiers with cooldown caching."""
        candidates = []
        fallback_order = (
            [preferred_model, "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash", "gemini-2.5-flash"]
            if preferred_model == self.secondary_model_name
            else [preferred_model, "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"]
        )
        for m in fallback_order:
            if m and m not in candidates:
                candidates.append(m)

        now = time.monotonic()
        client_key = id(client)
        active_candidates = [
            m for m in candidates if now >= self._model_cooldowns.get((client_key, m), 0.0)
        ]
        if not active_candidates:
            raise RuntimeError("All Gemini model candidates are currently in cooldown; using extractive fallback.")

        last_exc: Optional[Exception] = None
        for idx, model_name in enumerate(active_candidates):
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
                if any(m in err_s for m in ("404", "NOT_FOUND", "no longer available")):
                    self._model_cooldowns[(client_key, model_name)] = time.monotonic() + 1800.0
                    is_recoverable = True
                elif any(m in err_s for m in ("429", "RESOURCE_EXHAUSTED")):
                    self._model_cooldowns[(client_key, model_name)] = time.monotonic() + 300.0
                    is_recoverable = True
                elif any(m in err_s for m in ("503", "504", "UNAVAILABLE", "500", "INTERNAL", "overloaded", "timeout", "timed out")):
                    self._model_cooldowns[(client_key, model_name)] = time.monotonic() + 60.0
                    is_recoverable = True
                else:
                    is_recoverable = False

                if is_recoverable and idx < len(active_candidates) - 1:
                    logger.info("Gemini model %s unavailable (%s); trying fallback", model_name, err_s[:100])
                    continue
                raise
        raise last_exc or RuntimeError("No Gemini model candidates succeeded")

    def _embed_via_gemini_api(
        self,
        cleaned_texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
        title: Optional[str] = None,
    ) -> List[List[float]]:
        from google.genai import types

        client = self._get_client()
        if client is None:
            raise RuntimeError("Gemini client not configured for API embeddings.")

        vectors: List[List[float]] = []
        batch_size = 64
        norm_task = task_type if task_type in ("RETRIEVAL_DOCUMENT", "RETRIEVAL_QUERY", "SEMANTIC_SIMILARITY") else "RETRIEVAL_DOCUMENT"
        for start in range(0, len(cleaned_texts), batch_size):
            batch = cleaned_texts[start : start + batch_size]
            cfg_kwargs: Dict[str, Any] = {
                "output_dimensionality": self.embedding_dimensions,
                "task_type": norm_task,
            }
            if title and norm_task == "RETRIEVAL_DOCUMENT" and len(batch) == 1:
                cfg_kwargs["title"] = title[:200]
            try:
                cfg = types.EmbedContentConfig(**cfg_kwargs)
            except Exception:
                cfg = types.EmbedContentConfig(output_dimensionality=self.embedding_dimensions)
            res = client.models.embed_content(
                model="gemini-embedding-001",
                contents=batch,
                config=cfg,
            )
            for emb in res.embeddings or []:
                arr = np.asarray(emb.values, dtype=np.float32)
                norm = np.linalg.norm(arr)
                if norm > 0:
                    arr = arr / norm
                vectors.append(arr.tolist())
        return vectors

    def generate_embedding(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
        title: Optional[str] = None,
    ) -> List[float]:
        """Generate normalized semantic embedding supporting asymmetric Gemini task_type (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY)."""
        cleaned = (text or "").strip()
        if not cleaned:
            return [0.0] * self.embedding_dimensions
        if self._should_use_api_embeddings():
            try:
                vecs = self._embed_via_gemini_api([cleaned[:4000]], task_type=task_type, title=title)
                if vecs:
                    return vecs[0]
            except Exception as exc:
                logger.warning("Gemini API single embedding failed (%s)", str(exc)[:120])
                if settings.APP_ENV == "production":
                    return [0.0] * self.embedding_dimensions
        embedder = self._get_embedder()
        vec = next(embedder.embed([cleaned[:4000]]))
        arr = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr.tolist()

    def generate_embeddings_batch(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[List[float]]:
        if not texts:
            return []
        non_empty_positions = [(idx, (t or "").strip()[:4000]) for idx, t in enumerate(texts) if (t or "").strip()]
        if not non_empty_positions:
            return [[0.0] * self.embedding_dimensions for _ in texts]

        if self._should_use_api_embeddings():
            try:
                api_vecs = self._embed_via_gemini_api(
                    [txt for _, txt in non_empty_positions],
                    task_type=task_type,
                )
                if len(api_vecs) == len(non_empty_positions):
                    out = [[0.0] * self.embedding_dimensions for _ in texts]
                    for (orig_idx, _), vec in zip(non_empty_positions, api_vecs):
                        out[orig_idx] = vec
                    return out
            except Exception as exc:
                logger.warning("Gemini API batch embedding failed (%s)", str(exc)[:120])
                if settings.APP_ENV == "production":
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
            "total_citations": len(selected),
            "verified_citations": verified_count,
            "distinct_sources": unique_sources,
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
        conversation_history: Optional[List[Dict[str, str]]] = None,
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
        for idx, doc in enumerate(context_docs[:8], 1):
            full_excerpt = (doc.get("full_context") or doc.get("excerpt") or doc.get("content") or "")[:1400]
            display_excerpt = (doc.get("excerpt") or doc.get("content") or "")[:500]
            ts = doc.get("source_timestamp")
            ts_str = ts.isoformat() if isinstance(ts, datetime) else (str(ts) if ts else "Unknown date")
            author = doc.get("source_author") or "Unknown author"
            entity_kind = doc.get("entity_type", "evidence")
            evidence_block.append(
                f"[Evidence {idx}] Source: {doc.get('source_title', 'Project Record')} "
                f"| Kind: {entity_kind} | Type: {doc.get('source_type', 'document')} | Author: {author} | Date: {ts_str} "
                f"| Status: {doc.get('verification_status', 'Needs Human Verification')}\n{full_excerpt}"
            )
            raw_citations.append({
                "evidence_id": doc.get("id", f"ev-{idx}"),
                "entity_type": entity_kind,
                "source_type": doc.get("source_type", "document"),
                "source_title": doc.get("source_title", "Project Record"),
                "source_url": doc.get("source_url"),
                "source_author": author,
                "source_timestamp": ts_str,
                "verification_status": doc.get("verification_status", "Needs Human Verification"),
                "excerpt": display_excerpt,
                "confidence": round(float(doc.get("retrieval_score", doc.get("confidence", 0.5))), 2),
            })

        context_str = "\n\n".join(evidence_block)
        client = self._get_client()

        if client is not None:
            try:
                from google.genai import types

                history_block = ""
                if conversation_history:
                    recent = conversation_history[-4:]
                    formatted_turns = "\n".join(
                        f"- {str(t.get('role', 'user')).upper()}: {str(t.get('content', ''))[:400]}"
                        for t in recent
                        if t.get("content")
                    )
                    if formatted_turns:
                        history_block = f"\nPRIOR CONVERSATION CONTEXT (reference only; still verify facts solely against CONTEXT EVIDENCE):\n{formatted_turns}\n"

                prompt = f"""You are the TEAM OBSIDIAN Evidence-Grounded Knowledge Intelligence Assistant.
Rules:
1. Answer ONLY from the CONTEXT EVIDENCE below. Never use outside knowledge, never guess, and never fabricate names, decisions, links, or ownership.
2. If the provided CONTEXT EVIDENCE does not actually answer the QUESTION, set is_answerable=false and explain clearly what information is missing from the project records.
3. Structure the answer cleanly in Markdown:
   - Start with a crisp 1-2 sentence executive answer.
   - Follow with scannable bullet points grouped under short bold headings only when relevant (e.g. **Key Findings**, **Ownership & Stakeholders**, **Decisions & Rationale**, **Risks & Open Gaps**).
   - Cite supporting evidence inline at the claim level using `[Evidence 1]`, `[Evidence 2]`, and list those 1-based indices in cited_evidence_indices.
4. Distinguish clearly between verified facts and draft/unverified evidence if relevant.
5. Provide up to 3 concise, high-value suggested_followups tailored to the question and uncovered gaps.

DEPARTING FOCUS: {departing_name or 'Not specified'}
{history_block}
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

                # Post-generation citation integrity check: verify every inline [Evidence X] reference exists in raw_citations
                max_idx = len(raw_citations)
                answer_txt = parsed.answer.strip()
                invalid_tags: List[int] = []

                def _sanitize_cite(match: re.Match) -> str:
                    idx_num = int(match.group(1))
                    if 1 <= idx_num <= max_idx:
                        return match.group(0)
                    invalid_tags.append(idx_num)
                    return ""

                answer_txt = re.sub(r"\[Evidence\s+(\d+)\]", _sanitize_cite, answer_txt)
                inline_cited = [int(m) for m in re.findall(r"\[Evidence\s+(\d+)\]", answer_txt)]
                cited = sorted(
                    {i for i in (list(parsed.cited_evidence_indices) + inline_cited) if 1 <= i <= max_idx}
                )
                if not cited:
                    cited = list(range(1, min(len(raw_citations), 3) + 1))
                final_citations = [raw_citations[i - 1] for i in cited]
                conf, breakdown = self.compute_explainable_confidence(context_docs, cited)
                if invalid_tags:
                    conf = round(max(0.0, conf - 0.1), 2)
                    breakdown["ungrounded_citations_stripped"] = sorted(set(invalid_tags))
                return {
                    "answer": answer_txt,
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

        # Strict multi-document extractive synthesis fallback when Gemini is offline or rate-limited
        return self._build_extractive_answer(question, context_docs, raw_citations, departing_name=departing_name)

    def _build_extractive_answer(
        self,
        question: str,
        context_docs: List[Dict[str, Any]],
        raw_citations: List[Dict[str, Any]],
        departing_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Synthesize a clean Markdown answer across top retrieved evidence without fabricating claims."""
        stop_words = {
            "what", "which", "who", "whom", "where", "when", "why", "how", "is", "are", "was", "were",
            "the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "this", "that", "does",
            "do", "did", "can", "could", "there", "remain", "currently", "exist", "project", "about",
        }
        q_tokens = {
            t for t in re.findall(r"[a-z0-9_]{3,}", (question or "").lower())
            if t not in stop_words
        }

        findings: List[str] = []
        owners_seen: List[str] = []
        cited_indices: List[int] = []
        seen_sentences: set[str] = set()
        top_docs = context_docs[: min(len(context_docs), 4)]

        for idx, doc in enumerate(top_docs, 1):
            raw_text = (doc.get("excerpt") or doc.get("content") or "").strip()
            clean_text = re.sub(r"\s+", " ", raw_text)
            candidates = [
                s.strip(" -*\t")
                for s in re.split(r"(?<=[.!?])\s+|\n+", raw_text)
                if len(s.strip(" -*\t")) >= 20
            ]
            if not candidates and clean_text:
                candidates = [clean_text[:280]]

            def _score_sentence(sent: str) -> Tuple[int, float]:
                low = sent.lower()
                hits = sum(1 for tok in q_tokens if tok in low)
                length_bonus = 1.0 if 35 <= len(sent) <= 240 else 0.3
                return (hits, length_bonus)

            ranked = sorted(candidates, key=_score_sentence, reverse=True)
            picked = None
            for cand in ranked:
                norm_cand = re.sub(r"[^a-z0-9]+", " ", cand.lower()).strip()
                if norm_cand and norm_cand not in seen_sentences:
                    seen_sentences.add(norm_cand)
                    picked = cand[:280] + ("..." if len(cand) > 280 else "")
                    break
            if not picked and clean_text:
                picked = clean_text[:260] + ("..." if len(clean_text) > 260 else "")

            source_title = doc.get("source_title") or "Project Record"
            source_type = (doc.get("source_type") or "record").upper()
            author = doc.get("author")
            v_status = doc.get("verification_status")
            meta_parts = [source_type]
            if author:
                meta_parts.append(f"owner/author: {author}")
                if author not in owners_seen:
                    owners_seen.append(str(author))
            if v_status:
                meta_parts.append(v_status)
            meta_label = " · ".join(meta_parts)

            if picked:
                findings.append(f"- **{source_title}** ({meta_label}) [Evidence {idx}]: {picked}")
                cited_indices.append(idx)

        if not cited_indices and raw_citations:
            cited_indices = [1]

        conf, breakdown = self.compute_explainable_confidence(context_docs, cited_indices)
        distinct_src = breakdown.get("independent_sources", len(cited_indices))
        verified_cnt = breakdown.get("verified_citations", 0)

        header = (
            f"### Evidence Summary across {len(cited_indices)} matching record(s)"
            + (f" for **{departing_name}**" if departing_name else "")
            + "\n*Synthesized directly from retrieved project records (extractive fallback active while live LLM quota resets).*"
        )
        sections = [header, "\n**Key Findings**"] + findings

        if owners_seen:
            sections.append(f"\n**Attributed Contributors:** {', '.join(owners_seen[:5])}")

        sections.append(
            f"\n**Verification Coverage:** {verified_cnt}/{len(cited_indices)} cited item(s) verified across {distinct_src} distinct source(s)."
        )

        top_title = (context_docs[0].get("source_title") or "these records")[:45]
        followups = [
            f"What risks or dependencies affect {top_title}?",
            "Who are the primary owners and backups for these systems?",
            "Which knowledge gaps or unverified records remain open?",
        ]

        return {
            "answer": "\n".join(sections),
            "citations": [raw_citations[i - 1] for i in cited_indices if 1 <= i <= len(raw_citations)],
            "confidence": conf,
            "confidence_breakdown": breakdown,
            "is_grounded": True,
            "model_used": f"{self.primary_model_name} (Extractive Synthesis)",
            "suggested_followups": followups,
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

    def extract_text_and_diagram_from_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        context_label: str = "document",
    ) -> Dict[str, Any]:
        """Extract OCR text and architectural diagram structure from an image or rasterized PDF page via Gemini Vision."""
        client = self._get_client()
        if client is not None and image_bytes:
            try:
                from google.genai import types

                prompt = (
                    f"Analyze this {context_label} image for an engineering knowledge handover platform.\n"
                    "1. Transcribe ALL readable text, labels, API routes, commands, error messages, and notes accurately.\n"
                    "2. If it contains an architecture diagram, flowchart, schema, or whiteboard, describe every component/service, "
                    "data store, and directional connection (A -> B).\n"
                    "Return clean structured plain text/markdown."
                )
                image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type or "image/png")
                resp, model_used = self._generate_content_with_fallback(
                    client,
                    self.secondary_model_name,
                    [prompt, image_part],
                    types.GenerateContentConfig(temperature=0.1),
                )
                text_out = (resp.text or "").strip()
                if text_out:
                    return {
                        "ocr_text": text_out,
                        "ocr_performed": True,
                        "ocr_provider": model_used,
                    }
            except Exception as exc:
                logger.warning("Gemini multimodal OCR failed for %s: %s", context_label, str(exc)[:160])

        return {
            "ocr_text": "",
            "ocr_performed": False,
            "ocr_provider": "fallback_metadata",
        }


ai_engine = AIEngine()
