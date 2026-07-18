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
import os
import threading
from flask import Flask

import discord
from discord.ext import commands

from config import (
    DISCORD_TOKEN,
    GUILD_ID,
    ZIO_AUDIT_CHANNEL_NAME,
    TRIAL_CHANNEL_NAME,
    ROLE_MINECRAFT_ADMIN,
    CATEGORY_ID,
    WHITELISTING_CHANNEL_ID,
)
from database import Database
from utils.channels import resolve_channel_id
from utils.logger import get_logger
from views.payment_buttons import PaymentVerificationView
from views.application_form import WhitelistApplicationView, ManualReviewView

logger = get_logger(__name__)

APPLICATION_MARKER_TITLE = "📋 SMP Whitelist Application"

INITIAL_EXTENSIONS = (
    "cogs.whitelist",
    "cogs.payments",
    "cogs.audit",
    "cogs.subscriptions",
    "cogs.setup",
)

app = Flask(__name__)

@app.route("/")
def health_check():
    return "SMP Bot Running", 200


def run_web_server():
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        use_reloader=False,
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

        # Register the persistent views so buttons keep working after restarts.
        self.add_view(PaymentVerificationView(self))
        self.add_view(WhitelistApplicationView(self))
        self.add_view(ManualReviewView(self))

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
            await ensure_channels(guild, self)
            await ensure_application_message(guild, self)

    async def close(self) -> None:
        self.db.close()
        await super().close()


async def ensure_channels(guild: discord.Guild, bot: "SMPBot") -> None:
    """Create zio-audit and trial-channel if they don't already exist. Never creates roles.

    Both channels are created inside the configured category (from /setup or
    the fallback CATEGORY_ID). If that category doesn't exist in this guild,
    channel creation is skipped entirely.
    """
    cat_id = await resolve_channel_id(bot.db, guild.id, "category", CATEGORY_ID)
    category = guild.get_channel(cat_id)
    if category is None or not isinstance(category, discord.CategoryChannel):
        logger.error(
            "Category %s not found in guild %s ('%s'). Skipping channel creation.",
            cat_id,
            guild.id,
            guild.name,
        )
        return

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
                category=category,
                overwrites=overwrites,
                topic=topic,
                reason="SMP bot startup: ensuring required channel exists",
            )
            logger.info("Created channel #%s in guild %s", channel_name, guild.id)
        except discord.Forbidden:
            logger.exception("Missing permission to create channel #%s", channel_name)
        except discord.HTTPException:
            logger.exception("Failed to create channel #%s", channel_name)


async def ensure_application_message(guild: discord.Guild, bot: "SMPBot") -> None:
    """Post the whitelist application sticky message (with Apply button) once, if missing."""
    wl_id = await resolve_channel_id(bot.db, guild.id, "whitelisting", WHITELISTING_CHANNEL_ID)
    channel = guild.get_channel(wl_id)
    if channel is None or not isinstance(channel, discord.TextChannel):
        logger.error("Whitelisting channel %s not found in guild %s", wl_id, guild.id)
        return

    try:
        async for message in channel.history(limit=50):
            if (
                bot.user is not None
                and message.author.id == bot.user.id
                and message.embeds
                and message.embeds[0].title == APPLICATION_MARKER_TITLE
            ):
                return  # Already posted - don't duplicate it.
    except discord.HTTPException:
        logger.exception("Failed to read history of whitelisting channel")
        return

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
        await channel.send(embed=embed, view=WhitelistApplicationView(bot))
        logger.info("Posted whitelist application message in guild %s", guild.id)
    except discord.HTTPException:
        logger.exception("Failed to post whitelist application message")


async def main() -> None:
    bot = SMPBot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    asyncio.run(main())