"""Shared repository helpers used across modules."""
from __future__ import annotations

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_or_create_user(session: AsyncSession, tg_user: TgUser) -> User:
    """Fetch the User row for a Telegram user, creating it on first contact."""
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            full_name=tg_user.full_name,
        )
        session.add(user)
        await session.flush()
    else:
        # Keep profile fields fresh.
        changed = False
        if user.username != tg_user.username:
            user.username = tg_user.username
            changed = True
        if user.full_name != tg_user.full_name:
            user.full_name = tg_user.full_name
            changed = True
        if changed:
            await session.flush()
    return user


async def get_user_by_calendar_token(session: AsyncSession, token: str) -> User | None:
    result = await session.execute(select(User).where(User.calendar_token == token))
    return result.scalar_one_or_none()
