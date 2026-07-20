"""
Payments cog.

Monitors the existing #payment-confirmation channel for image attachments.
When a whitelisted user uploads a screenshot, the bot records the submission
in MongoDB, DMs the user an acknowledgement, and posts a verification
request embed (with Approve/Reject buttons) into #zio-audit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from config import PAYMENT_CONFIRMATION_CHANNEL_ID, ZIO_AUDIT_CHANNEL_NAME
from utils.channels import resolve_channel_id, resolve_audit_channel
from utils.embeds import payment_verification_embed
from utils.logger import get_logger
from views.payment_buttons import PaymentVerificationView

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


class PaymentsCog(commands.Cog):
    def __init__(self, bot: "SMPBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return

        # Resolve the payment-confirmation channel dynamically
        expected_channel_id = await resolve_channel_id(
            self.bot.db, message.guild.id, "payment_confirmation", PAYMENT_CONFIRMATION_CHANNEL_ID
        )
        if message.channel.id != expected_channel_id:
            return
        if not message.attachments:
            return

        image_attachments = [
            a for a in message.attachments if (a.content_type or "").startswith("image/")
            or a.filename.lower().endswith(IMAGE_EXTENSIONS)
        ]
        if not image_attachments:
            return

        guild = message.guild
        if guild is None:
            return

        user_doc = await self.bot.db.get_user(message.author.id)
        if user_doc is None:
            try:
                await message.reply(
                    "⚠️ You are not on the whitelist yet. Please wait for an admin to accept your "
                    "application before submitting payment.",
                    mention_author=True,
                )
            except discord.HTTPException:
                pass
            return

        screenshot_url = image_attachments[0].url
        submitted_at = datetime.now(timezone.utc)

        await self.bot.db.record_payment_submission(
            discord_id=message.author.id,
            username=str(message.author),
            screenshot_url=screenshot_url,
        )

        try:
            await message.author.send(
                "📨 Payment screenshot received.\nStaff will verify your payment shortly."
            )
        except discord.Forbidden:
            logger.warning("Could not DM user %s (DMs closed)", message.author.id)

        audit_channel = await resolve_audit_channel(self.bot.db, guild)
        if audit_channel is None:
            logger.error("Audit channel not found; cannot post verification request")
            return

        embed = payment_verification_embed(
            discord_id=message.author.id,
            username=str(message.author),
            submitted_at=submitted_at,
            screenshot_url=screenshot_url,
        )
        view = PaymentVerificationView(self.bot)
        try:
            await audit_channel.send(embed=embed, view=view)
        except discord.HTTPException:
            logger.exception("Failed to send verification request for %s", message.author.id)

        logger.info("Payment submitted by %s", message.author.id)

        try:
            await message.add_reaction("✅")
        except discord.HTTPException:
            pass


async def setup(bot: "SMPBot") -> None:
    await bot.add_cog(PaymentsCog(bot))
