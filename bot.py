import os
import json
import difflib
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
GUILD_IDS = os.getenv("GUILD_IDS")

DATA_PATH = Path(__file__).parent / "bottles.json"
BOTY_VOTES_PATH = Path(__file__).parent / "boty_votes.json"
BATTLE_VOTES_PATH = Path(__file__).parent / "battle_votes.json"


def load_bottles():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


BOTTLES = load_bottles()
BOTTLE_NAMES = list(BOTTLES.keys())


def parse_guild_ids():
    raw_ids = GUILD_IDS or GUILD_ID or ""
    guild_ids = []

    for raw_id in raw_ids.split(","):
        guild_id = raw_id.strip()

        if guild_id:
            guild_ids.append(int(guild_id))

    return guild_ids


def configure_guild_commands():
    for guild_id in parse_guild_ids():
        guild = discord.Object(id=guild_id)
        bot.tree.copy_global_to(guild=guild)


def load_json(path: Path, default):
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


BOTY_VOTES = load_json(BOTY_VOTES_PATH, {})
BATTLE_VOTES = load_json(BATTLE_VOTES_PATH, {})


def normalize(text: str) -> str:
    return text.lower().strip().replace("'", "").replace("’", "")


def find_bottle(query: str):
    q = normalize(query)

    for name in BOTTLE_NAMES:
        if q == normalize(name):
            return name, BOTTLES[name]

    for name, data in BOTTLES.items():
        for alias in data.get("aliases", []):
            if q == normalize(alias):
                return name, data

    searchable = BOTTLE_NAMES[:]
    alias_to_name = {}

    for name, data in BOTTLES.items():
        for alias in data.get("aliases", []):
            searchable.append(alias)
            alias_to_name[alias] = name

    matches = difflib.get_close_matches(query, searchable, n=1, cutoff=0.55)

    if not matches:
        return None, None

    matched = matches[0]
    canonical = alias_to_name.get(matched, matched)

    return canonical, BOTTLES[canonical]


def price_verdict(price: float, data: dict):
    msrp = data.get("msrp")
    fair_low = data.get("fair_price_low")
    fair_high = data.get("fair_price_high")
    secondary_high = data.get("secondary_high")

    if any(value is None for value in [msrp, fair_low, fair_high, secondary_high]):
        return (
            "🟡 Fair but not exciting",
            "NeatBot does not have enough pricing data for this bottle yet. Use recent local comps before buying."
        )

    if price <= msrp:
        return "🦄 Unicorn buy", "At or below MSRP. Buy it if you actually want the bottle."
    if price <= fair_low:
        return "🟢 Buy", "Above MSRP, but still a strong buy in today’s market."
    if price <= fair_high:
        return "🟡 Fair but not exciting", "Reasonable drinker price, but not a steal."
    if price <= secondary_high:
        return "🟠 Only if you really want it", "You are paying collector/secondary-ish pricing."
    return "🔴 Pass", "That price is deep into emotional damage territory."


def dollars(value):
    if value is None:
        return "Unknown"

    return f"${value}"


def bottle_embed(name: str, data: dict):
    embed = discord.Embed(
        title=f"🥃 {name}",
        description=data.get("description", "No description yet."),
        color=discord.Color.gold()
    )

    embed.add_field(name="Proof", value=str(data.get("proof", "Unknown")), inline=True)
    embed.add_field(name="Style", value=data.get("style", "Unknown"), inline=True)
    embed.add_field(name="MSRP", value=dollars(data.get("msrp")), inline=True)
    embed.add_field(name="Profile", value=data.get("profile", "Unknown"), inline=False)
    embed.add_field(
        name="Similar Bottles",
        value=", ".join(data.get("similar", [])) or "None listed",
        inline=False
    )

    embed.set_footer(text="NeatBot bottle data is guidance only. Drink what you like.")

    return embed


def average_score(votes: dict) -> float:
    if not votes:
        return 0

    return sum(votes.values()) / len(votes)


def boty_embed(message_id: str):
    state = BOTY_VOTES[message_id]
    bottle_name = state["bottle"]
    votes = state.get("votes", {})
    average = average_score(votes)

    embed = discord.Embed(
        title=f"🏆 BOTY Score: {bottle_name}",
        description="Click a button from 1-10 to rate this bottle. Your latest vote replaces your previous vote.",
        color=discord.Color.gold()
    )

    embed.add_field(name="Average Score", value=f"{average:.2f}/10" if votes else "No votes yet", inline=True)
    embed.add_field(name="Votes", value=str(len(votes)), inline=True)
    embed.set_footer(text="BOTY = Bottle of the Year. Discuss this bottle in the thread.")

    return embed


