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

Restart the bot after any change. You do not need to resync slash commands when only
bottle data changes.

### Preferred: merge a seed file

Do not hand-edit `bottles.json` for anything more than a one-line tweak — it is 1,400+
entries and it is easy to create a duplicate of a bottle that already exists under a
different name. Use the merge script instead:

```sh
python3 scripts/import_alias_seed.py scripts/seeds/your-seed.json
```

A seed file is a list of `{name, aliases}` objects:

```json
{
  "bottles": [
    {
      "name": "Elmer T. Lee Single Barrel",
      "aliases": ["Elmer T. Lee", "Elmer T Lee", "Elmer Lee", "ETL"]
    }
  ]
}
```

The script:

- writes a timestamped backup to `backups/` first
- matches each seed entry against every existing name **and alias**, ignoring case,
  punctuation, and spacing
- adds only the new aliases when the bottle already exists, never removing an existing one
- creates a minimal `{name, aliases}` entry when it does not
- skips an entry that matches more than one existing bottle rather than guessing

Re-running the same seed is a no-op, so seeds are safe to keep and replay.
`scripts/seeds/allocation-gaps.json` is a worked example.

### Pricing fields are optional

Only about 8% of entries carry `proof`, `msrp`, `profile`, and the price ranges; the rest
are `{name, aliases}` only. The bot degrades gracefully — `/bottle` shows "Unknown" and
`/worth` says it does not have enough pricing data. So **add the name and aliases now and
fill in pricing later**; an alias-only entry is what makes the allocation tracker, `/bottle`,
`/compare`, and `/bottlelist` recognize a bottle at all.

To add pricing to an existing entry, edit it in place with the fields shown on any bottle
that has them (`proof`, `style`, `msrp`, `fair_price_low`, `fair_price_high`,
`secondary_low`, `secondary_high`, `profile`, `similar`, `description`, `verdict_notes`,
`community_score`).

### Which aliases to include

The allocation tracker matches what people actually type, so include the shorthand:
initialisms (`ETL`, `WSR`, `RHF`), the spelling without punctuation (`Michters 10`), and
common nicknames (`Green Label Weller`, `Lot B`). Aliases of three characters or fewer are
matched as whole words only, so they will not fire inside unrelated text.

### Community submissions

`/suggestbottle` writes to `COMMUNITY_BOTTLES_PATH` (`/data/community_bottles.json`), which
is layered over `bottles.json` at load time. That file lives on the volume, not in git — it
is the right place for one-off member additions, and `bottles.json` is the right place for
anything you want in the repo.
