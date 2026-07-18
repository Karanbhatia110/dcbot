"""
Audit cog.

Provides the /audit command group used by MINECRAFT ADMIN to inspect user
and subscription state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from cogs.whitelist import is_admin
from utils.embeds import user_status_embed, user_list_embed, COLOR_APPROVED, COLOR_EXPIRED, COLOR_PENDING
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)


class AuditCog(commands.Cog):
    def __init__(self, bot: "SMPBot") -> None:
        self.bot = bot

    audit_group = app_commands.Group(name="audit", description="Inspect SMP user/subscription records.")

    @audit_group.command(name="user", description="Show a specific user's audit record.")
    @app_commands.describe(user="The user to look up")
    @is_admin()
    async def audit_user(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        doc = await self.bot.db.get_user(user.id)
        if doc is None:
            await interaction.followup.send(f"No record found for {user.mention}.", ephemeral=True)
            return
        await interaction.followup.send(embed=user_status_embed(doc), ephemeral=True)

    @audit_group.command(name="active", description="List all users with an active subscription.")
    @is_admin()
    async def audit_active(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        users = await self.bot.db.get_users_by_status("active")
        await interaction.followup.send(
            embed=user_list_embed("✅ Active Subscriptions", users, COLOR_APPROVED), ephemeral=True
        )

    @audit_group.command(name="expired", description="List all users with an expired subscription.")
    @is_admin()
    async def audit_expired(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        users = await self.bot.db.get_users_by_status("expired")
        await interaction.followup.send(
            embed=user_list_embed("⏳ Expired Subscriptions", users, COLOR_EXPIRED), ephemeral=True
        )

    @audit_group.command(name="pending", description="List all users awaiting payment verification.")
    @is_admin()
    async def audit_pending(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        users = await self.bot.db.get_pending_verification_users()
        await interaction.followup.send(
            embed=user_list_embed("🕓 Pending Verification", users, COLOR_PENDING), ephemeral=True
        )


async def setup(bot: "SMPBot") -> None:
    await bot.add_cog(AuditCog(bot))