def battle_embed(message_id: str):
    state = BATTLE_VOTES[message_id]
    bottle_one = state["bottle_one"]
    bottle_two = state["bottle_two"]
    votes = state.get("votes", {})
    one_votes = sum(1 for pick in votes.values() if pick == 1)
    two_votes = sum(1 for pick in votes.values() if pick == 2)

    if one_votes > two_votes:
        one_label = f"🏆 {bottle_one}"
        two_label = f"💩 {bottle_two}"
    elif two_votes > one_votes:
        one_label = f"💩 {bottle_one}"
        two_label = f"🏆 {bottle_two}"
    else:
        one_label = f"⚔️ {bottle_one}"
        two_label = f"⚔️ {bottle_two}"

    embed = discord.Embed(
        title="🥃 Bottle Battle",
        description="Vote for the bottle you would rather pour. Your latest vote replaces your previous vote.",
        color=discord.Color.blurple()
    )
    embed.add_field(name=one_label, value=f"{one_votes} vote(s)", inline=True)
    embed.add_field(name=two_label, value=f"{two_votes} vote(s)", inline=True)
    embed.add_field(name="Total Votes", value=str(len(votes)), inline=False)
    embed.set_footer(text="Winner gets the trophy. Loser gets humbled.")

    return embed


def recover_boty_state(message: discord.Message):
    for embed in message.embeds:
        title = embed.title or ""
        prefix = "🏆 BOTY Score: "

        if title.startswith(prefix):
            bottle_name = title[len(prefix):].strip()

            if bottle_name and bottle_name != "Unknown bottle":
                return {
                    "bottle": bottle_name,
                    "votes": {}
                }

    thread = getattr(message, "thread", None)

    if thread and thread.name.startswith("BOTY: "):
        bottle_name = thread.name[len("BOTY: "):].strip()

        if bottle_name:
            return {
                "bottle": bottle_name,
                "thread_id": thread.id,
                "votes": {}
            }

    return None


def clean_battle_bottle_label(label: str) -> str:
    for marker in ("🏆 ", "💩 ", "⚔️ "):
        if label.startswith(marker):
            return label[len(marker):].strip()

    return label.strip()


def recover_battle_state(message: discord.Message):
    for embed in message.embeds:
        if len(embed.fields) < 2:
            continue

        bottle_one = clean_battle_bottle_label(embed.fields[0].name)
        bottle_two = clean_battle_bottle_label(embed.fields[1].name)

        if bottle_one and bottle_two:
            state = {
                "bottle_one": bottle_one,
                "bottle_two": bottle_two,
                "votes": {}
            }

            thread = getattr(message, "thread", None)

            if thread:
                state["thread_id"] = thread.id

            return state

    return None


class BOTYView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for score in range(1, 11):
            self.add_item(BOTYScoreButton(score))


class BOTYScoreButton(discord.ui.Button):
    def __init__(self, score: int):
        super().__init__(
            label=str(score),
            style=discord.ButtonStyle.secondary,
            custom_id=f"boty_score:{score}",
            row=0 if score <= 5 else 1
        )
        self.score = score

    async def callback(self, interaction: discord.Interaction):
        message_id = str(interaction.message.id)

        if message_id not in BOTY_VOTES:
            recovered_state = recover_boty_state(interaction.message)

            if not recovered_state:
                await interaction.response.send_message(
                    "I lost the saved state for this BOTY post. Please start a new `/boty` post for this bottle.",
                    ephemeral=True
                )
                return

            BOTY_VOTES[message_id] = recovered_state

        BOTY_VOTES[message_id].setdefault("votes", {})[str(interaction.user.id)] = self.score
        save_json(BOTY_VOTES_PATH, BOTY_VOTES)

        await interaction.response.send_message(
            f"Your BOTY score is locked in: {self.score}/10.",
            ephemeral=True
        )
        await interaction.message.edit(embed=boty_embed(message_id), view=BOTYView())


class BattleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BattleVoteButton(1))
        self.add_item(BattleVoteButton(2))


