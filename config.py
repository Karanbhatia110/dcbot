"""
Configuration module.

Loads environment variables and defines static constants used across the bot:
existing channel IDs, role names, and business-rule constants (pricing,
subscription length, reminder thresholds).
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Secrets / environment
# ---------------------------------------------------------------------------
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
MONGODB_URI: str = os.getenv("MONGODB_URI", "")
MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME", "smp_bot")

GUILD_ID_RAW: str = os.getenv("GUILD_ID", "")
GUILD_ID: int | None = int(GUILD_ID_RAW) if GUILD_ID_RAW.strip() else None

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Please set it in your .env file.")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is not set. Please set it in your .env file.")

# ---------------------------------------------------------------------------
# Default / fallback channel IDs. These are used when a guild has NOT yet
# configured channels via /setup. Once /setup is run, the DB values take
# priority over these constants.
# ---------------------------------------------------------------------------
PAYMENT_GATEWAY_CHANNEL_ID: int = 1527346320434528377
WHITELISTING_CHANNEL_ID: int = 1527323483078529074
PAYMENT_CONFIRMATION_CHANNEL_ID: int = 1527366877234335844

# ---------------------------------------------------------------------------
# Channels the bot is responsible for creating (only if missing)
# ---------------------------------------------------------------------------
ZIO_AUDIT_CHANNEL_NAME: str = "zio-audit"
TRIAL_CHANNEL_NAME: str = "trial-channel"

# Default category for bot-created channels. Overridden by /setup.
CATEGORY_ID: int = 818112617628565546

# ---------------------------------------------------------------------------
# Existing roles (DO NOT CREATE THESE - fetched by name, never created)
# ---------------------------------------------------------------------------
ROLE_MINECRAFT_ADMIN: str = "MINECRAFT ADMIN"
ROLE_MINECRAFT: str = "MINECRAFT"
ROLE_WHITELISTED: str = "Whitelisted"
ROLE_SMP_APPLICANT: str = "SMP Applicant"

# ---------------------------------------------------------------------------
# Business rules
# ---------------------------------------------------------------------------
PAYMENT_AMOUNT_INR: int = 69
SUBSCRIPTION_DAYS: int = 30
REMINDER_DAYS_BEFORE_EXPIRY: tuple[int, ...] = (3, 1)

# MongoDB collection names
GUILD_SETTINGS_COLLECTION: str = "guild_settings"
USERS_COLLECTION: str = "users"

# Logging
LOG_FILE: str = os.getenv("LOG_FILE", "bot.log")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")