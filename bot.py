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

DATA_PATH = Path(__file__).parent / "bottles.json"


def load_bottles():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


BOTTLES = load_bottles()
BOTTLE_NAMES = list(BOTTLES.keys())


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
    msrp = data["msrp"]
    fair_low = data["fair_price_low"]
    fair_high = data["fair_price_high"]
    secondary_high = data["secondary_high"]

    if price <= msrp:
        return "🦄 Unicorn buy", "At or below MSRP. Buy it if you actually want the bottle."
    if price <= fair_low:
        return "🟢 Buy", "Above MSRP, but still a strong buy in today’s market."
    if price <= fair_high:
        return "🟡 Fair but not exciting", "Reasonable drinker price, but not a steal."
    if price <= secondary_high:
        return "🟠 Only if you really want it", "You are paying collector/secondary-ish pricing."
    return "🔴 Pass", "That price is deep into emotional damage territory."


def bottle_embed(name: str, data: dict):
    embed = discord.Embed(
        title=f"🥃 {name}",
        description=data.get("description", "No description yet."),
        color=discord.Color.gold()
    )

    embed.add_field(name="Proof", value=str(data.get("proof", "Unknown")), inline=True)
    embed.add_field(name="Style", value=data.get("style", "Unknown"), inline=True)
    embed.add_field(name="MSRP", value=f"${data.get('msrp', 'Unknown')}", inline=True)
    embed.add_field(name="Profile", value=data.get("profile", "Unknown"), inline=False)
    embed.add_field(
        name="Similar Bottles",
        value=", ".join(data.get("similar", [])) or "None listed",
        inline=False
    )

    embed.set_footer(text="NeatBot bottle data is guidance only. Drink what you like.")

    return embed


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} command(s) to guild {GUILD_ID}")
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

    embed.add_field(name="MSRP", value=f"${data['msrp']}", inline=True)
    embed.add_field(
        name="Fair Drinker Price",
        value=f"${data['fair_price_low']}–${data['fair_price_high']}",
        inline=True
    )
    embed.add_field(
        name="Secondary-ish Range",
        value=f"${data['secondary_low']}–${data['secondary_high']}",
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


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN. Put it in your .env file.")

bot.run(TOKEN)