class BattleVoteButton(discord.ui.Button):
    def __init__(self, pick: int):
        super().__init__(
            label=f"Vote Bottle {pick}",
            style=discord.ButtonStyle.primary if pick == 1 else discord.ButtonStyle.danger,
            custom_id=f"battle_vote:{pick}"
        )
        self.pick = pick

    async def callback(self, interaction: discord.Interaction):
        message_id = str(interaction.message.id)

        if message_id not in BATTLE_VOTES:
            recovered_state = recover_battle_state(interaction.message)

            if not recovered_state:
                await interaction.response.send_message(
                    "I can’t find this battle in the vote database anymore. Please start a new `/battle` post.",
                    ephemeral=True
                )
                return

            BATTLE_VOTES[message_id] = recovered_state

        BATTLE_VOTES[message_id].setdefault("votes", {})[str(interaction.user.id)] = self.pick
        save_json(BATTLE_VOTES_PATH, BATTLE_VOTES)

        chosen = BATTLE_VOTES[message_id]["bottle_one"] if self.pick == 1 else BATTLE_VOTES[message_id]["bottle_two"]
        await interaction.response.send_message(f"Vote counted for {chosen}.", ephemeral=True)
        await interaction.message.edit(embed=battle_embed(message_id), view=BattleView())


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    bot.add_view(BOTYView())
    bot.add_view(BattleView())
    configure_guild_commands()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        guild_ids = parse_guild_ids()
        command_names = ", ".join(f"/{command.name}" for command in bot.tree.get_commands())
        print(f"Loaded {len(bot.tree.get_commands())} global command(s): {command_names}")
        print(f"Configured guild IDs: {guild_ids or 'none; syncing globally'}")

        if guild_ids:
            for guild_id in guild_ids:
                guild = discord.Object(id=guild_id)
                synced = await bot.tree.sync(guild=guild)
                print(f"Synced {len(synced)} command(s) to guild {guild_id}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global command(s)")
    except Exception as e:
        print(f"Command sync failed: {e}")


@bot.tree.command(name="bottle", description="Look up bourbon info by bottle name.")
@app_commands.describe(name="Example: Weller Antique 107")
async def bottle(interaction: discord.Interaction, name: str):
    bottle_name, data = find_bottle(name)

    if not bottle_name:
        await interaction.response.send_message(
            f"Couldn’t find `{name}` yet. Ask a mod to add it to NeatBot’s bottle database.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(embed=bottle_embed(bottle_name, data))


@bot.tree.command(name="worth", description="Check if a bottle is worth the asking price.")
@app_commands.describe(
    name="Example: Weller Antique 107",
    price="Shelf price before tax, e.g. 89.99"
)
async def worth(interaction: discord.Interaction, name: str, price: float):
    bottle_name, data = find_bottle(name)

    if not bottle_name:
        await interaction.response.send_message(
            f"Couldn’t find `{name}` yet. Ask a mod to add it to NeatBot’s bottle database.",
            ephemeral=True
        )
        return

    verdict, why = price_verdict(price, data)

    embed = discord.Embed(
        title=f"{verdict}: {bottle_name} at ${price:,.2f}",
        description=why,
        color=discord.Color.orange()
    )

    embed.add_field(name="MSRP", value=dollars(data.get("msrp")), inline=True)
    embed.add_field(
        name="Fair Drinker Price",
        value=f"{dollars(data.get('fair_price_low'))}–{dollars(data.get('fair_price_high'))}",
        inline=True
    )
    embed.add_field(
        name="Secondary-ish Range",
        value=f"{dollars(data.get('secondary_low'))}–{dollars(data.get('secondary_high'))}",
        inline=True
    )
    embed.add_field(
        name="NeatBot Take",
        value=data.get("verdict_notes", "No extra notes yet."),
        inline=False
    )

    embed.set_footer(text="Pricing varies by state, store, timing, and chaos.")

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="compare", description="Compare two bourbon bottles.")
@app_commands.describe(
    bottle_one="Example: Stagg",
    bottle_two="Example: Elijah Craig Barrel Proof"
)
async def compare(interaction: discord.Interaction, bottle_one: str, bottle_two: str):
    name1, data1 = find_bottle(bottle_one)
    name2, data2 = find_bottle(bottle_two)

    missing = []

    if not name1:
        missing.append(bottle_one)

    if not name2:
        missing.append(bottle_two)

    if missing:
        await interaction.response.send_message(
            f"Couldn’t find: {', '.join(missing)}. Ask a mod to add it to the database.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"🥃 Compare: {name1} vs {name2}",
        description="Here’s the NeatBot side-by-side.",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name=name1,
        value=(
            f"**Proof:** {data1.get('proof', 'Unknown')}\n"
            f"**Style:** {data1.get('style', 'Unknown')}\n"
            f"**MSRP:** ${data1.get('msrp', 'Unknown')}\n"
            f"**Profile:** {data1.get('profile', 'Unknown')}"
        ),
        inline=True
    )

    embed.add_field(
        name=name2,
        value=(
            f"**Proof:** {data2.get('proof', 'Unknown')}\n"
            f"**Style:** {data2.get('style', 'Unknown')}\n"
            f"**MSRP:** ${data2.get('msrp', 'Unknown')}\n"
            f"**Profile:** {data2.get('profile', 'Unknown')}"
        ),
        inline=True
    )

    score1 = data1.get("community_score", 0)
    score2 = data2.get("community_score", 0)

    if score1 > score2:
        pick = f"**Pick:** {name1}, based on current NeatBot score."
    elif score2 > score1:
        pick = f"**Pick:** {name2}, based on current NeatBot score."
    else:
        pick = "**Pick:** Toss-up. Choose based on your preferred profile."

    embed.add_field(name="NeatBot Pick", value=pick, inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="boty", description="Start a Bottle of the Year rating with 1-10 buttons.")
