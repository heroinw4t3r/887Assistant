"""ORM models — the shared data contract between all modules.

Tables:
  users                  -- Telegram users known to the bot (+ per-user calendar feed token)
  file_folders           -- user-created folders for the files module
  files                  -- stored file metadata (content on disk and/or Telegram file_id)
  bot_chat_messages      -- bot message ids for per-chat cleanup
  events                 -- calendar events
  ai_sessions            -- per-user AI chat conversation state
  faceit_nick_cache      -- persistent FACEIT nickname availability cache

Subagents MUST treat these schemas as fixed contracts. If a column is missing for
a feature, add it here (and only here) and keep it backward compatible.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_token() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    # Telegram user id is the primary key.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    # Secret token used to build the personal .ics / webcal subscription URL.
    calendar_token: Mapped[str] = mapped_column(
        String(64), default=_new_token, unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    files: Mapped[list[StoredFile]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    folders: Mapped[list[FileFolder]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    events: Mapped[list[CalendarEvent]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class FileFolder(Base):
    __tablename__ = "file_folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("file_folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="folders")
    files: Mapped[list[StoredFile]] = relationship(back_populates="folder")


class StoredFile(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folder_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("file_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Telegram file_id is always stored so files can be re-sent without local storage.
    telegram_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    # Local path is only set when the file was small enough to download.
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Where the blob lives: "telegram" | "local" | "s3".
    storage_backend: Mapped[str] = mapped_column(String(16), default="telegram", nullable=False)
    # Object key in S3 (or relative path); NULL when only a Telegram file_id is kept.
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # "document" | "photo" | "video" | "audio" | "voice" | ...
    kind: Mapped[str] = mapped_column(String(32), default="document", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="files")
    folder: Mapped[FileFolder | None] = relationship(back_populates="files")


class BotChatMessage(Base):
    __tablename__ = "bot_chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CalendarEvent(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stored in UTC.
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Minutes before start_at to send a reminder; NULL = no reminder.
    reminder_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Stable UID for the iCalendar VEVENT.
    uid: Mapped[str] = mapped_column(String(64), default=_new_token, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="events")


class AISession(Base):
    __tablename__ = "ai_sessions"

    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # JSON-encoded list of {"role": "...", "content": "..."} messages (no system prompt).
    messages_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class FaceitNickCache(Base):
    __tablename__ = "faceit_nick_cache"

    nickname: Mapped[str] = mapped_column(String(128), primary_key=True)  # case-sensitive
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # "taken" | "free"
    player_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
