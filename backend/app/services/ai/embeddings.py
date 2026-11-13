from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
import numpy as np

from app.core.config import settings

logger = logging.getLogger("team_obsidian.ai.embeddings")


class EmbeddingService:
    """Enterprise text embedding service separating vector representation generation from generative LLM inference."""

    def __init__(self):
        self.embedding_model_name = settings.EMBEDDING_MODEL
        self.embedding_dimensions = settings.EMBEDDING_DIMENSIONS
        self._embedder = None
        self._genai_client = None

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
            for emb in res.embeddings:
                v = list(emb.values)
                if len(v) != self.embedding_dimensions:
                    if len(v) > self.embedding_dimensions:
                        v = v[: self.embedding_dimensions]
                    else:
                        v = v + [0.0] * (self.embedding_dimensions - len(v))
                vectors.append(v)
        return vectors

    def generate_embedding(
        self,
        text: str,
        task_type: str = "RETRIEVAL_DOCUMENT",
        title: Optional[str] = None,
    ) -> List[float]:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned:
            return [0.0] * self.embedding_dimensions

        if self._should_use_api_embeddings():
            try:
                res = self._embed_via_gemini_api([cleaned], task_type=task_type, title=title)
                if res and len(res) == 1:
                    return res[0]
            except Exception as e:
                logger.warning("Gemini embedding API failed (%s); falling back to local embedder", e)

        embedder = self._get_embedder()
        vec_gen = embedder.embed([cleaned])
        raw_vec = next(vec_gen)
        vec = [float(x) for x in raw_vec]
        if len(vec) != self.embedding_dimensions:
            if len(vec) > self.embedding_dimensions:
                vec = vec[: self.embedding_dimensions]
            else:
                vec = vec + [0.0] * (self.embedding_dimensions - len(vec))
        return vec

    def generate_embeddings_batch(
        self,
        texts: List[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
        titles: Optional[List[str]] = None,
    ) -> List[List[float]]:
        if not texts:
            return []

        cleaned_texts = [re.sub(r"\s+", " ", (t or "").strip()) for t in texts]
        non_empty_indices = [i for i, t in enumerate(cleaned_texts) if t]
        if not non_empty_indices:
            return [[0.0] * self.embedding_dimensions for _ in texts]

        results: List[List[float]] = [[0.0] * self.embedding_dimensions for _ in texts]
        active_texts = [cleaned_texts[i] for i in non_empty_indices]

        if self._should_use_api_embeddings():
            try:
                vectors = self._embed_via_gemini_api(active_texts, task_type=task_type)
                for orig_idx, vec in zip(non_empty_indices, vectors):
                    results[orig_idx] = vec
                return results
            except Exception as e:
                logger.warning("Batch Gemini embedding API failed (%s); falling back to local embedder", e)

        embedder = self._get_embedder()
        vec_gen = embedder.embed(active_texts, batch_size=32)
        for orig_idx, raw_vec in zip(non_empty_indices, vec_gen):
            vec = [float(x) for x in raw_vec]
            if len(vec) != self.embedding_dimensions:
                if len(vec) > self.embedding_dimensions:
                    vec = vec[: self.embedding_dimensions]
                else:
                    vec = vec + [0.0] * (self.embedding_dimensions - len(vec))
            results[orig_idx] = vec
        return results

    def cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        if not vec_a or not vec_b:
            return 0.0
        a = np.array(vec_a, dtype=np.float32)
        b = np.array(vec_b, dtype=np.float32)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        val = float(np.dot(a, b) / (norm_a * norm_b))
        return max(-1.0, min(1.0, val))


embedding_service = EmbeddingService()

