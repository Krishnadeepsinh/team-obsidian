from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.core.config import settings
from app.services.ai.embeddings import embedding_service
from app.services.ai.prompts import PromptManager
from app.services.ai.provider import central_ai_service
from app.services.ai.validators import (
    AssistantSynthesisOutput,
    ExtractedDecision,
    ExtractedDependency,
    ExtractedEntity,
    ExtractedGap,
    ExtractedRelationship,
    ExtractedResponsibility,
    ExtractedRisk,
    ExtractedTask,
    StructuredKnowledgeBundle,
    clean_json_markdown,
    safe_parse_json,
)

logger = logging.getLogger("team_obsidian.ai")


class AIEngine:
    """Enterprise AI Engine coordinating Groq (primary inference), Gemini (fallback inference), and local embeddings."""

    def __init__(self):
        self.primary_model_name = settings.GROQ_PRIMARY_MODEL if settings.GROQ_API_KEY else settings.PRIMARY_LLM
        self.secondary_model_name = settings.GROQ_SECONDARY_MODEL if settings.GROQ_API_KEY else settings.SECONDARY_LLM
        self.embedding_model_name = settings.EMBEDDING_MODEL
        self.embedding_dimensions = settings.EMBEDDING_DIMENSIONS
        self._embedding_service = embedding_service
        self._central_ai = central_ai_service
        self._prompt_manager = PromptManager
        self._genai_client = None
        self._model_cooldowns: Dict[Tuple[int, str], float] = {}

    @property
    def effective_embedding_model(self) -> str:
        return self._embedding_service.effective_embedding_model

    def _should_use_api_embeddings(self) -> bool:
        return self._embedding_service._should_use_api_embeddings()

    def _get_embedder(self):
        return self._embedding_service._get_embedder()

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

    def generate_embedding(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
        title: Optional[str] = None,
    ) -> List[float]:
        return self._embedding_service.generate_embedding(text=text, task_type=task_type, title=title)

    def generate_embeddings_batch(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
        titles: Optional[List[str]] = None,
    ) -> List[List[float]]:
        return self._embedding_service.generate_embeddings_batch(texts=texts, task_type=task_type, titles=titles)

    def cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        return self._embedding_service.cosine_similarity(vec_a, vec_b)

    def compute_explainable_confidence(
        self,
        evidence_records: List[Dict[str, Any]],
        cited_indices: Optional[List[int]] = None,
    ) -> Tuple[float, Dict[str, Any]]:
        """Compute an explainable confidence score (0.0 to 1.0) and auditable breakdown."""
        if not evidence_records:
            return 0.0, {
                "total_citations": 0,
                "verified_citations": 0,
                "distinct_sources": 0,
                "evidence_coverage": 0.0,
                "avg_relevance": 0.0,
                "contradictions": 0,
                "explanation": "No evidence retrieved to support claim.",
            }

        selected = []
        if cited_indices:
            for idx in cited_indices:
                if 1 <= idx <= len(evidence_records):
                    selected.append(evidence_records[idx - 1])
        if not selected:
            selected = evidence_records[: min(len(evidence_records), 4)]

        unique_sources = len({
            doc.get("source_id") or doc.get("source_title") or doc.get("title") or str(idx)
            for idx, doc in enumerate(selected)
        })

        verified_count = 0
        relevance_scores = []
        recency_scores = []
        now = datetime.now(timezone.utc)

        verified_states = {
            "verified", "verified by reviewer", "supported by evidence",
            "human_verified", "automated_verified"
        }
        for doc in selected:
            status = (doc.get("verification_status") or "").strip().lower()
            if status in verified_states:
                verified_count += 1
            rel = float(doc.get("retrieval_score", doc.get("confidence", 0.5)))
            relevance_scores.append(max(0.0, min(1.0, rel)))

            ts = doc.get("source_timestamp") or doc.get("created_at")
            if isinstance(ts, str):
                try:
                    if ts.endswith("Z"):
                        ts = ts[:-1] + "+00:00"
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    ts = None
            if isinstance(ts, datetime):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = max(0, (now - ts).days)
                recency_scores.append(max(0.2, 1.0 - (age_days / 180.0)))
            else:
                recency_scores.append(0.6)

        avg_rel = float(np.mean(relevance_scores)) if relevance_scores else 0.5
        avg_recency = float(np.mean(recency_scores)) if recency_scores else 0.6
        verified_ratio = (verified_count / len(selected)) if selected else 0.0
        source_diversity = min(1.0, unique_sources / 3.0)

        contradictions = 0
        contents = [
            (doc.get("full_context") or doc.get("excerpt") or doc.get("content") or "").lower()
            for doc in selected
        ]
        has_pos = any("approved" in c or "enabled" in c or "success" in c for c in contents)
        has_neg = any("rejected" in c or "disabled" in c or "failed" in c or "deprecated" in c for c in contents)
        if has_pos and has_neg:
            contradictions = 1

        raw_score = (
            0.35 * avg_rel
            + 0.25 * verified_ratio
            + 0.20 * source_diversity
            + 0.20 * avg_recency
            - 0.15 * contradictions
        )
        confidence = round(max(0.05, min(0.99, raw_score)), 2)
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

        # 1. Attempt Groq primary inference when configured
        if settings.GROQ_API_KEY and self._genai_client is None and self._central_ai.groq_provider.is_available():
            try:
                sys_prompt, user_prompt = self._prompt_manager.build_qa_prompt(
                    query=question,
                    context_text=context_str,
                    conversation_history=conversation_history,
                )
                resp_text = self._central_ai.groq_provider.generate_completion(
                    prompt=user_prompt,
                    system_instruction=sys_prompt,
                    response_format="json_object",
                    temperature=0.1,
                )
                parsed_dict = safe_parse_json(resp_text)
                if parsed_dict:
                    parsed = AssistantSynthesisOutput.model_validate(parsed_dict)
                    if not parsed.is_answerable:
                        return {
                            "answer": f"No supporting evidence found in the connected project records to answer this question. {parsed.missing_information_note or ''}".strip(),
                            "citations": [],
                            "confidence": 0.0,
                            "confidence_breakdown": self.compute_explainable_confidence([])[1],
                            "is_grounded": False,
                            "model_used": "Groq (Live)",
                            "suggested_followups": parsed.suggested_followups[:3] or [
                                "Which knowledge gaps currently exist?",
                                "What documents and sources are connected?",
                            ],
                        }
                    max_idx = len(raw_citations)
                    answer_txt = parsed.answer.strip()
                    inline_cited = [int(m) for m in re.findall(r"\[Evidence\s+(\d+)\]", answer_txt)]
                    cited = sorted({i for i in (list(parsed.cited_evidence_indices) + inline_cited) if 1 <= i <= max_idx})
                    if not cited:
                        cited = list(range(1, min(len(raw_citations), 3) + 1))
                    final_citations = [raw_citations[i - 1] for i in cited]
                    conf, breakdown = self.compute_explainable_confidence(context_docs, cited)
                    return {
                        "answer": answer_txt,
                        "citations": final_citations,
                        "confidence": conf,
                        "confidence_breakdown": breakdown,
                        "is_grounded": True,
                        "model_used": "Groq (Live)",
                        "suggested_followups": parsed.suggested_followups[:3] or [
                            "What risks affect this area?",
                            "What tasks or decisions relate to this?",
                        ],
                    }
            except Exception as exc:
                logger.warning("Groq inference failed (%s); falling back to Gemini", exc)

        # 2. Attempt Gemini fallback inference with cooldown caching
        client = self._get_client()
        if client is not None:
            try:
                from google.genai import types

                sys_prompt, user_prompt = self._prompt_manager.build_qa_prompt(
                    query=question,
                    context_text=context_str,
                    conversation_history=conversation_history,
                )
                resp, used_model = self._generate_content_with_fallback(
                    client,
                    self.primary_model_name,
                    user_prompt,
                    types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AssistantSynthesisOutput,
                        temperature=0.1,
                    ),
                )
                resp_body = getattr(resp, "text", "") or str(resp)
                parsed = AssistantSynthesisOutput.model_validate_json(resp_body)
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
                cited = sorted({
                    i for i in (list(parsed.cited_evidence_indices) + inline_cited) if 1 <= i <= max_idx
                })
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
                    "model_used": "Obsidian Intelligence Engine",
                    "suggested_followups": parsed.suggested_followups[:3] or [
                        "What risks affect this area?",
                        "What tasks or decisions relate to this?",
                    ],
                }
            except Exception as exc:
                logger.warning("Gemini live Q&A failed, falling back to extractive evidence synthesis: %s", exc)

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
            "model_used": "Obsidian Intelligence Engine",
            "suggested_followups": followups,
        }

    def extract_knowledge_from_records(
        self,
        records: List[Dict[str, Any]],
        project_name: str = "Project",
    ) -> StructuredKnowledgeBundle:
        """Use Central AI structured extraction (Groq primary / Gemini fallback / heuristic) to extract knowledge items."""
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

        try:
            sys_prompt, user_prompt = self._prompt_manager.build_knowledge_extraction_prompt(
                evidence_text=joined,
                project_name=project_name,
            )
            resp_text, _ = self._central_ai.generate_completion(
                prompt=user_prompt,
                system_instruction=sys_prompt,
                response_format="json_object",
                temperature=0.1,
            )
            parsed_dict = safe_parse_json(resp_text)
            if parsed_dict:
                return StructuredKnowledgeBundle.model_validate(parsed_dict)
        except Exception as exc:
            logger.warning("Central AI structured extraction failed (%s); using deterministic extraction", exc)

        # Deterministic structured fallback
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
        """Extract OCR text and architectural diagram structure from an image via vision model."""
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
                resp = client.models.generate_content(
                    model=self.secondary_model_name,
                    contents=[prompt, image_part],
                    config=types.GenerateContentConfig(temperature=0.1),
                )
                text_out = (resp.text or "").strip()
                if text_out:
                    return {
                        "ocr_text": text_out,
                        "ocr_performed": True,
                        "ocr_provider": self.secondary_model_name,
                    }
            except Exception as exc:
                logger.warning("Multimodal OCR failed for %s: %s", context_label, str(exc)[:160])

        return {
            "ocr_text": "",
            "ocr_performed": False,
            "ocr_provider": "fallback_metadata",
        }


ai_engine = AIEngine()

__all__ = [
    "AIEngine",
    "ai_engine",
    "ExtractedEntity",
    "ExtractedRelationship",
    "ExtractedDecision",
    "ExtractedTask",
    "ExtractedRisk",
    "ExtractedDependency",
    "ExtractedResponsibility",
    "ExtractedGap",
    "StructuredKnowledgeBundle",
    "AssistantSynthesisOutput",
]
