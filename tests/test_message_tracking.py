"""Tests for bot message tracking patching."""
from __future__ import annotations

import pytest

from app.bot import message_tracking
from app.bot.message_tracking import (
    _TRACKED_METHODS,
    patch_bot_for_message_tracking,
)


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict]] = []

    async def send_message(self, chat_id, **kwargs):
        self.calls.append(("send_message", chat_id, kwargs))
        return None

    async def send_photo(self, chat_id, **kwargs):
        self.calls.append(("send_photo", chat_id, kwargs))
        return None

    async def send_video(self, chat_id, **kwargs):
        self.calls.append(("send_video", chat_id, kwargs))
        return None

    async def send_audio(self, chat_id, **kwargs):
        self.calls.append(("send_audio", chat_id, kwargs))
        return None

    async def send_voice(self, chat_id, **kwargs):
        self.calls.append(("send_voice", chat_id, kwargs))
        return None

    async def send_document(self, chat_id, **kwargs):
        self.calls.append(("send_document", chat_id, kwargs))
        return None


def test_fake_bot_defines_all_tracked_methods() -> None:
    bot = FakeBot()
    for method_name in _TRACKED_METHODS:
        assert callable(getattr(bot, method_name))


@pytest.mark.asyncio
async def test_send_photo_passes_chat_id_through() -> None:
    bot = FakeBot()
    patch_bot_for_message_tracking(bot)

    result = await bot.send_photo(123, photo="abc")

    assert result is None
    assert bot.calls == [("send_photo", 123, {"photo": "abc"})]
    method, chat_id, kwargs = bot.calls[0]
    assert chat_id == 123
    assert kwargs == {"photo": "abc"}


@pytest.mark.asyncio
async def test_send_message_passes_chat_id_through() -> None:
    bot = FakeBot()
    patch_bot_for_message_tracking(bot)

    await bot.send_message(456, text="hello")

    method, chat_id, kwargs = bot.calls[0]
    assert method == "send_message"
    assert chat_id == 456
    assert kwargs == {"text": "hello"}


@pytest.mark.asyncio
async def test_patch_is_idempotent(monkeypatch) -> None:
    bot = FakeBot()
    patch_bot_for_message_tracking(bot)
    wrapped_once = bot.send_photo

    patch_bot_for_message_tracking(bot)
    wrapped_twice = bot.send_photo

    assert bot._message_tracking_patched is True
    assert wrapped_once is wrapped_twice

    await bot.send_photo(123, photo="abc")
    assert bot.calls == [("send_photo", 123, {"photo": "abc"})]


@pytest.mark.asyncio
async def test_track_bot_message_not_called_when_result_is_none(monkeypatch) -> None:
    called = False

    async def fake_track(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(message_tracking, "track_bot_message", fake_track)

    bot = FakeBot()
    patch_bot_for_message_tracking(bot)
    await bot.send_photo(123, photo="abc")

    assert called is False
