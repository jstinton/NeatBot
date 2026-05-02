# NeatBot

NeatBot is a Discord bourbon bot built with Python, `discord.py`, and guild-scoped slash commands.

## Commands

- `/bottle name:` looks up proof, style, MSRP, profile, and similar bottles.
- `/worth name: price:` compares a shelf price to MSRP, fair price, and secondary-ish pricing.
- `/compare bottle_one: bottle_two:` compares two bottles and recommends a pick.

## Local Setup

Create `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token_here
GUILD_ID=your_discord_server_id_here
```

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
   - `GUILD_ID`
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
   - `GUILD_ID`
5. Deploy.

The included `render.yaml` defines the worker shape, but secrets still need to be entered in Render.

## Adding Bottles

Edit `bottles.json`, then restart the bot. You do not need to resync slash commands when only bottle data changes.
