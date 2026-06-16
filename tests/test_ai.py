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


# --------------------------------------------------------------------------- #
# get_provider factory
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("provider", "base_url", "model"),
    [
        ("moonshot", "https://api.moonshot.ai/v1", "kimi-k2.6"),
        ("groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.0-flash"),
        ("openrouter", "https://openrouter.ai/api/v1", "deepseek/deepseek-chat"),
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

    @asynccontextmanager
    async def fake_scope():
        yield db_session

    monkeypatch.setattr(service, "session_scope", fake_scope)

    reply = await service.ask(1, "Привет")
    assert reply == "Привет! Чем помочь?"

    # The provider received the system prompt + the user message.
    assert captured["system"] == service.SYSTEM_PROMPT
    assert captured["messages"][-1] == {"role": "user", "content": "Привет"}

    history = await service.get_history(db_session, 1)
    assert history[-2] == {"role": "user", "content": "Привет"}
    assert history[-1] == {"role": "assistant", "content": "Привет! Чем помочь?"}