@app_commands.describe(name="Example: Weller Antique 107")
async def boty(interaction: discord.Interaction, name: str):
    bottle_name, data = find_bottle(name)

    if not bottle_name:
        await interaction.response.send_message(
            f"Couldn’t find `{name}` yet. Ask a mod to add it to NeatBot’s bottle database.",
            ephemeral=True
        )
        return

    starter_embed = discord.Embed(
        title=f"🏆 BOTY Score: {bottle_name}",
        description="Click a button from 1-10 to rate this bottle. Your latest vote replaces your previous vote.",
        color=discord.Color.gold()
    )
    starter_embed.add_field(name="Proof", value=str(data.get("proof", "Unknown")), inline=True)
    starter_embed.add_field(name="Style", value=data.get("style", "Unknown"), inline=True)
    starter_embed.add_field(name="Average Score", value="No votes yet", inline=True)
    starter_embed.set_footer(text="BOTY = Bottle of the Year. A discussion thread will be created.")

    await interaction.response.send_message(embed=starter_embed, view=BOTYView())
    message = await interaction.original_response()
    message_id = str(message.id)

    BOTY_VOTES[message_id] = {
        "bottle": bottle_name,
        "votes": {}
    }
    save_json(BOTY_VOTES_PATH, BOTY_VOTES)

    try:
        thread = await message.create_thread(name=f"BOTY: {bottle_name}"[:100])
        BOTY_VOTES[message_id]["thread_id"] = thread.id
        save_json(BOTY_VOTES_PATH, BOTY_VOTES)
        await thread.send(f"Discuss **{bottle_name}** here. What score did it earn and why?")
    except discord.HTTPException:
        pass

    await message.edit(embed=boty_embed(message_id), view=BOTYView())


@bot.tree.command(name="battle", description="Start a head-to-head bottle battle vote.")
@app_commands.describe(
    bottle_one="Example: Stagg",
    bottle_two="Example: Elijah Craig Barrel Proof"
)
async def battle(interaction: discord.Interaction, bottle_one: str, bottle_two: str):
    name1, data1 = find_bottle(bottle_one)
    name2, data2 = find_bottle(bottle_two)

    missing = []

    if not name1:
        missing.append(bottle_one)

    if not name2:
        missing.append(bottle_two)

    if missing:
        await interaction.response.send_message(
            f"Couldn’t find: {', '.join(missing)}. Ask a mod to add it to the database.",
            ephemeral=True
        )
        return

    starter_embed = discord.Embed(
        title="🥃 Bottle Battle",
        description="Vote for the bottle you would rather pour. Your latest vote replaces your previous vote.",
        color=discord.Color.blurple()
    )
    starter_embed.add_field(
        name=f"⚔️ {name1}",
        value=f"**Proof:** {data1.get('proof', 'Unknown')}\n**Profile:** {data1.get('profile', 'Unknown')}",
        inline=True
    )
    starter_embed.add_field(
        name=f"⚔️ {name2}",
        value=f"**Proof:** {data2.get('proof', 'Unknown')}\n**Profile:** {data2.get('profile', 'Unknown')}",
        inline=True
    )
    starter_embed.set_footer(text="Winner gets the trophy. Loser gets humbled.")

    await interaction.response.send_message(embed=starter_embed, view=BattleView())
    message = await interaction.original_response()
    message_id = str(message.id)

    BATTLE_VOTES[message_id] = {
        "bottle_one": name1,
        "bottle_two": name2,
        "votes": {}
    }
    save_json(BATTLE_VOTES_PATH, BATTLE_VOTES)

    try:
        thread = await message.create_thread(name=f"Battle: {name1} vs {name2}"[:100])
        BATTLE_VOTES[message_id]["thread_id"] = thread.id
        save_json(BATTLE_VOTES_PATH, BATTLE_VOTES)
        await thread.send(
            f"Battle thread: **{name1}** vs **{name2}**.\n"
            "Make your case. Flavor, value, proof, hype, bottle kill stories, all of it."
        )
    except discord.HTTPException:
        pass

    await message.edit(embed=battle_embed(message_id), view=BattleView())


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN. Put it in your .env file.")

if __name__ == "__main__":
    bot.run(TOKEN)
