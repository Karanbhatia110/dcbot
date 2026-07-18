"""
Entry point for the SMP Discord bot.

Responsibilities:
- Boot the bot with the correct intents.
- Connect to MongoDB Atlas.
- Create the two channels the bot owns (zio-audit, trial-channel) if missing,
  with correct permission overwrites, without ever touching pre-existing
  channels or creating any roles.
- Load all cogs and register the persistent payment-verification view.
- Sync application (slash) commands.
"""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from config import (
    DISCORD_TOKEN,
    GUILD_ID,
    ZIO_AUDIT_CHANNEL_NAME,
    TRIAL_CHANNEL_NAME,
    ROLE_MINECRAFT_ADMIN,
)
from database import Database
from utils.logger import get_logger
from views.payment_buttons import PaymentVerificationView

logger = get_logger(__name__)

INITIAL_EXTENSIONS = (
    "cogs.whitelist",
    "cogs.payments",
    "cogs.audit",
    "cogs.subscriptions",
)


class SMPBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.db = Database()

    async def setup_hook(self) -> None:
        await self.db.connect()

        for extension in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info("Loaded extension: %s", extension)
            except Exception:
                logger.exception("Failed to load extension: %s", extension)

        # Register the persistent view so buttons keep working after restarts.
        self.add_view(PaymentVerificationView(self))

        if GUILD_ID is not None:
            guild_obj = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild_obj)
            synced = await self.tree.sync(guild=guild_obj)
        else:
            synced = await self.tree.sync()
        logger.info("Synced %d application command(s)", len(synced))

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "?")
        for guild in self.guilds:
            await ensure_channels(guild)

    async def close(self) -> None:
        self.db.close()
        await super().close()


async def ensure_channels(guild: discord.Guild) -> None:
    """Create zio-audit and trial-channel if they don't already exist. Never creates roles."""
    admin_role = discord.utils.get(guild.roles, name=ROLE_MINECRAFT_ADMIN)
    if admin_role is None:
        logger.error(
            "Role '%s' not found in guild %s ('%s'). Cannot set channel permissions correctly.",
            ROLE_MINECRAFT_ADMIN,
            guild.id,
            guild.name,
        )
        # Still proceed to create channels with @everyone denied; admin overwrite
        # will simply be skipped until the role exists.

    overwrites: dict[discord.Role, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    if admin_role is not None:
        overwrites[admin_role] = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )

    for channel_name, topic in (
        (ZIO_AUDIT_CHANNEL_NAME, "Payment approvals, rejections, and subscription audit logs."),
        (TRIAL_CHANNEL_NAME, "Admin testing environment for bot commands."),
    ):
        existing = discord.utils.get(guild.text_channels, name=channel_name)
        if existing is not None:
            continue
        try:
            await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                topic=topic,
                reason="SMP bot startup: ensuring required channel exists",
            )
            logger.info("Created channel #%s in guild %s", channel_name, guild.id)
        except discord.Forbidden:
            logger.exception("Missing permission to create channel #%s", channel_name)
        except discord.HTTPException:
            logger.exception("Failed to create channel #%s", channel_name)


async def main() -> None:
    bot = SMPBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
