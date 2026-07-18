# SMP Whitelist & Payment Bot

A production-ready Discord bot for a paid Minecraft SMP server. Handles the
full applicant → whitelist → payment → subscription lifecycle, with an admin
audit trail, renewal commands, and automated expiry reminders.

## Features

- **Whitelist flow** — new members get `SMP Applicant`; admins promote them
  with `/whitelist_accept`, which grants `Whitelisted`, creates a MongoDB
  record, and DMs payment instructions.
- **Payment verification** — screenshots uploaded to the existing
  payment-confirmation channel are recorded and posted to `#zio-audit` as an
  embed with **Approve** / **Reject** buttons (persistent — they survive bot
  restarts).
- **Subscriptions** — approving a payment grants `MINECRAFT` for 30 days.
  `/renew` extends it. A daily scheduler sends 7/3/1-day expiry reminders and
  removes only the `MINECRAFT` role on expiry — `Whitelisted` and
  `SMP Applicant` are never touched, so users never need to re-apply.
- **Audit commands** — `/audit user`, `/audit active`, `/audit expired`,
  `/audit pending`, all restricted to `MINECRAFT ADMIN`.
- **Self-healing channel setup** — creates `#zio-audit` and `#trial-channel`
  on startup if they don't exist yet, with correct permissions. It never
  creates roles or the three pre-existing channels; if a required role is
  missing it logs an error and posts a warning in `#zio-audit`.

## Project structure

```
bot/
├── main.py                 # Bot bootstrap, channel creation, extension loading
├── config.py                # Env vars + constants (channel IDs, role names)
├── database.py               # Motor/MongoDB access layer
├── cogs/
│   ├── whitelist.py           # on_member_join, /whitelist_accept
│   ├── payments.py            # Screenshot monitoring -> audit embed
│   ├── audit.py                # /audit user|active|expired|pending
│   └── subscriptions.py        # /renew + APScheduler expiry/reminder job
├── views/
│   └── payment_buttons.py       # Persistent Approve/Reject button view
├── models/
│   └── user_model.py             # `users` collection schema
├── utils/
│   ├── embeds.py                  # Embed builders
│   └── logger.py                   # Logging setup
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

1. **Python 3.11+** required.

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Discord application**

   - Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
   - Enable the **Server Members Intent** and **Message Content Intent** under
     Bot → Privileged Gateway Intents (required for whitelist role assignment
     and screenshot detection).
   - Invite the bot with `applications.commands`, `bot` scopes and at minimum:
     Manage Roles, Manage Channels, Send Messages, Read Message History,
     Attach Files, Add Reactions.
   - **Role position**: the bot's own role must sit **above** `MINECRAFT`,
     `Whitelisted`, and `SMP Applicant` in the role list, or role
     add/remove calls will fail with a 403.

3. **MongoDB Atlas**

   - Create a free/shared cluster, a database user, and allow network access
     from wherever the bot runs (or `0.0.0.0/0` for simplicity during setup).
   - Copy the connection string into `MONGODB_URI`.

4. **Environment**

   ```bash
   cp .env.example .env
   # then fill in DISCORD_TOKEN and MONGODB_URI (and optionally GUILD_ID)
   ```

   Setting `GUILD_ID` makes slash commands sync instantly to that one server
   — recommended during development. Leave it blank for global sync (can take
   up to an hour to appear).

5. **Run**

   ```bash
   python main.py
   ```

   On first startup the bot will create `#zio-audit` and `#trial-channel` in
   every guild it's in (skipping any that already exist) and register its
   persistent button view.

## Required pre-existing server setup

The bot assumes these already exist and will **never** create them:

**Channels**

| Purpose               | Channel ID           |
|------------------------|-----------------------|
| Payment gateway (QR)   | `1527346320434528377` |
| Whitelisting           | `1527323483078529074` |
| Payment confirmation   | `1527366877234335844` |

**Roles** (fetched by exact name each time they're needed)

- `MINECRAFT ADMIN`
- `MINECRAFT`
- `Whitelisted`
- `SMP Applicant`

If any of these roles is missing, the bot logs an error and posts a warning
in `#zio-audit` instead of creating the role automatically.

## Commands

All admin commands require the `MINECRAFT ADMIN` role.

| Command                       | Description                                   |
|--------------------------------|------------------------------------------------|
| `/whitelist_accept @user`       | Whitelist an applicant, DM payment instructions |
| `/audit user @user`              | Show one user's full audit record               |
| `/audit active`                   | List users with an active subscription          |
| `/audit expired`                   | List users whose subscription has expired       |
| `/audit pending`                    | List users awaiting payment verification        |
| `/renew @user`                        | Extend a user's subscription by 30 days         |

## Notes on the scheduler

The daily job runs at **00:05 UTC** (see `cogs/subscriptions.py`,
`CronTrigger(hour=0, minute=5)`) and:

1. Expires any active subscription whose `subscription_end` has passed,
   removing only the `MINECRAFT` role.
2. Sends 7-day / 3-day / 1-day expiry reminder DMs, tracked per-user in
   MongoDB (`reminder_7d_sent_at`, etc.) so nobody gets duplicate reminders.

Adjust the cron schedule to your preferred time zone/hour as needed.
