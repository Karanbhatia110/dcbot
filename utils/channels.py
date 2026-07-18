"""
Channel resolution utility.

Provides ``resolve_channel_id`` which checks per-guild DB settings first, then
falls back to the hardcoded default in ``config.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from database import Database


async def resolve_channel_id(
    db: "Database", guild_id: int, key: str, fallback: int
) -> int:
    """Return the channel/category ID for *key*, preferring DB, falling back to *fallback*.

    Parameters
    ----------
    db:
        The bot's ``Database`` instance.
    guild_id:
        Discord guild ID.
    key:
        Setting key, e.g. ``"payment_gateway"``, ``"whitelisting"``, ``"category"``.
    fallback:
        The default config constant to use when no DB override exists.
    """
    stored = await db.get_channel_id(guild_id, key)
    return stored if stored is not None else fallback
