"""
Persistent Discord UI views for the /setup configuration command.

Provides a channel-select workflow: the admin clicks a button to configure a
specific channel type, a ``ChannelSelect`` dropdown appears, and the selection
is saved to MongoDB via ``Database.set_guild_channel``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from config import (
    PAYMENT_GATEWAY_CHANNEL_ID,
    PAYMENT_CONFIRMATION_CHANNEL_ID,
    WHITELISTING_CHANNEL_ID,
    CATEGORY_ID,
    ZIO_AUDIT_CHANNEL_NAME,
)
from utils.logger import get_logger

if TYPE_CHECKING:
    from main import SMPBot

logger = get_logger(__name__)

# Maps a setting key to (label, emoji, description shown after setting)
CHANNEL_KEYS: dict[str, tuple[str, str, str]] = {
    "payment_gateway":      ("Payment Gateway",      "💳", "Where the QR / payment info is posted"),
    "payment_confirmation": ("Payment Confirmation",  "📸", "Where users upload payment screenshots"),
    "whitelisting":         ("Whitelisting",          "📋", "Where the whitelist application message lives"),
    "audit":                ("Audit Channel",         "📝", "Where audit logs are posted"),
    "category":             ("Bot Category",          "📁", "Category for bot-created channels"),
}


def _settings_embed(guild: discord.Guild, settings: dict | None) -> discord.Embed:
    """Build the embed that shows current configuration."""
    embed = discord.Embed(
        title="⚙️ Bot Channel Configuration",
        description="Click a button below to assign a channel for each function.",
        color=discord.Color.blurple(),
    )
    for key, (label, emoji, desc) in CHANNEL_KEYS.items():
        channel_id = settings.get(key) if settings else None
        if channel_id:
            value = f"<#{channel_id}>"
        else:
            # Show the fallback default
            fallback = _fallback_for(key, guild)
            value = f"<#{fallback}> *(default)*" if fallback else "*Not set*"
        embed.add_field(name=f"{emoji} {label}", value=value, inline=True)
    embed.set_footer(text="Settings are saved per server.")
    return embed


def _fallback_for(key: str, guild: discord.Guild) -> int | None:
    """Return the hardcoded fallback for a key, if any."""
    mapping = {
        "payment_gateway": PAYMENT_GATEWAY_CHANNEL_ID,
        "payment_confirmation": PAYMENT_CONFIRMATION_CHANNEL_ID,
        "whitelisting": WHITELISTING_CHANNEL_ID,
        "category": CATEGORY_ID,
    }
    if key == "audit":
        ch = discord.utils.get(guild.text_channels, name=ZIO_AUDIT_CHANNEL_NAME)
        return ch.id if ch else None
    return mapping.get(key)


# ---------------------------------------------------------------------------
# Channel select dropdown that appears after a button click
# ---------------------------------------------------------------------------
class ChannelSelectView(discord.ui.View):
    """Ephemeral view with a single channel select menu."""

    def __init__(self, bot: "SMPBot", key: str, original_interaction: discord.Interaction) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.key = key
        self.original_interaction = original_interaction

        # For the "category" key, only show category channels
        if key == "category":
            channel_types = [discord.ChannelType.category]
        else:
            channel_types = [discord.ChannelType.text]

        select = discord.ui.ChannelSelect(
            placeholder=f"Select a channel for {CHANNEL_KEYS[key][0]}…",
            channel_types=channel_types,
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        # interaction.data contains the selected channel(s)
        selected = interaction.data["values"][0]  # type: ignore[index]
        channel_id = int(selected)

        await self.bot.db.set_guild_channel(interaction.guild.id, self.key, channel_id)

        label, emoji, _ = CHANNEL_KEYS[self.key]
        await interaction.response.send_message(
            f"{emoji} **{label}** set to <#{channel_id}>.",
            ephemeral=True,
        )

        # Refresh the original setup embed
        try:
            settings = await self.bot.db.get_guild_settings(interaction.guild.id)
            embed = _settings_embed(interaction.guild, settings)
            await self.original_interaction.edit_original_response(embed=embed)
        except discord.HTTPException:
            logger.exception("Failed to refresh setup embed after channel selection")

        self.stop()


# ---------------------------------------------------------------------------
# Main setup view with 5 buttons
# ---------------------------------------------------------------------------
class SetupView(discord.ui.View):
    """View shown by /setup — one button per configurable channel."""

    def __init__(self, bot: "SMPBot") -> None:
        super().__init__(timeout=180)
        self.bot = bot

        for key, (label, emoji, _) in CHANNEL_KEYS.items():
            btn = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"setup_{key}",
            )
            btn.callback = self._make_callback(key)
            self.add_item(btn)

    def _make_callback(self, key: str):
        async def callback(interaction: discord.Interaction) -> None:
            select_view = ChannelSelectView(self.bot, key, interaction)
            label, emoji, desc = CHANNEL_KEYS[key]
            await interaction.response.send_message(
                f"{emoji} **{label}**: {desc}\nSelect a channel below:",
                view=select_view,
                ephemeral=True,
            )
        return callback
