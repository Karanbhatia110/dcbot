"""
Subscriptions cog.

Handles:
- /renew admin command: extends a user's subscription by 30 days.
- A daily APScheduler job that sends expiry reminders (7/3/1 days out) and
  expires subscriptions (removing only the "MINECRAFT" role) once they lapse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from cogs.whitelist import is_admin
from config import ROLE_MINECRAFT, REMINDER_DAYS_BEFORE_EXPIRY, ZIO_AUDIT_CHANNEL_NAME, GUILD_ID
from utils.embeds import audit_log_embed, user_status_embed, COLOR_INFO, COLOR_EXPIRED
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)


class SubscriptionsCog(commands.Cog):
    def __init__(self, bot: "SMPBot") -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")

    async def cog_load(self) -> None:
        # Runs once daily at 00:05 UTC. Adjust the cron trigger as needed.
        self.scheduler.add_job(
            self._run_daily_check,
            CronTrigger(hour=0, minute=5),
            id="daily_subscription_check",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        self.scheduler.start()
        logger.info("Subscription scheduler started (daily at 00:05 UTC)")

    async def cog_unload(self) -> None:
        self.scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------
    # /renew
    # ------------------------------------------------------------------
    @app_commands.command(name="renew", description="Renew a user's SMP subscription by 30 days.")
    @app_commands.describe(user="The user whose subscription to renew")
    @is_admin()
    async def renew(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        assert guild is not None

        existing = await self.bot.db.get_user(user.id)
        if existing is None:
            await interaction.followup.send(
                f"❌ {user.mention} has no record. Use /whitelist_accept first.", ephemeral=True
            )
            return

        minecraft_role = discord.utils.get(guild.roles, name=ROLE_MINECRAFT)
        if minecraft_role and minecraft_role not in user.roles:
            try:
                await user.add_roles(minecraft_role, reason="Subscription renewed")
            except discord.Forbidden:
                logger.exception("Missing permission to add '%s' to %s", ROLE_MINECRAFT, user.id)

        doc = await self.bot.db.renew_subscription(user.id, interaction.user.id)

        try:
            await user.send(
                "🔄 Your SMP subscription has been renewed for another 30 days. Thanks for staying!"
            )
        except discord.Forbidden:
            logger.warning("Could not DM user %s (DMs closed)", user.id)

        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        if audit_channel:
            embed = audit_log_embed(
                title="🔄 Subscription Renewed",
                description=f"{user.mention}'s subscription was renewed.",
                color=COLOR_INFO,
                fields={"Admin": interaction.user.mention, "New Expiry": doc.get("subscription_end")},
            )
            await audit_channel.send(embed=embed)

        logger.info("Subscription renewed for %s by %s", user.id, interaction.user.id)
        await interaction.followup.send(embed=user_status_embed(doc), ephemeral=True)

    # ------------------------------------------------------------------
    # Scheduled job
    # ------------------------------------------------------------------
    async def _run_daily_check(self) -> None:
        logger.info("Running daily subscription check")
        try:
            guild = self._get_guild()
            if guild is None:
                logger.error("Could not resolve guild for scheduled subscription check")
                return

            active_users = await self.bot.db.get_active_subscriptions()
            now = datetime.now(timezone.utc)

            for doc in active_users:
                sub_end = doc.get("subscription_end")
                if sub_end is None:
                    continue
                if sub_end.tzinfo is None:
                    sub_end = sub_end.replace(tzinfo=timezone.utc)

                days_remaining = (sub_end - now).days

                if sub_end <= now:
                    await self._expire_user(guild, doc)
                    continue

                if days_remaining in REMINDER_DAYS_BEFORE_EXPIRY:
                    await self._maybe_send_reminder(doc, days_remaining)

        except Exception:  # noqa: BLE001 - scheduler jobs must never crash silently
            logger.exception("Scheduler error during daily subscription check")

    def _get_guild(self) -> discord.Guild | None:
        if GUILD_ID is not None:
            guild = self.bot.get_guild(GUILD_ID)
            if guild:
                return guild
        # Fallback: single-guild bots can just use the first cached guild.
        return self.bot.guilds[0] if self.bot.guilds else None

    async def _maybe_send_reminder(self, doc: dict, days_remaining: int) -> None:
        discord_id = int(doc["_id"])
        already_sent_field = f"reminder_{days_remaining}d_sent_at"
        if doc.get(already_sent_field):
            return  # Already sent for this threshold.

        messages = {
            7: "⏰ Your SMP subscription expires in 7 days.\nRenew to continue playing.",
            3: "⏰ Your SMP subscription expires in 3 days.",
            1: "⏰ Your SMP subscription expires tomorrow.",
        }
        message = messages.get(days_remaining)
        if not message:
            return

        user = self.bot.get_user(discord_id) or await self._safe_fetch_user(discord_id)
        if user:
            try:
                await user.send(message)
                logger.info("Sent %s-day expiry reminder to %s", days_remaining, discord_id)
            except discord.Forbidden:
                logger.warning("Could not DM user %s (DMs closed)", discord_id)

        await self.bot.db.mark_reminder_sent(discord_id, days_remaining)

    async def _expire_user(self, guild: discord.Guild, doc: dict) -> None:
        discord_id = int(doc["_id"])
        minecraft_role = discord.utils.get(guild.roles, name=ROLE_MINECRAFT)

        member = guild.get_member(discord_id) or await self._safe_fetch_member(guild, discord_id)
        if member is not None and minecraft_role is not None and minecraft_role in member.roles:
            try:
                await member.remove_roles(minecraft_role, reason="Subscription expired")
            except discord.Forbidden:
                logger.exception("Missing permission to remove '%s' from %s", ROLE_MINECRAFT, discord_id)

        await self.bot.db.expire_subscription(discord_id)

        if member is not None:
            try:
                await member.send(
                    "⏳ Your SMP subscription has expired.\nRenew payment to regain access."
                )
            except discord.Forbidden:
                logger.warning("Could not DM user %s (DMs closed)", discord_id)

        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        if audit_channel:
            embed = audit_log_embed(
                title="⏳ Subscription Expired",
                description=f"<@{discord_id}>'s subscription has expired. `{ROLE_MINECRAFT}` role removed.",
                color=COLOR_EXPIRED,
            )
            await audit_channel.send(embed=embed)

        logger.info("Subscription expired for %s", discord_id)

    async def _safe_fetch_member(self, guild: discord.Guild, user_id: int) -> discord.Member | None:
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
        except discord.HTTPException:
            logger.exception("Failed to fetch member %s", user_id)
            return None

    async def _safe_fetch_user(self, user_id: int) -> discord.User | None:
        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            logger.exception("Failed to fetch user %s", user_id)
            return None


async def setup(bot: "SMPBot") -> None:
    await bot.add_cog(SubscriptionsCog(bot))
