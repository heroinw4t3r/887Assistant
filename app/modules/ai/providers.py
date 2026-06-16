"""LLM provider abstraction.

CONTRACT:
    class LLMProvider(Protocol):
        name: str
        async def chat(self, messages: list[dict], *, system: str | None = None) -> str: ...

    def get_provider(settings) -> LLMProvider
        Factory selecting the provider from settings.llm_provider.

Supported providers (all OpenAI-compatible chat/completions unless noted):
  * moonshot          -> https://api.moonshot.ai/v1   (Kimi: kimi-k2.6 default; also kimi-k2.7-code)
  * openrouter        -> https://openrouter.ai/api/v1 (free models incl. some Kimi)
  * groq              -> https://api.groq.com/openai/v1
  * gemini            -> https://generativelanguage.googleapis.com/v1beta/openai
  * openai_compatible -> uses LLM_BASE_URL
"""
from __future__ import annotations

from typing import Protocol

import httpx


class AIError(Exception):
    """A user-facing error from the LLM layer.

    The message is safe (and intended) to be shown directly to the end user.
    """


class LLMProvider(Protocol):
    name: str

    async def chat(self, messages: list[dict], *, system: str | None = None) -> str:
        ...


class OpenAICompatibleProvider:
    """Thin async client for any OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self, *, name: str, base_url: str, api_key: str, model: str, timeout: float
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        # Lazily-created, reused across calls to avoid the cost of opening a new
        # connection pool on every request.
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying reused HTTP client, if any."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def chat(self, messages: list[dict], *, system: str | None = None) -> str:
        if not self.api_key:
            raise AIError(
                "Ключ API не задан. Установите переменную окружения LLM_API_KEY "
                "(и при необходимости LLM_PROVIDER / LLM_MODEL)."
            )
        if not self.base_url:
            raise AIError(
                "Не задан адрес API. Для провайдера openai_compatible установите LLM_BASE_URL."
            )

        payload_messages: list[dict] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        body = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": 0.6,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        try:
            client = self._get_client()
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise AIError(
                "Нейросеть слишком долго не отвечает. Попробуйте ещё раз чуть позже."
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise AIError(
                    "Ключ API отклонён (401/403). Проверьте LLM_API_KEY и права доступа."
                ) from exc
            if status == 429:
                raise AIError(
                    "Превышен лимит запросов к нейросети (429). Подождите немного и повторите."
                ) from exc
            raise AIError(
                f"Сервис нейросети вернул ошибку (HTTP {status}). Попробуйте позже."
            ) from exc
        except httpx.HTTPError as exc:
            raise AIError(
                "Не удалось связаться с сервисом нейросети. Проверьте подключение и настройки."
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("Нейросеть вернула неожиданный ответ. Попробуйте ещё раз.") from exc

        if content is None:
            raise AIError("Нейросеть вернула пустой ответ. Попробуйте переформулировать запрос.")
        return str(content)


# provider name -> (base_url, default_model)
_PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "moonshot": ("https://api.moonshot.ai/v1", "kimi-k2.6"),
    "openrouter": (
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct:free",
    ),
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
}


def get_provider(settings) -> LLMProvider:
    """Build an :class:`LLMProvider` from ``settings``.

    ``settings.llm_model`` (if set) overrides the per-provider default model.
    An unknown provider falls back to ``moonshot``. The provider is constructed
    even when the API key is missing; ``chat()`` raises :class:`AIError` in that
    case so the user gets a friendly hint to set ``LLM_API_KEY``.
    """
    name = (getattr(settings, "llm_provider", "") or "moonshot").strip().lower()

    if name == "openai_compatible":
        base_url = getattr(settings, "llm_base_url", "") or ""
        default_model = "gpt-3.5-turbo"
    else:
        if name not in _PROVIDER_DEFAULTS:
            name = "moonshot"
        base_url, default_model = _PROVIDER_DEFAULTS[name]

    model = (getattr(settings, "llm_model", "") or "").strip() or default_model

    return OpenAICompatibleProvider(
        name=name,
        base_url=base_url,
        api_key=getattr(settings, "llm_api_key", "") or "",
        model=model,
        timeout=getattr(settings, "llm_request_timeout", 60),
    )
