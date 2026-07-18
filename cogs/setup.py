"""
Setup cog.

Provides the !setup prefix command that lets server administrators configure
which channels the bot should use for payments, whitelisting, and audit
logging — replacing the previously hardcoded channel IDs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from config import ROLE_MINECRAFT_ADMIN
from utils.logger import get_logger
from views.setup_views import SetupView, _settings_embed

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)


class SetupCog(commands.Cog):
    def __init__(self, bot: "SMPBot") -> None:
        self.bot = bot

    @commands.command(name="setup", help="Configure which channels the bot uses.")
    @commands.has_permissions(administrator=True)
    async def setup_cmd(self, ctx: commands.Context) -> None:
        """Configure which channels the bot uses for payments, whitelisting, and audit."""
        guild = ctx.guild
        if guild is None:
            await ctx.send("❌ This command can only be used in a server.")
            return

        # Check for MINECRAFT ADMIN role OR server Administrator permission
        member = ctx.author
        if isinstance(member, discord.Member):
            admin_role = discord.utils.get(guild.roles, name=ROLE_MINECRAFT_ADMIN)
            has_mc_admin = admin_role is not None and admin_role in member.roles
            has_server_admin = member.guild_permissions.administrator
            if not has_mc_admin and not has_server_admin:
                await ctx.send(
                    "❌ You need the `MINECRAFT ADMIN` role or server Administrator permission to use this command.",
                    delete_after=10,
                )
                return

        settings = await self.bot.db.get_guild_settings(guild.id)
        embed = _settings_embed(guild, settings)
        view = SetupView(self.bot)

        await ctx.send(embed=embed, view=view)
        logger.info("!setup invoked by %s in guild %s", ctx.author.id, guild.id)

    @setup_cmd.error
    async def setup_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use this command.", delete_after=10)
            return
        logger.exception("Error in !setup", exc_info=error)
        await ctx.send("❌ An unexpected error occurred.", delete_after=10)


async def setup(bot: "SMPBot") -> None:
    await bot.add_cog(SetupCog(bot))
