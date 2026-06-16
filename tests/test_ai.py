"""Tests for the AI chat module.

Covers:
  * the ``get_provider`` factory mapping (base_url + default model) and the
    ``LLM_MODEL`` override, using a lightweight settings stand-in object;
  * conversation history persistence (trimming + reset) and the full ``ask``
    turn against an isolated in-memory SQLite database with a stub provider.

No real network calls are made.
"""
from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import models  # noqa: F401 - ensure tables are registered on Base.metadata
from app.db.base import Base
from app.db.models import User
from app.modules.ai import service
from app.modules.ai.providers import AIError, OpenAICompatibleProvider, get_provider


@dataclasses.dataclass
class FakeSettings:
    """Minimal stand-in exposing only the attributes ``get_provider`` / service use."""

    llm_provider: str = "moonshot"
    llm_api_key: str = "test-key"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_request_timeout: int = 60
    llm_max_history_messages: int = 20
    # Web search: defaults chosen so NO real network call is ever attempted in
    # tests (tavily provider with an empty key short-circuits to no results).
    web_search_enabled: bool = False
    web_search_provider: str = "tavily"
    web_search_max_results: int = 5
    tavily_api_key: str = ""


# --------------------------------------------------------------------------- #
# get_provider factory
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("provider", "base_url", "model"),
    [
        ("moonshot", "https://api.moonshot.ai/v1", "kimi-k2.6"),
        ("groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
        ("openrouter", "https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free"),
    ],
)
def test_get_provider_defaults(provider: str, base_url: str, model: str) -> None:
    p = get_provider(FakeSettings(llm_provider=provider))
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.name == provider
    assert p.base_url == base_url
    assert p.model == model


def test_get_provider_model_override() -> None:
    p = get_provider(FakeSettings(llm_provider="moonshot", llm_model="kimi-k2.7-code"))
    assert p.base_url == "https://api.moonshot.ai/v1"
    assert p.model == "kimi-k2.7-code"


def test_get_provider_openai_compatible_uses_base_url() -> None:
    p = get_provider(
        FakeSettings(
            llm_provider="openai_compatible",
            llm_base_url="https://example.test/v1",
            llm_model="local-model",
        )
    )
    assert p.name == "openai_compatible"
    assert p.base_url == "https://example.test/v1"
    assert p.model == "local-model"


def test_get_provider_unknown_falls_back_to_moonshot() -> None:
    p = get_provider(FakeSettings(llm_provider="does-not-exist"))
    assert p.name == "moonshot"
    assert p.base_url == "https://api.moonshot.ai/v1"


async def test_chat_missing_key_raises_ai_error() -> None:
    p = get_provider(FakeSettings(llm_provider="moonshot", llm_api_key=""))
    with pytest.raises(AIError):
        await p.chat([{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------- #
# service history / reset / ask
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(User(id=1, username="tester", full_name="Tester"))
        await session.commit()
        yield session
    await engine.dispose()


async def test_history_trimming_and_reset(db_session, monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: FakeSettings(llm_max_history_messages=4))

    for i in range(10):
        await service.append_and_save(db_session, 1, "user", f"m{i}")

    history = await service.get_history(db_session, 1)
    assert len(history) == 4
    assert history[0]["content"] == "m6"
    assert history[-1]["content"] == "m9"

    await service.reset(db_session, 1)
    assert await service.get_history(db_session, 1) == []


async def test_ask_full_turn_with_stub_provider(db_session, monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: FakeSettings(llm_max_history_messages=20))

    captured: dict = {}

    class StubProvider:
        name = "stub"
        model = "stub-model"

        async def chat(self, messages, *, system=None):
            captured["messages"] = messages
            captured["system"] = system
            return "Привет! Чем помочь?"

    monkeypatch.setattr(service, "get_provider", lambda settings: StubProvider())
    monkeypatch.setattr(service, "search_web", lambda *args, **kwargs: [])

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    monkeypatch.setattr(service, "session_scope", fake_scope)

    reply, used_web = await service.ask(1, "Привет", web_enabled=False)
    assert reply == "Привет! Чем помочь?"
    assert used_web is False

    # The provider received the system prompt + the user message.
    assert captured["system"] == service.SYSTEM_PROMPT_OFFLINE
    assert captured["messages"][-1] == {"role": "user", "content": "Привет"}

    history = await service.get_history(db_session, 1)
    assert history[-2] == {"role": "user", "content": "Привет"}
    assert history[-1] == {"role": "assistant", "content": "Привет! Чем помочь?"}


async def test_ask_with_web_search_context(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: FakeSettings(llm_max_history_messages=20, web_search_enabled=True),
    )

    captured: dict = {}

    class StubProvider:
        name = "stub"
        model = "stub-model"

        async def chat(self, messages, *, system=None):
            captured["system"] = system
            return "Сейчас +5°C."

    async def fake_search(query, settings):
        from app.modules.ai.web_search import SearchResult

        return [
            SearchResult(
                title="Weather",
                url="https://example.com/weather",
                snippet="Moscow +5C",
            )
        ]

    monkeypatch.setattr(service, "get_provider", lambda settings: StubProvider())
    monkeypatch.setattr(service, "search_web", fake_search)

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    monkeypatch.setattr(service, "session_scope", fake_scope)

    reply, used_web = await service.ask(1, "Какая погода?", web_enabled=True)
    assert used_web is True
    assert reply == "Сейчас +5°C."
    assert "Weather" in captured["system"]
    assert "https://example.com/weather" in captured["system"]


async def test_ask_web_enabled_but_search_fails_still_replies(db_session, monkeypatch) -> None:
    """A failing web search must never break the turn — answer offline instead."""
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: FakeSettings(llm_max_history_messages=20, web_search_enabled=True),
    )

    captured: dict = {}

    class StubProvider:
        name = "stub"
        model = "stub-model"

        async def chat(self, messages, *, system=None):
            captured["system"] = system
            return "Ответ без интернета."

    async def boom(query, settings):
        raise RuntimeError("search backend exploded")

    monkeypatch.setattr(service, "get_provider", lambda settings: StubProvider())
    monkeypatch.setattr(service, "search_web", boom)

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    monkeypatch.setattr(service, "session_scope", fake_scope)

    reply, used_web = await service.ask(1, "Какая погода?", web_enabled=True)
    assert reply == "Ответ без интернета."
    assert used_web is False
    assert captured["system"] == service.SYSTEM_PROMPT_OFFLINE
