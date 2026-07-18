"""
Data model for a SMP user record stored in MongoDB.

This is a lightweight dataclass-style helper used to build/validate the
document shape described in the spec. Motor works with plain dicts, so this
class mainly centralizes the schema and default values in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class UserRecord:
    """Mirrors the `users` collection schema."""

    _id: str  # discord user id (string)
    username: str
    status: str = "pending"  # pending | active | expired

    whitelisted: bool = True
    payment_submitted: bool = False
    payment_verified: bool = False
    payment_screenshot_url: Optional[str] = None

    subscription_start: Optional[datetime] = None
    subscription_end: Optional[datetime] = None

    verified_by: Optional[str] = None

    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def new_whitelisted(discord_id: int, username: str) -> "UserRecord":
        """Factory for a freshly-whitelisted user."""
        now = utcnow()
        return UserRecord(
            _id=str(discord_id),
            username=username,
            status="pending",
            whitelisted=True,
            payment_submitted=False,
            payment_verified=False,
            payment_screenshot_url=None,
            subscription_start=None,
            subscription_end=None,
            verified_by=None,
            created_at=now,
            updated_at=now,
        )
