"""
Channel resolution utility.

Provides ``resolve_channel_id`` which checks per-guild DB settings first, then
falls back to the hardcoded default in ``config.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import discord

from config import ZIO_AUDIT_CHANNEL_NAME

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


async def resolve_audit_channel(
    db: "Database", guild: discord.Guild
) -> Optional[discord.TextChannel]:
    """Return the audit TextChannel for this guild.

    Checks per-guild DB settings first (the ``"audit"`` key saved by ``!setup``),
    then falls back to searching by the hardcoded channel name.
    """
    stored_id = await db.get_channel_id(guild.id, "audit")
    if stored_id is not None:
        ch = guild.get_channel(stored_id)
        if isinstance(ch, discord.TextChannel):
            return ch

    # Fallback: look up by the default name
    return discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)

