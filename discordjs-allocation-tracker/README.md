# NeatBot Allocation Tracker

Discord.js v14 allocation tracker for the `🔢allocation-tracker` channel.

## What It Does

- Listens to normal messages in `🔢allocation-tracker`
- Detects likely allocation success posts like `Got a RR15 at Binny's today`
- Ignores obvious false positives like `Anyone seen Stagg?` or `ISO JD14`
- Asks the poster to confirm with buttons
- Saves confirmed allocations to SQLite
- Maintains one persistent annual leaderboard message
- Preserves historical data and filters by year
- Provides `/alloc-stats` and `/alloc-leaderboard`

## File Structure

```text
discordjs-allocation-tracker/
  package.json
  .env.example
  README.md
  src/
    index.js
    deploy-commands.js
    config.js
    database.js
    commands/
      alloc-leaderboard.js
      alloc-stats.js
    events/
      interactionCreate.js
      messageCreate.js
    services/
      allocationQueries.js
      leaderboard.js
    utils/
      bottleAliases.js
      detector.js
      text.js
```

## Install

```bash
cd discordjs-allocation-tracker
npm install
cp .env.example .env
```

Fill in `.env`:

```text
DISCORD_TOKEN=your_discord_bot_token
CLIENT_ID=your_discord_application_client_id
GUILD_ID=your_server_id_for_fast_command_registration
ALLOCATION_TRACKER_CHANNEL_NAME=🔢allocation-tracker
ALLOCATION_DB_PATH=/data/allocations.db
```

## Discord Developer Portal

Enable these bot permissions/intents:

- Server Members Intent: not required
- Message Content Intent: required
- Bot permissions:
  - View Channels
  - Send Messages
  - Read Message History
  - Embed Links
  - Use Application Commands

## Register Slash Commands

```bash
npm run deploy
```

## Run Locally

```bash
npm start
```

## Railway Setup

1. Create a Railway volume.
2. Mount it to:

```text
/data
```

3. Set variable:

```text
ALLOCATION_DB_PATH=/data/allocations.db
```

4. Start command:

```bash
npm start
```

5. Run command registration once from Railway shell or locally:

```bash
npm run deploy
```

## Duplicate Protection

The same user cannot log the same bottle again within 6 hours.

Override:

```text
ALLOCATION_DUPLICATE_WINDOW_HOURS=6
```

## Add Aliases

Edit:

```text
src/utils/bottleAliases.js
```

Put the most specific aliases first when adding ambiguous terms.
