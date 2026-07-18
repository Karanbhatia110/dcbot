"""
Whitelist cog.

Handles:
- Assigning the "SMP Applicant" role when a new member joins.
- /whitelist_accept admin command: promotes an applicant to "Whitelisted",
  creates their MongoDB record, and DMs them payment instructions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from config import (
    ROLE_MINECRAFT_ADMIN,
    ROLE_SMP_APPLICANT,
    ROLE_WHITELISTED,
    PAYMENT_GATEWAY_CHANNEL_ID,
    PAYMENT_CONFIRMATION_CHANNEL_ID,
    PAYMENT_AMOUNT_INR,
    ZIO_AUDIT_CHANNEL_NAME,
)
from utils.channels import resolve_channel_id
from utils.embeds import audit_log_embed, COLOR_INFO
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        admin_role = discord.utils.get(interaction.guild.roles, name=ROLE_MINECRAFT_ADMIN)
        if admin_role is None:
            await interaction.response.send_message(
                f"⚠️ Role `{ROLE_MINECRAFT_ADMIN}` not found on this server.", ephemeral=True
            )
            return False
        if not isinstance(interaction.user, discord.Member) or admin_role not in interaction.user.roles:
            await interaction.response.send_message(
                "❌ You need the `MINECRAFT ADMIN` role to use this command.", ephemeral=True
            )
            return False
        return True

    return app_commands.check(predicate)


class WhitelistCog(commands.Cog):
    def __init__(self, bot: "SMPBot") -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        role = discord.utils.get(member.guild.roles, name=ROLE_SMP_APPLICANT)
        if role is None:
            logger.error("Role '%s' not found in guild %s", ROLE_SMP_APPLICANT, member.guild.id)
            await self._notify_missing_role(member.guild, ROLE_SMP_APPLICANT)
            return
        try:
            await member.add_roles(role, reason="New member joined - SMP Applicant")
            logger.info("Assigned '%s' to %s", ROLE_SMP_APPLICANT, member.id)
        except discord.Forbidden:
            logger.exception("Missing permission to assign '%s' to %s", ROLE_SMP_APPLICANT, member.id)

    async def _notify_missing_role(self, guild: discord.Guild, role_name: str) -> None:
        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        if audit_channel:
            try:
                await audit_channel.send(
                    f"⚠️ Role `{role_name}` is missing and was NOT created automatically. "
                    f"Please create it manually."
                )
            except discord.HTTPException:
                logger.exception("Failed to notify admins in #%s", ZIO_AUDIT_CHANNEL_NAME)

    @app_commands.command(
        name="whitelist_accept", description="Accept a user's SMP whitelist application."
    )
    @app_commands.describe(user="The user to whitelist")
    @is_admin()
    async def whitelist_accept(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        assert guild is not None

        whitelisted_role = discord.utils.get(guild.roles, name=ROLE_WHITELISTED)
        if whitelisted_role is None:
            logger.error("Role '%s' not found in guild %s", ROLE_WHITELISTED, guild.id)
            await self._notify_missing_role(guild, ROLE_WHITELISTED)
            await interaction.followup.send(
                f"⚠️ Role `{ROLE_WHITELISTED}` not found. Cannot whitelist. Admins notified.",
                ephemeral=True,
            )
            return

        try:
            await user.add_roles(whitelisted_role, reason=f"Whitelisted by {interaction.user}")
        except discord.Forbidden:
            logger.exception("Missing permission to add '%s' to %s", ROLE_WHITELISTED, user.id)
            await interaction.followup.send("❌ I lack permission to assign that role.", ephemeral=True)
            return

        await self.bot.db.create_whitelisted_user(user.id, str(user))

        # Resolve channels dynamically from DB settings
        gw_id = await resolve_channel_id(
            self.bot.db, guild.id, "payment_gateway", PAYMENT_GATEWAY_CHANNEL_ID
        )
        pc_id = await resolve_channel_id(
            self.bot.db, guild.id, "payment_confirmation", PAYMENT_CONFIRMATION_CHANNEL_ID
        )

        try:
            await user.send(
                "🎉 You have been accepted into the SMP whitelist.\n\n"
                f"Please complete the ₹{PAYMENT_AMOUNT_INR} payment using the QR code in "
                f"<#{gw_id}>.\n\n"
                f"After payment, upload the screenshot in <#{pc_id}>."
            )
        except discord.Forbidden:
            logger.warning("Could not DM whitelisted user %s (DMs closed)", user.id)

        audit_channel = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        if audit_channel:
            embed = audit_log_embed(
                title="✅ Whitelist Accepted",
                description=f"{user.mention} was whitelisted.",
                color=COLOR_INFO,
                fields={"Admin": interaction.user.mention, "Discord ID": user.id},
            )
            await audit_channel.send(embed=embed)

        logger.info("Whitelist accepted for %s by %s", user.id, interaction.user.id)
        await interaction.followup.send(f"✅ {user.mention} has been whitelisted.", ephemeral=True)

    @whitelist_accept.error
    async def whitelist_accept_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            return  # Already handled by the check's own response.
        logger.exception("Error in /whitelist_accept", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send("❌ An unexpected error occurred.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ An unexpected error occurred.", ephemeral=True)


async def setup(bot: "SMPBot") -> None:
    await bot.add_cog(WhitelistCog(bot))
