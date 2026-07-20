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
from utils.channels import resolve_channel_id, resolve_audit_channel
from utils.embeds import audit_log_embed, COLOR_INFO
from utils.logger import get_logger
from views.application_form import WhitelistApplicationView

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)

APPLICATION_MARKER_TITLE = "📋 SMP Whitelist Application"


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if member.guild_permissions.administrator:
            return True
        admin_role = discord.utils.get(interaction.guild.roles, name=ROLE_MINECRAFT_ADMIN)
        if admin_role is not None and admin_role in member.roles:
            return True
        if admin_role is None:
            await interaction.response.send_message(
                f"⚠️ Role `{ROLE_MINECRAFT_ADMIN}` not found on this server.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ You need the `MINECRAFT ADMIN` role to use this command.", ephemeral=True
            )
        return False

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
        audit_channel = await resolve_audit_channel(self.bot.db, guild)
        if audit_channel:
            try:
                await audit_channel.send(
                    f"⚠️ Role `{role_name}` is missing and was NOT created automatically. "
                    f"Please create it manually."
                )
            except discord.HTTPException:
                logger.exception("Failed to notify admins")

    @commands.command(name="mcform", help="Post the whitelist application form in this channel.")
    @commands.has_permissions(administrator=True)
    async def mcform_cmd(self, ctx: commands.Context) -> None:
        """Post the SMP whitelist application embed + Apply button in the current channel."""
        guild = ctx.guild
        if guild is None:
            await ctx.send("❌ This command can only be used in a server.")
            return

        member = ctx.author
        if isinstance(member, discord.Member):
            admin_role = discord.utils.get(guild.roles, name=ROLE_MINECRAFT_ADMIN)
            has_mc_admin = admin_role is not None and admin_role in member.roles
            has_server_admin = member.guild_permissions.administrator
            if not has_mc_admin and not has_server_admin:
                await ctx.send(
                    "❌ You need the `MINECRAFT ADMIN` role or server Administrator permission.",
                    delete_after=10,
                )
                return

        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("❌ This command can only be used in a text channel.")
            return

        # Avoid duplicating the form in the same channel
        try:
            async for message in channel.history(limit=50):
                if (
                    self.bot.user is not None
                    and message.author.id == self.bot.user.id
                    and message.embeds
                    and message.embeds[0].title == APPLICATION_MARKER_TITLE
                ):
                    await ctx.send(
                        "ℹ️ The whitelist application form is already posted in this channel.",
                        delete_after=10,
                    )
                    return
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title=APPLICATION_MARKER_TITLE,
            description=(
                "Welcome! Before joining the server, every player must complete this short "
                "application. This helps us build a friendly, active, and mature community "
                "that values fair play and long-term progression.\n\n"
                "Click the button below to apply.\n\n"
                "Applications are usually reviewed within 12–24 hours."
            ),
            color=discord.Color.blurple(),
        )
        try:
            await channel.send(embed=embed, view=WhitelistApplicationView(self.bot))
            logger.info("!mcform: posted whitelist form in #%s (guild %s)", channel.name, guild.id)
        except discord.HTTPException:
            logger.exception("Failed to post whitelist application via !mcform")
            await ctx.send("❌ Failed to post the application form.", delete_after=10)
            return

        # Delete the invoking command message to keep the channel clean
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

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

        audit_channel = await resolve_audit_channel(self.bot.db, guild)
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
