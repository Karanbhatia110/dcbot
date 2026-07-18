"""
Whitelist application modal + button view.

Users click "Apply for Whitelist" in the whitelisting channel, fill out a
short form, and submit. If they answer "yes" to question 4 (consent to be
removed/banned if caught cheating), the bot immediately grants the
Whitelisted role and creates their MongoDB record - mirroring what
/whitelist_accept does manually. Any other answer is forwarded to
#zio-audit for manual admin review and no role is granted automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import (
    ROLE_WHITELISTED,
    ROLE_MINECRAFT_ADMIN,
    ZIO_AUDIT_CHANNEL_NAME,
    PAYMENT_GATEWAY_CHANNEL_ID,
    PAYMENT_CONFIRMATION_CHANNEL_ID,
    PAYMENT_AMOUNT_INR,
)
from utils.channels import resolve_channel_id
from utils.embeds import audit_log_embed, COLOR_INFO, COLOR_PENDING
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)

CONSENT_YES_VALUES = {"yes", "y"}


class WhitelistApplicationModal(discord.ui.Modal, title="SMP Whitelist Application"):
    minecraft_username = discord.ui.TextInput(
        label="Minecraft Username", placeholder="Steve", max_length=32, required=True
    )
    minecraft_knowledge = discord.ui.TextInput(
        label="How much Minecraft do you know?",
        style=discord.TextStyle.paragraph,
        placeholder="e.g. I've been playing for 3 years, know redstone, etc.",
        max_length=300,
        required=True,
    )
    how_heard = discord.ui.TextInput(
        label="How did you hear about this SMP?",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=True,
    )
    consent = discord.ui.TextInput(
        label="Consent to removal/ban if caught cheating?",
        placeholder="Yes or No",
        max_length=10,
        required=True,
    )

    def __init__(self, bot: "SMPBot") -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        member = interaction.user
        assert isinstance(member, discord.Member)

        existing = await self.bot.db.get_user(member.id)
        if existing is not None:
            await interaction.followup.send(
                "ℹ️ You've already applied. Check your DMs, or contact staff if you think this is a mistake.",
                ephemeral=True,
            )
            return

        consented = self.consent.value.strip().lower() in CONSENT_YES_VALUES
        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)

        if consented:
            await self._grant_whitelist(interaction, guild, member, audit_channel)
        else:
            await self._reject_application(interaction, guild, member, audit_channel)

    async def _grant_whitelist(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        member: discord.Member,
        audit_channel: discord.TextChannel | None,
    ) -> None:
        whitelisted_role = discord.utils.get(guild.roles, name=ROLE_WHITELISTED)
        if whitelisted_role is None:
            logger.error("Role '%s' not found in guild %s", ROLE_WHITELISTED, guild.id)
            if audit_channel:
                await audit_channel.send(
                    f"⚠️ Role `{ROLE_WHITELISTED}` is missing. Could not auto-whitelist "
                    f"{member.mention} from their application. Please create the role and "
                    f"run /whitelist_accept manually."
                )
            await interaction.followup.send(
                "⚠️ Something went wrong on our end. Staff has been notified.", ephemeral=True
            )
            return

        try:
            await member.add_roles(
                whitelisted_role, reason="Auto-whitelisted via application form (consent=yes)"
            )
        except discord.Forbidden:
            logger.exception("Missing permission to add '%s' to %s", ROLE_WHITELISTED, member.id)
            await interaction.followup.send(
                "⚠️ I couldn't assign your role automatically. Staff has been notified.", ephemeral=True
            )
            if audit_channel:
                await audit_channel.send(
                    f"⚠️ Failed to auto-whitelist {member.mention} — missing permissions."
                )
            return

        await self.bot.db.create_whitelisted_user(member.id, str(member))

        gw_id = await resolve_channel_id(
            self.bot.db, guild.id, "payment_gateway", PAYMENT_GATEWAY_CHANNEL_ID
        )
        pc_id = await resolve_channel_id(
            self.bot.db, guild.id, "payment_confirmation", PAYMENT_CONFIRMATION_CHANNEL_ID
        )

        try:
            await member.send(
                "🎉 Your application was approved and you have been accepted into the SMP whitelist.\n\n"
                f"Please complete the ₹{PAYMENT_AMOUNT_INR} payment using the QR code in "
                f"<#{gw_id}>.\n\n"
                f"After payment, upload the screenshot in <#{pc_id}>."
            )
        except discord.Forbidden:
            logger.warning("Could not DM whitelisted user %s (DMs closed)", member.id)

        if audit_channel:
            embed = audit_log_embed(
                title="✅ Application Approved (auto)",
                description=f"{member.mention} was auto-whitelisted via the application form.",
                color=COLOR_INFO,
                fields={
                    "Minecraft Username": self.minecraft_username.value,
                    "Minecraft Knowledge": self.minecraft_knowledge.value,
                    "How they heard": self.how_heard.value,
                    "Discord ID": member.id,
                },
            )
            await audit_channel.send(embed=embed)

        logger.info("Auto-whitelisted %s via application form", member.id)
        await interaction.followup.send(
            "✅ You've been whitelisted! Check your DMs for payment instructions.", ephemeral=True
        )

    async def _reject_application(
        self,
        interaction: discord.Interaction,
        guild: discord.Guild,
        member: discord.Member,
        audit_channel: discord.TextChannel | None,
    ) -> None:
        if audit_channel:
            embed = audit_log_embed(
                title="🕓 Application Needs Manual Review",
                description=(
                    f"{member.mention} did not confirm consent to the anti-cheat policy. "
                    f"No role was granted automatically."
                ),
                color=COLOR_PENDING,
                fields={
                    "Minecraft Username": self.minecraft_username.value,
                    "Minecraft Knowledge": self.minecraft_knowledge.value,
                    "How they heard": self.how_heard.value,
                    "Consent Answer": self.consent.value,
                    "Discord ID": member.id,
                },
            )
            view = ManualReviewView(self.bot)
            await audit_channel.send(embed=embed, view=view)

        logger.info(
            "Application from %s requires manual review (consent=%r)", member.id, self.consent.value
        )
        try:
            await member.send(
                "📨 Your SMP whitelist application has been received.\n"
                "Your application is under manual review by our staff. "
                "You'll be notified once a decision is made."
            )
        except discord.Forbidden:
            logger.warning("Could not DM user %s (DMs closed)", member.id)

        await interaction.followup.send(
            "📨 Your application has been submitted for manual review by staff.", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Accept / Reject buttons for manual review audit messages
# ---------------------------------------------------------------------------
class ManualReviewView(discord.ui.View):
    """Persistent view with Accept / Reject buttons for manual-review audit messages."""

    def __init__(self, bot: "SMPBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @staticmethod
    def _extract_target_id(interaction: discord.Interaction) -> int | None:
        """Pull the target Discord ID from the embed's fields."""
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

    @staticmethod
    async def _is_admin(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        admin_role = discord.utils.get(interaction.guild.roles, name=ROLE_MINECRAFT_ADMIN)
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        has_mc_admin = admin_role is not None and admin_role in member.roles
        has_server_admin = member.guild_permissions.administrator
        if not has_mc_admin and not has_server_admin:
            await interaction.response.send_message(
                "❌ Only admins can use this button.", ephemeral=True
            )
            return False
        return True

    async def _disable_buttons(
        self, interaction: discord.Interaction, status: str, color: discord.Color
    ) -> None:
        """Replace the view with disabled buttons and update the embed."""
        if not interaction.message:
            return
        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.color = color
            embed.add_field(name="Decision", value=status, inline=False)

        disabled_view = discord.ui.View(timeout=None)
        disabled_view.add_item(discord.ui.Button(
            label="Accept", style=discord.ButtonStyle.success, emoji="✅",
            disabled=True, custom_id="review_accept_done",
        ))
        disabled_view.add_item(discord.ui.Button(
            label="Reject", style=discord.ButtonStyle.danger, emoji="🚫",
            disabled=True, custom_id="review_remove_done",
        ))
        try:
            await interaction.message.edit(embed=embed, view=disabled_view)
        except discord.HTTPException:
            logger.exception("Failed to disable manual review buttons")

    # ---- Accept button ----
    @discord.ui.button(
        label="Accept", style=discord.ButtonStyle.success, emoji="✅",
        custom_id="review_accept",
    )
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._is_admin(interaction):
            return
        await interaction.response.defer()

        guild = interaction.guild
        assert guild is not None
        target_id = self._extract_target_id(interaction)
        if target_id is None:
            await interaction.followup.send("❌ Could not determine the user.", ephemeral=True)
            return

        member = guild.get_member(target_id)
        if member is None:
            try:
                member = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send("❌ User not found in this server.", ephemeral=True)
                return

        whitelisted_role = discord.utils.get(guild.roles, name=ROLE_WHITELISTED)
        if whitelisted_role is None:
            await interaction.followup.send(
                f"⚠️ Role `{ROLE_WHITELISTED}` not found.", ephemeral=True
            )
            return

        try:
            await member.add_roles(
                whitelisted_role, reason=f"Manual review accepted by {interaction.user}"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Missing permission to assign role.", ephemeral=True
            )
            return

        await self.bot.db.create_whitelisted_user(member.id, str(member))

        gw_id = await resolve_channel_id(
            self.bot.db, guild.id, "payment_gateway", PAYMENT_GATEWAY_CHANNEL_ID
        )
        pc_id = await resolve_channel_id(
            self.bot.db, guild.id, "payment_confirmation", PAYMENT_CONFIRMATION_CHANNEL_ID
        )
        try:
            await member.send(
                "🎉 Your application has been manually reviewed and accepted!\n\n"
                f"Please complete the ₹{PAYMENT_AMOUNT_INR} payment using the QR code in "
                f"<#{gw_id}>.\n\n"
                f"After payment, upload the screenshot in <#{pc_id}>."
            )
        except discord.Forbidden:
            logger.warning("Could not DM user %s (DMs closed)", member.id)

        await self._disable_buttons(
            interaction, f"✅ Accepted by {interaction.user.mention}", COLOR_INFO
        )
        logger.info("Manual review: accepted %s by %s", target_id, interaction.user.id)

    # ---- Reject button ----
    @discord.ui.button(
        label="Reject", style=discord.ButtonStyle.danger, emoji="🚫",
        custom_id="review_remove",
    )
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await self._is_admin(interaction):
            return
        await interaction.response.defer()

        guild = interaction.guild
        assert guild is not None
        target_id = self._extract_target_id(interaction)
        if target_id is None:
            await interaction.followup.send("❌ Could not determine the user.", ephemeral=True)
            return

        member = guild.get_member(target_id)
        if member is None:
            try:
                member = await guild.fetch_member(target_id)
            except discord.NotFound:
                await interaction.followup.send("❌ User not found in this server.", ephemeral=True)
                return

        try:
            await member.send(
                "❌ Your SMP whitelist application has been reviewed and unfortunately denied.\n"
                "If you believe this is a mistake, please contact a server admin."
            )
        except (discord.Forbidden, discord.HTTPException):
            pass  # DM may fail if user has DMs closed

        await self._disable_buttons(
            interaction, f"🚫 Rejected by {interaction.user.mention}", discord.Color.red()
        )
        logger.info("Manual review: rejected %s by %s", target_id, interaction.user.id)


# ---------------------------------------------------------------------------
# Persistent "Apply" button view
# ---------------------------------------------------------------------------
class WhitelistApplicationView(discord.ui.View):
    """Persistent view with the 'Apply for Whitelist' button, posted once in the whitelisting channel."""

    def __init__(self, bot: "SMPBot") -> None:
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Apply for Whitelist",
        style=discord.ButtonStyle.primary,
        emoji="📝",
        custom_id="smp_apply_button",
    )
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(WhitelistApplicationModal(self.bot))