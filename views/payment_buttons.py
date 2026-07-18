"""
Persistent Discord UI View for the payment verification audit embed.

Contains the "Approve Payment" and "Reject Payment" buttons that admins use
in #zio-audit. The view is persistent (timeout=None, static custom_ids) so
it keeps working after bot restarts, and the target user's Discord ID is
encoded in the custom_id so a single registered view instance can handle
every embed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import ROLE_MINECRAFT_ADMIN, ROLE_MINECRAFT, ROLE_WHITELISTED, ZIO_AUDIT_CHANNEL_NAME
from utils.embeds import audit_log_embed, COLOR_APPROVED, COLOR_REJECTED
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)


def _get_admin_role(guild: discord.Guild) -> discord.Role | None:
    return discord.utils.get(guild.roles, name=ROLE_MINECRAFT_ADMIN)


async def _is_admin(interaction: discord.Interaction) -> bool:
    assert interaction.guild is not None
    admin_role = _get_admin_role(interaction.guild)
    if admin_role is None:
        logger.error("Role '%s' not found in guild %s", ROLE_MINECRAFT_ADMIN, interaction.guild.id)
        await interaction.response.send_message(
            f"⚠️ The `{ROLE_MINECRAFT_ADMIN}` role could not be found. Please contact a server owner.",
            ephemeral=True,
        )
        return False

    member = interaction.user
    if not isinstance(member, discord.Member) or admin_role not in member.roles:
        await interaction.response.send_message(
            "❌ Only `MINECRAFT ADMIN` can use this button.", ephemeral=True
        )
        return False
    return True


async def _notify_admins_missing_role(bot: "SMPBot", guild: discord.Guild, role_name: str) -> None:
    audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
    if audit_channel is None:
        return
    try:
        await audit_channel.send(
            f"⚠️ Role `{role_name}` is missing from this server. It was not created automatically. "
            f"Please create it manually."
        )
    except discord.HTTPException:
        logger.exception("Failed to notify admins about missing role %s", role_name)


class PaymentVerificationView(discord.ui.View):
    """Registered once as a persistent view in `main.py`."""

    def __init__(self, bot: "SMPBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @staticmethod
    def build_custom_ids(discord_id: int) -> tuple[str, str]:
        return f"payment_approve:{discord_id}", f"payment_reject:{discord_id}"

    @discord.ui.button(
        label="Approve Payment", style=discord.ButtonStyle.success, emoji="✅", custom_id="payment_approve"
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle(interaction, approve=True)

    @discord.ui.button(
        label="Reject Payment", style=discord.ButtonStyle.danger, emoji="❌", custom_id="payment_reject"
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle(interaction, approve=False)

    async def _handle(self, interaction: discord.Interaction, *, approve: bool) -> None:
        if not await _is_admin(interaction):
            return

        assert interaction.guild is not None
        guild = interaction.guild

        # The target user's ID is embedded in the original embed (Discord ID field),
        # since a single static custom_id is shared by every audit message.
        target_id = self._extract_target_id(interaction)
        if target_id is None:
            await interaction.response.send_message(
                "❌ Could not determine which user this action applies to.", ephemeral=True
            )
            return

        member = guild.get_member(target_id) or await self._safe_fetch_member(guild, target_id)

        if approve:
            await self._approve_flow(interaction, guild, member, target_id)
        else:
            await self._reject_flow(interaction, guild, member, target_id)

    @staticmethod
    async def _safe_fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
        except discord.HTTPException:
            logger.exception("Failed to fetch member %s", user_id)
            return None

    @staticmethod
    def _extract_target_id(interaction: discord.Interaction) -> int | None:
        if not interaction.message or not interaction.message.embeds:
            return None
        embed = interaction.message.embeds[0]
        for field in embed.fields:
            if field.name == "Discord ID":
                try:
                    return int(field.value)
                except (TypeError, ValueError):
                    return None
        return None

    async def _approve_flow(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        member: discord.Member | None,
        target_id: int,
    ) -> None:
        await interaction.response.defer()

        minecraft_role = discord.utils.get(guild.roles, name=ROLE_MINECRAFT)
        whitelisted_role = discord.utils.get(guild.roles, name=ROLE_WHITELISTED)

        if minecraft_role is None:
            logger.error("Role '%s' not found in guild %s", ROLE_MINECRAFT, guild.id)
            await _notify_admins_missing_role(self.bot, guild, ROLE_MINECRAFT)
            await interaction.followup.send(
                f"⚠️ Role `{ROLE_MINECRAFT}` not found. Approval aborted.", ephemeral=True
            )
            return

        if member is not None:
            try:
                await member.add_roles(minecraft_role, reason="Payment approved")
                if whitelisted_role and whitelisted_role not in member.roles:
                    await member.add_roles(whitelisted_role, reason="Ensure whitelisted role retained")
            except discord.Forbidden:
                logger.exception("Missing permissions to add roles to %s", target_id)

        user_doc = await self.bot.db.approve_payment(target_id, interaction.user.id)

        if member is not None:
            try:
                await member.send(
                    "✅ Payment verified.\nYou now have access to the SMP. "
                    "Check the server-ip and modpack channels."
                )
            except discord.Forbidden:
                logger.warning("Could not DM user %s (DMs closed)", target_id)

        await self._update_embed_status(interaction, "✅ Approved", COLOR_APPROVED)

        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        if audit_channel is not None:
            embed = audit_log_embed(
                title="✅ Payment Approved",
                description=f"<@{target_id}>'s payment was approved.",
                color=COLOR_APPROVED,
                fields={
                    "Admin": interaction.user.mention,
                    "Subscription End": user_doc.get("subscription_end"),
                },
            )
            await audit_channel.send(embed=embed)

        logger.info("Payment approved for %s by %s", target_id, interaction.user.id)

    async def _reject_flow(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        member: discord.Member | None,
        target_id: int,
    ) -> None:
        await interaction.response.defer()

        await self.bot.db.reject_payment(target_id, interaction.user.id)

        if member is not None:
            try:
                await member.send("❌ Your payment could not be verified.\nPlease contact staff.")
            except discord.Forbidden:
                logger.warning("Could not DM user %s (DMs closed)", target_id)

        await self._update_embed_status(interaction, "❌ Rejected", COLOR_REJECTED)

        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        if audit_channel is not None:
            embed = audit_log_embed(
                title="❌ Payment Rejected",
                description=f"<@{target_id}>'s payment was rejected.",
                color=COLOR_REJECTED,
                fields={"Admin": interaction.user.mention},
            )
            await audit_channel.send(embed=embed)

        logger.info("Payment rejected for %s by %s", target_id, interaction.user.id)

    @staticmethod
    async def _update_embed_status(
        interaction: discord.Interaction, status_text: str, color: discord.Color
    ) -> None:
        if not interaction.message or not interaction.message.embeds:
            return
        embed = interaction.message.embeds[0]
        embed.color = color
        for i, field in enumerate(embed.fields):
            if field.name == "Current Status":
                embed.set_field_at(i, name="Current Status", value=status_text, inline=False)
                break
        else:
            embed.add_field(name="Current Status", value=status_text, inline=False)

        # IMPORTANT: build a brand new, disabled view scoped to *this* message only.
        # The bot's registered PaymentVerificationView instance is a single shared
        # persistent view reused across every audit embed (that's what makes the
        # static custom_ids work after a restart). Mutating that shared instance's
        # buttons here would disable the Approve/Reject buttons on every other
        # pending audit message too, so we never touch `interaction.view` directly.
        disabled_view = discord.ui.View(timeout=None)
        disabled_view.add_item(
            discord.ui.Button(
                label="Approve Payment",
                style=discord.ButtonStyle.success,
                emoji="✅",
                disabled=True,
                custom_id="payment_approve_done",
            )
        )
        disabled_view.add_item(
            discord.ui.Button(
                label="Reject Payment",
                style=discord.ButtonStyle.danger,
                emoji="❌",
                disabled=True,
                custom_id="payment_reject_done",
            )
        )

        try:
            await interaction.message.edit(embed=embed, view=disabled_view)
        except discord.HTTPException:
            logger.exception("Failed to update audit embed after decision")
