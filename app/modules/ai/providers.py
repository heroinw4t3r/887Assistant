"""LLM provider abstraction.

CONTRACT:
    class LLMProvider(Protocol):
        name: str
        async def chat(self, messages: list[dict], *, system: str | None = None) -> str: ...

    def get_provider(settings) -> LLMProvider
        Factory selecting the provider from settings.llm_provider.

Supported providers (all OpenAI-compatible chat/completions unless noted):
  * moonshot  -> https://api.moonshot.ai/v1   (Kimi: kimi-k2.6 default; kimi-k2.7-code, kimi-k2.5)
  * openrouter-> https://openrouter.ai/api/v1 (free models incl. some Kimi)
  * groq      -> https://api.groq.com/openai/v1
  * gemini    -> https://generativelanguage.googleapis.com/v1beta/openai
  * openai_compatible -> uses LLM_BASE_URL

TODO(subagent-3): implement the factory + an httpx-based OpenAI-compatible client.
"""
from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    name: str

    async def chat(self, messages: list[dict], *, system: str | None = None) -> str:
        ...
