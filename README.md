# NeatBot

NeatBot is a Discord bourbon bot built with Python, `discord.py`, and guild-scoped slash commands.

## Commands

- `/bottle name:` looks up proof, style, MSRP, profile, and similar bottles.
- `/worth name: price:` compares a shelf price to MSRP, fair price, and secondary-ish pricing.
- `/compare bottle_one: bottle_two:` compares two bottles and recommends a pick.
- `/boty name:` starts a Bottle of the Year scorecard with 1-10 rating buttons and creates a discussion thread.
- `/battle bottle_one: bottle_two:` starts a head-to-head vote and marks the winner with a trophy and the loser with a poop emoji.
- `/alloc-add name:` logs an allocation by hand when the tracker does not pick up a post.
- `/alloc-leaderboard` shows the annual allocation rankings.
- `/alloc-stats` shows your own allocation totals, rank, and recent pickups.

## Allocation Tracker

In any channel whose name contains `allocation-tracker` (configurable with
`ALLOCATION_TRACKER_CHANNEL_NAME`), NeatBot watches for bottle posts and replies with a
Confirm/Cancel prompt. Threads and forum posts under that channel count too. Confirming
writes the pickup to the annual leaderboard; duplicates from the same person within
`ALLOCATION_DUPLICATE_HOURS` are ignored.

Detection matches a message against `bottles.json` names and aliases plus the curated
`ALLOCATION_EXTRA_ALIASES` table in `bot.py`. Shorthand shorter than the stored name (for
example `Michter's 10` or `King of Kentucky`) is matched word-by-word against bottle names.
If a bottle still is not recognized, add it to `ALLOCATION_EXTRA_ALIASES` — and use
`/alloc-add` in the meantime so the pickup is not lost.

Allocation history lives in SQLite at `ALLOCATION_DB_PATH`. **This must point at a mounted
volume** (`/data/allocations.db`), or every deploy erases the year. The bot prints a warning
on startup if the path is not under `/data`.

BOTY and Battle votes are stored in local JSON files on the running service. For permanent cross-deploy history, move vote storage to a database later.

## Local Setup

Create `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token_here
GUILD_IDS=your_first_server_id_here,your_second_server_id_here
```

For one server, `GUILD_ID=your_discord_server_id_here` still works. For multiple servers, use `GUILD_IDS` with comma-separated server IDs.

Install and run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONPYCACHEPREFIX=.pycache .venv/bin/python bot.py
```

## Always-On Hosting

Use a worker/background service, not a web service. The bot keeps a gateway connection open to Discord and does not need an HTTP port.

### Railway

1. Push this folder to GitHub.
2. In Railway, create a new project from the GitHub repo.
3. Railway can use the included `Dockerfile` and `railway.json`.
4. Add service variables:
   - `DISCORD_TOKEN`
   - `GUILD_IDS`
5. Deploy.

Railway docs: start commands are the process used to run the deployment, and variables are exposed to the running service as environment variables.

### Render

1. Push this folder to GitHub.
2. In Render, create a new Background Worker from the GitHub repo.
3. Use:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python bot.py`
4. Add environment variables:
   - `DISCORD_TOKEN`
   - `GUILD_IDS`
5. Deploy.

The included `render.yaml` defines the worker shape, but secrets still need to be entered in Render.

## Adding Bottles

Edit `bottles.json`, then restart the bot. You do not need to resync slash commands when only bottle data changes.
