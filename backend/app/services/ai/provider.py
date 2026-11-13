from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("team_obsidian.ai.provider")


class BaseLLMProvider(ABC):
    """Abstract interface for LLM inference providers."""

    name: str = "base"

    @abstractmethod
    def generate_completion(
        self,
        prompt: str,
        system_instruction: str = "",
        response_format: str = "text",  # "text" | "json_object"
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Generate response text from LLM."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is configured and not in full cooldown."""


class GroqProvider(BaseLLMProvider):
    """Central AI inference provider powered by Groq (ultra-low latency Llama-3.3-70B / Llama-3.1-8B)."""

    name: str = "groq"

    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        self.primary_model = settings.GROQ_PRIMARY_MODEL or "llama-3.3-70b-versatile"
        self.secondary_model = settings.GROQ_SECONDARY_MODEL or "llama-3.1-8b-instant"
        self._client = None
        self._cooldown_until: float = 0.0

    def _get_client(self):
        if self._client is None and self.api_key:
            try:
                from groq import Groq
                self._client = Groq(api_key=self.api_key, timeout=20.0)
            except Exception as e:
                logger.error("Failed to initialize Groq client: %s", e)
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key) and time.monotonic() >= self._cooldown_until

    def generate_completion(
        self,
        prompt: str,
        system_instruction: str = "",
        response_format: str = "text",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        client = self._get_client()
        if client is None:
            raise RuntimeError("Groq client is not configured or missing GROQ_API_KEY.")

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        models = [self.primary_model, self.secondary_model]
        last_exc: Optional[Exception] = None

        for model in models:
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if response_format == "json_object":
                    kwargs["response_format"] = {"type": "json_object"}

                completion = client.chat.completions.create(**kwargs)
                if completion.choices and completion.choices[0].message:
                    return completion.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                err_s = str(exc)
                if any(m in err_s for m in ("429", "rate_limit", "Rate limit")):
                    self._cooldown_until = time.monotonic() + 120.0
                    logger.warning("Groq rate limited on %s; backing off for 120s: %s", model, err_s[:100])
                else:
                    logger.warning("Groq inference error on %s: %s", model, err_s[:100])
                continue

        raise last_exc or RuntimeError("All Groq model attempts failed.")


class GeminiProvider(BaseLLMProvider):
    """Fallback generative inference provider powered by Google Gemini (google-genai)."""

    name: str = "gemini"

    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.primary_model = settings.PRIMARY_LLM or "gemini-3.5-flash"
        self.secondary_model = settings.SECONDARY_LLM or "gemini-3.5-flash-lite"
        self._client = None
        self._model_cooldowns: Dict[str, float] = {}

    def _get_client(self):
        if self._client is None and self.api_key:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    api_version="v1beta",
                    timeout=15000,
                    client_args={"timeout": 15.0},
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        now = time.monotonic()
        candidates = [self.primary_model, self.secondary_model, "gemini-3.5-flash-lite", "gemini-2.5-flash"]
        return any(now >= self._model_cooldowns.get(m, 0.0) for m in candidates)

    def generate_completion(
        self,
        prompt: str,
        system_instruction: str = "",
        response_format: str = "text",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        client = self._get_client()
        if client is None:
            raise RuntimeError("Gemini client is not configured or missing GEMINI_API_KEY.")

        from google.genai import types

        candidates = [
            self.primary_model,
            self.secondary_model,
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
            "gemini-2.5-flash",
        ]
        now = time.monotonic()
        active = [m for m in candidates if now >= self._model_cooldowns.get(m, 0.0)]
        if not active:
            raise RuntimeError("All Gemini models currently in cooldown.")

        last_exc: Optional[Exception] = None
        for m in active:
            try:
                cfg_kwargs: Dict[str, Any] = {
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                }
                if system_instruction:
                    cfg_kwargs["system_instruction"] = system_instruction
                if response_format == "json_object":
                    cfg_kwargs["response_mime_type"] = "application/json"

                cfg = types.GenerateContentConfig(**cfg_kwargs)
                res = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=cfg,
                )
                return getattr(res, "text", "") or ""
            except Exception as exc:
                last_exc = exc
                err_s = str(exc)
                if any(k in err_s for m in ("429", "RESOURCE_EXHAUSTED")):
                    self._model_cooldowns[m] = time.monotonic() + 180.0
                elif any(k in err_s for m in ("503", "504", "UNAVAILABLE", "500", "overloaded")):
                    self._model_cooldowns[m] = time.monotonic() + 60.0
                logger.warning("Gemini error on model %s: %s", m, err_s[:100])
                continue

        raise last_exc or RuntimeError("All Gemini model attempts failed.")


class CentralAIService:
    """Central AI service orchestrating Groq (primary inference) and Gemini (fallback)."""

    def __init__(self):
        self.groq_provider = GroqProvider()
        self.gemini_provider = GeminiProvider()

    def generate_completion(
        self,
        prompt: str,
        system_instruction: str = "",
        response_format: str = "text",
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> Tuple[str, str]:
        """Generate text completion using Groq first, falling back to Gemini.
        Returns: (completion_text, provider_name)
        """
        if self.groq_provider.is_available():
            try:
                text = self.groq_provider.generate_completion(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    response_format=response_format,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if text and text.strip():
                    return text, "groq"
            except Exception as exc:
                logger.warning("Groq central inference failed (%s); falling back to Gemini", exc)

        if self.gemini_provider.is_available():
            try:
                text = self.gemini_provider.generate_completion(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    response_format=response_format,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if text and text.strip():
                    return text, "gemini"
            except Exception as exc:
                logger.warning("Gemini fallback inference failed: %s", exc)

        raise RuntimeError("No LLM inference providers available or all configured models failed.")


central_ai_service = CentralAIService()

