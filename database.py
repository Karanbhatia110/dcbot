"""
MongoDB Atlas access layer built on Motor (async PyMongo driver).

Exposes a `Database` class that wraps the `users` collection with the
specific operations the bot needs. A single instance is created in main.py
and passed to every cog via `bot.db`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.errors import PyMongoError

from config import MONGODB_URI, MONGODB_DB_NAME, USERS_COLLECTION, SUBSCRIPTION_DAYS
from models.user_model import UserRecord, utcnow
from utils.logger import get_logger

logger = get_logger(__name__)


class Database:
    """Thin async wrapper around the `users` MongoDB collection."""

    def __init__(self) -> None:
        self.client: AsyncIOMotorClient = AsyncIOMotorClient(MONGODB_URI)
        self.db = self.client[MONGODB_DB_NAME]
        self.users: AsyncIOMotorCollection = self.db[USERS_COLLECTION]

    async def connect(self) -> None:
        """Verify the connection and create indexes."""
        try:
            await self.client.admin.command("ping")
            await self.users.create_index("_id", unique=True)
            await self.users.create_index("status")
            await self.users.create_index("subscription_end")
            logger.info("Connected to MongoDB Atlas (db=%s)", MONGODB_DB_NAME)
        except PyMongoError:
            logger.exception("Failed to connect to MongoDB Atlas")
            raise

    def close(self) -> None:
        self.client.close()

    # ------------------------------------------------------------------
    # Create / read
    # ------------------------------------------------------------------
    async def create_whitelisted_user(self, discord_id: int, username: str) -> dict[str, Any]:
        """Insert a new user record on whitelist acceptance (idempotent)."""
        existing = await self.get_user(discord_id)
        if existing:
            # User re-whitelisted: keep history, just refresh username/flag.
            await self.users.update_one(
                {"_id": str(discord_id)},
                {"$set": {"username": username, "whitelisted": True, "updated_at": utcnow()}},
            )
            return await self.get_user(discord_id)  # type: ignore[return-value]

        record = UserRecord.new_whitelisted(discord_id, username)
        doc = record.to_dict()
        try:
            await self.users.insert_one(doc)
            logger.info("Created user record for %s (%s)", username, discord_id)
        except PyMongoError:
            logger.exception("Failed to insert user record for %s", discord_id)
            raise
        return doc

    async def get_user(self, discord_id: int | str) -> Optional[dict[str, Any]]:
        try:
            return await self.users.find_one({"_id": str(discord_id)})
        except PyMongoError:
            logger.exception("Failed to fetch user %s", discord_id)
            return None

    async def get_users_by_status(self, status: str) -> list[dict[str, Any]]:
        try:
            cursor = self.users.find({"status": status})
            return [doc async for doc in cursor]
        except PyMongoError:
            logger.exception("Failed to fetch users with status=%s", status)
            return []

    async def get_pending_verification_users(self) -> list[dict[str, Any]]:
        """Users who submitted a payment screenshot but are not yet verified/rejected."""
        try:
            cursor = self.users.find(
                {"payment_submitted": True, "payment_verified": False, "status": "pending"}
            )
            return [doc async for doc in cursor]
        except PyMongoError:
            logger.exception("Failed to fetch pending-verification users")
            return []

    async def get_active_subscriptions(self) -> list[dict[str, Any]]:
        return await self.get_users_by_status("active")

    # ------------------------------------------------------------------
    # Payment submission
    # ------------------------------------------------------------------
    async def record_payment_submission(
        self, discord_id: int, username: str, screenshot_url: str
    ) -> None:
        try:
            await self.users.update_one(
                {"_id": str(discord_id)},
                {
                    "$set": {
                        "username": username,
                        "payment_submitted": True,
                        "payment_screenshot_url": screenshot_url,
                        "updated_at": utcnow(),
                    }
                },
                upsert=False,
            )
            logger.info("Recorded payment submission for %s", discord_id)
        except PyMongoError:
            logger.exception("Failed to record payment submission for %s", discord_id)
            raise

    # ------------------------------------------------------------------
    # Approve / reject
    # ------------------------------------------------------------------
    async def approve_payment(self, discord_id: int, admin_id: int) -> dict[str, Any]:
        now = utcnow()
        end = now + timedelta(days=SUBSCRIPTION_DAYS)
        update = {
            "payment_verified": True,
            "status": "active",
            "subscription_start": now,
            "subscription_end": end,
            "verified_by": str(admin_id),
            "updated_at": now,
        }
        try:
            await self.users.update_one({"_id": str(discord_id)}, {"$set": update})
            logger.info("Approved payment for %s by admin %s", discord_id, admin_id)
        except PyMongoError:
            logger.exception("Failed to approve payment for %s", discord_id)
            raise
        return await self.get_user(discord_id)  # type: ignore[return-value]

    async def reject_payment(self, discord_id: int, admin_id: int) -> dict[str, Any]:
        now = utcnow()
        update = {
            "payment_verified": False,
            "payment_submitted": False,
            "status": "pending",
            "verified_by": str(admin_id),
            "updated_at": now,
        }
        try:
            await self.users.update_one({"_id": str(discord_id)}, {"$set": update})
            logger.info("Rejected payment for %s by admin %s", discord_id, admin_id)
        except PyMongoError:
            logger.exception("Failed to reject payment for %s", discord_id)
            raise
        return await self.get_user(discord_id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Renewal / expiry
    # ------------------------------------------------------------------
    async def renew_subscription(self, discord_id: int, admin_id: int) -> dict[str, Any]:
        now = utcnow()
        user = await self.get_user(discord_id)
        current_end = None
        if user and user.get("subscription_end"):
            current_end = user["subscription_end"]
            if current_end.tzinfo is None:
                current_end = current_end.replace(tzinfo=timezone.utc)

        # Extend from the later of "now" or current expiry, so renewing early
        # doesn't lose remaining days.
        base = current_end if (current_end and current_end > now) else now
        new_end = base + timedelta(days=SUBSCRIPTION_DAYS)

        update = {
            "status": "active",
            "subscription_start": user.get("subscription_start") or now if user else now,
            "subscription_end": new_end,
            "verified_by": str(admin_id),
            "updated_at": now,
        }
        try:
            await self.users.update_one({"_id": str(discord_id)}, {"$set": update})
            logger.info("Renewed subscription for %s by admin %s", discord_id, admin_id)
        except PyMongoError:
            logger.exception("Failed to renew subscription for %s", discord_id)
            raise
        return await self.get_user(discord_id)  # type: ignore[return-value]

    async def expire_subscription(self, discord_id: int) -> None:
        try:
            await self.users.update_one(
                {"_id": str(discord_id)},
                {"$set": {"status": "expired", "updated_at": utcnow()}},
            )
            logger.info("Marked subscription expired for %s", discord_id)
        except PyMongoError:
            logger.exception("Failed to mark subscription expired for %s", discord_id)
            raise

    async def mark_reminder_sent(self, discord_id: int, days_before: int) -> None:
        """Track which reminder thresholds have already been sent to avoid duplicates."""
        field_name = f"reminder_{days_before}d_sent_at"
        try:
            await self.users.update_one(
                {"_id": str(discord_id)},
                {"$set": {field_name: utcnow(), "updated_at": utcnow()}},
            )
        except PyMongoError:
            logger.exception("Failed to mark reminder sent for %s", discord_id)
