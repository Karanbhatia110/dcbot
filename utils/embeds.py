"""
Reusable embed builders for audit logs and user-facing messages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import discord

COLOR_PENDING = discord.Color.gold()
COLOR_APPROVED = discord.Color.green()
COLOR_REJECTED = discord.Color.red()
COLOR_INFO = discord.Color.blurple()
COLOR_EXPIRED = discord.Color.dark_grey()


def _fmt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return discord.utils.format_dt(dt, style="F")


def payment_verification_embed(
    *, discord_id: int, username: str, submitted_at: datetime, screenshot_url: str, status: str = "Pending"
) -> discord.Embed:
    embed = discord.Embed(
        title="💳 Payment Verification Request",
        color=COLOR_PENDING,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User", value=f"<@{discord_id}>", inline=True)
    embed.add_field(name="Discord ID", value=str(discord_id), inline=True)
    embed.add_field(name="Username", value=username, inline=True)
    embed.add_field(name="Submission Time", value=_fmt(submitted_at), inline=False)
    embed.add_field(name="Screenshot URL", value=screenshot_url, inline=False)
    embed.add_field(name="Current Status", value=status, inline=False)
    embed.set_image(url=screenshot_url)
    embed.set_footer(text="SMP Payment System")
    return embed


def audit_log_embed(
    *, title: str, description: str, color: discord.Color = COLOR_INFO, fields: Optional[dict[str, Any]] = None
) -> discord.Embed:
    embed = discord.Embed(
        title=title, description=description, color=color, timestamp=datetime.now(timezone.utc)
    )
    if fields:
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value), inline=True)
    embed.set_footer(text="ZIO Audit Log")
    return embed


def user_status_embed(user_doc: dict[str, Any]) -> discord.Embed:
    status = user_doc.get("status", "unknown")
    color = {"active": COLOR_APPROVED, "expired": COLOR_EXPIRED, "pending": COLOR_PENDING}.get(
        status, COLOR_INFO
    )

    embed = discord.Embed(title="📋 User Audit", color=color, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Username", value=user_doc.get("username", "N/A"), inline=True)
    embed.add_field(name="Discord ID", value=user_doc.get("_id", "N/A"), inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Whitelisted", value=str(user_doc.get("whitelisted", False)), inline=True)
    embed.add_field(
        name="Payment Submitted", value=str(user_doc.get("payment_submitted", False)), inline=True
    )
    embed.add_field(
        name="Payment Verified", value=str(user_doc.get("payment_verified", False)), inline=True
    )
    embed.add_field(
        name="Subscription Start", value=_fmt(user_doc.get("subscription_start")), inline=False
    )
    embed.add_field(name="Subscription End", value=_fmt(user_doc.get("subscription_end")), inline=False)

    sub_end = user_doc.get("subscription_end")
    if sub_end:
        if sub_end.tzinfo is None:
            sub_end = sub_end.replace(tzinfo=timezone.utc)
        days_remaining = (sub_end - datetime.now(timezone.utc)).days
        embed.add_field(name="Days Remaining", value=str(max(days_remaining, 0)), inline=True)
    else:
        embed.add_field(name="Days Remaining", value="N/A", inline=True)

    verified_by = user_doc.get("verified_by")
    embed.add_field(
        name="Verified By", value=f"<@{verified_by}>" if verified_by else "N/A", inline=True
    )
    return embed


def user_list_embed(title: str, users: list[dict[str, Any]], color: discord.Color = COLOR_INFO) -> discord.Embed:
    embed = discord.Embed(title=title, color=color, timestamp=datetime.now(timezone.utc))
    if not users:
        embed.description = "No users found."
        return embed

    lines = []
    for doc in users[:25]:  # Discord embed field/description limits
        end = doc.get("subscription_end")
        end_str = _fmt(end) if end else "N/A"
        lines.append(f"<@{doc.get('_id')}> — `{doc.get('username')}` — ends: {end_str}")
    embed.description = "\n".join(lines)
    if len(users) > 25:
        embed.set_footer(text=f"Showing 25 of {len(users)} users")
    return embed
