import os
import json
import difflib
import re
import uuid
import random
import ipaddress
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import quote_plus, unquote, urlparse
from pathlib import Path
from typing import Optional

import aiohttp
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
GUILD_IDS = os.getenv("GUILD_IDS")
BOTTLE_REVIEW_CHANNEL_ID = os.getenv("BOTTLE_REVIEW_CHANNEL_ID")
BOTTLE_REVIEW_CHANNEL_NAMES = [
    name.strip()
    for name in os.getenv(
        "BOTTLE_REVIEW_CHANNEL_NAMES",
        "bottle-review,bottle-submissions,mod-review,mod-bottle-review"
    ).split(",")
    if name.strip()
]

DATA_PATH = Path(__file__).parent / "bottles.json"
COMMUNITY_BOTTLES_PATH = Path(
    os.getenv(
        "COMMUNITY_BOTTLES_PATH",
        "/data/community_bottles.json" if Path("/data").exists() else Path(__file__).parent / "community_bottles.json"
    )
)
BOTTLE_SUBMISSIONS_PATH = Path(
    os.getenv(
        "BOTTLE_SUBMISSIONS_PATH",
        "/data/bottle_submissions.json" if Path("/data").exists() else Path(__file__).parent / "bottle_submissions.json"
    )
)
BOTY_VOTES_PATH = Path(__file__).parent / "boty_votes.json"
BATTLE_VOTES_PATH = Path(__file__).parent / "battle_votes.json"
WHADD_IMAGE_PATH = Path(__file__).parent / "assets" / "whadd.png"
NERD_IMAGE_PATH = Path(__file__).parent / "assets" / "nerd.jpg"
BRICKED_IMAGE_PATH = Path(__file__).parent / "assets" / "bricked.png"
DOXXED_IMAGE_PATH = Path(__file__).parent / "assets" / "doxxed.jpg"
ALLOCATION_DB_PATH = Path(
    os.getenv(
        "ALLOCATION_DB_PATH",
        "/data/allocations.db" if Path("/data").exists() else Path(__file__).parent / "allocations.db"
    )
)
ALLOCATION_TRACKER_CHANNEL_NAME = os.getenv("ALLOCATION_TRACKER_CHANNEL_NAME", "🔢allocation-tracker")
ALLOCATION_DUPLICATE_HOURS = int(os.getenv("ALLOCATION_DUPLICATE_HOURS", "6"))
ALLOCATION_BATCH_PATTERN = re.compile(
    r"\bbatch\s*(?:#|number|no\.?)?\s*(?P<batch>[a-z0-9][a-z0-9.\-]*)",
    re.IGNORECASE
)
STORE_PICK_MARKER_PATTERN = re.compile(
    r"\b(?:sp|store\s*pick|single\s*barrel\s*pick|barrel\s*pick)\b",
    re.IGNORECASE
)
ZIP_CODE_PATTERN = re.compile(r"^\d{5}$")
USER_MENTION_PATTERN = re.compile(r"<@!?(?P<user_id>\d+)>")
VINTAGE_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
DISCORD_ID_PATTERN = re.compile(r"^\d{15,25}$")
URL_PATTERN = re.compile(r"https?://\S+")
DISCORD_MESSAGE_LINK_PATTERN = re.compile(
    r"https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/channels/"
    r"(?P<guild_id>\d+|@me)/(?P<channel_id>\d+)/(?P<message_id>\d+)"
)


STORE_ROLE_MAP = {
    "Binny's Bucktown": {
        "address": "2409 N Elston Ave, Chicago, IL 60614",
        "role_id": "1470964559740403722",
    },
    "Binny's Oak Brook": {
        "address": "1500 16th St Ste A, Oak Brook, IL 60523",
        "role_id": "1470964788749402254",
    },
    "Binny's Lincoln Park": {
        "address": "1720 N Marcey St, Chicago, IL 60614",
        "role_id": "1470966132537168090",
    },
    "Binny's Rockford": {
        "address": "6363 E State St, Rockford, IL 61108",
        "role_id": "1470967512953917541",
    },
    "Binny's River North": {
        "address": "213 W Grand Ave, Chicago, IL 60654",
        "role_id": "1470968160047071314",
    },
    "Binny's South Loop": {
        "address": "1132 S Jefferson St, Chicago, IL 60607",
        "role_id": "1470968434434244689",
    },
    "Binny's Logan Square": {
        "address": "3934 W Diversey Ave, Chicago, IL 60647",
        "role_id": "1470969243775406202",
    },
    "Binny's Lakeview": {
        "address": "3000 N Clark St, Chicago, IL 60657",
        "role_id": "1470969593446006837",
    },
    "Binny's Elmwood Park": {
        "address": "7330 W North Ave, Elmwood Park, IL 60707",
        "role_id": "1470977144321478841",
    },
    "Almost Wisconsin (NW Burb)": {
        "address": "TBD",
        "role_id": None,
    },
    "NorthBurbs": {
        "address": "TBD",
        "role_id": None,
    },
    "OutWESTTTT": {
        "address": "TBD",
        "role_id": None,
    },
    "NW City": {
        "address": "TBD",
        "role_id": None,
    },
}

TATER_STORE_CHOICES = [
    app_commands.Choice(name=store_name, value=store_name)
    for store_name in STORE_ROLE_MAP
]
TATER_FIND_TYPE_CHOICES = [
    app_commands.Choice(name="On Shelf", value="on_shelf"),
    app_commands.Choice(name="Brown Bag", value="brown_bag"),
]


def load_bottles():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        bottles = json.load(f)

    if COMMUNITY_BOTTLES_PATH.exists():
        with open(COMMUNITY_BOTTLES_PATH, "r", encoding="utf-8") as f:
            community_bottles = json.load(f)

        if isinstance(community_bottles, dict):
            bottles.update(community_bottles)

    return bottles


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
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


BOTTLE_SUBMISSIONS = load_json(BOTTLE_SUBMISSIONS_PATH, {})


def configured_tater_location(store: Optional[str], location: Optional[str]):
    store_config = STORE_ROLE_MAP.get(store or "", {})
    configured_address = store_config.get("address")

    if configured_address and configured_address != "TBD":
        return configured_address

    return location


def tater_role_tag(store: Optional[str]):
    role_id = STORE_ROLE_MAP.get(store or "", {}).get("role_id")

    if role_id and DISCORD_ID_PATTERN.fullmatch(role_id):
        return f"<@&{role_id}>"

    return None


def tater_price(value: Optional[float]):
    if value is None:
        return None

    numeric_value = float(value)

    if numeric_value.is_integer():
        return f"${int(numeric_value):,}"

    return f"${numeric_value:,.2f}"


def tater_find_type_label(find_type: Optional[str]):
    if not find_type:
        return None

    normalized_type = normalize(find_type).replace(" ", "_").replace("-", "_")

    if normalized_type in {"on_shelf", "shelf", "on_the_shelf"}:
        return "🛒 On Shelf"

    if normalized_type in {"brown_bag", "brownbag", "bag", "brown"}:
        return "🛍️ Brown Bag"

    return None


def google_maps_url(location: str):
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(location)}"


def tater_store_location_link(store: Optional[str], location: Optional[str]):
    if not store and not location:
        return None

    if not store:
        return f"[{location}]({google_maps_url(location)})" if location else None

    if not location:
        return store

    label = f"{store} — {location}"

    return f"[{label}]({google_maps_url(location)})"


def has_store_pick_marker(value: Optional[str]):
    return bool(value and STORE_PICK_MARKER_PATTERN.search(value))


def strip_store_pick_marker(value: str):
    stripped = STORE_PICK_MARKER_PATTERN.sub(" ", value)
    stripped = re.sub(r"\s+", " ", stripped)
    stripped = re.sub(r"\s+([,;:/-])\s+", r" \1 ", stripped)
    return stripped.strip(" -:;,")


def format_store_pick_name(bottle_name: str, source: Optional[str] = None):
    display = f"{bottle_name} Store Pick"

    if source:
        display = f"{display} — {source}"

    return display


def store_pick_source_from_context(*values: Optional[str]):
    for value in values:
        if value and value != "TBD":
            return value

    return None


def taterfind_message(
    *,
    bottle: str,
    store: Optional[str],
    location: Optional[str],
    find_type: Optional[str],
    price: Optional[float],
    quantity: Optional[int],
    notes: Optional[str],
    source_link: Optional[str],
    source_preview: Optional[str],
):
    lines = [
        "🥃 **TATER FIND ALERT** 🥃",
        "",
        f"**Bottle:** {bottle}",
    ]

    store_location = tater_store_location_link(store, location)

    if store_location:
        lines.append(f"**Store:** {store_location}")

    find_type_label = tater_find_type_label(find_type)

    if find_type_label:
        lines.append(f"**Find Type:** {find_type_label}")

    formatted_price = tater_price(price)

    if formatted_price:
        lines.append(f"**Price:** {formatted_price}")

    if quantity is not None:
        lines.append(f"**Qty Seen:** {quantity}")

    if notes:
        lines.append(f"**Notes:** {notes}")

    if source_preview:
        lines.extend(["", source_preview])

    if source_link and not source_preview:
        lines.append(f"**Source Post:** [Open post]({source_link})")

    role_tag = tater_role_tag(store)

    if role_tag:
        lines.extend(["", f"{role_tag} — heads up! 🔔"])

    lines.extend(["", "_Posted via /taterfind · NeatBot_"])

    return "\n".join(lines)


def clean_source_link(value: Optional[str]):
    if not value:
        return None

    match = URL_PATTERN.search(value.strip())

    if not match:
        return None

    return match.group(0).rstrip(").,]>")


def extract_source_link_from_notes(notes: Optional[str]):
    source_link = clean_source_link(notes)

    if not notes or not source_link:
        return notes, None

    cleaned_notes = notes.replace(source_link, "").strip()
    cleaned_notes = re.sub(r"\s{2,}", " ", cleaned_notes).strip(" -—:|")

    return cleaned_notes or None, source_link


def discord_message_link_ids(source_link: Optional[str]):
    if not source_link:
        return None

    match = DISCORD_MESSAGE_LINK_PATTERN.search(source_link)

    if not match:
        return None

    return int(match.group("channel_id")), int(match.group("message_id"))


def preview_message_text(message: discord.Message):
    content = (message.content or "").strip()

    if not content and message.embeds:
        embed = message.embeds[0]
        content = (embed.description or embed.title or "").strip()

    if not content and message.attachments:
        content = "Attachment included in source post."

    if not content:
        content = "Source post preview unavailable."

    content = re.sub(r"\s+", " ", content)

    if len(content) > 420:
        content = f"{content[:417]}..."

    return content


async def source_post_preview(source_link: Optional[str]):
    ids = discord_message_link_ids(source_link)

    if not ids:
        return None

    channel_id, message_id = ids

    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)

        if not hasattr(channel, "fetch_message"):
            return None

        message = await channel.fetch_message(message_id)
    except discord.HTTPException:
        return None

    channel_name = getattr(channel, "name", "source")
    timestamp = discord.utils.format_dt(message.created_at, "t")
    text = preview_message_text(message)

    return (
        "↪ **Forwarded**\n"
        f"{text}\n"
        f"[#{channel_name}]({source_link}) · {timestamp} ›"
    )


def parse_tater_price(value: Optional[str]):
    if not value:
        return None

    cleaned = value.strip().replace("$", "").replace(",", "")

    if not cleaned:
        return None

    return float(cleaned)


def parse_tater_quantity(value: Optional[str]):
    if not value:
        return None

    cleaned = value.strip()

    if not cleaned:
        return None

    return int(cleaned)


def match_tater_store(value: Optional[str]):
    if not value:
        return None, None

    cleaned = value.strip()

    if not cleaned:
        return None, None

    normalized_input = normalize(cleaned)
    normalized_stores = {normalize(store_name): store_name for store_name in STORE_ROLE_MAP}

    if normalized_input in normalized_stores:
        store = normalized_stores[normalized_input]
        return store, configured_tater_location(store, None)

    for normalized_store, store in normalized_stores.items():
        if normalized_input in normalized_store:
            return store, configured_tater_location(store, None)

    matches = difflib.get_close_matches(normalized_input, list(normalized_stores.keys()), n=1, cutoff=0.72)

    if matches:
        store = normalized_stores[matches[0]]
        return store, configured_tater_location(store, None)

    return None, cleaned


def parse_tater_find_type(value: Optional[str]):
    if not value:
        return None

    cleaned = value.strip()

    if not cleaned:
        return None

    normalized_type = normalize(cleaned).replace(" ", "_").replace("-", "_")

    if normalized_type in {"on_shelf", "shelf", "on_the_shelf"}:
        return "on_shelf"

    if normalized_type in {"brown_bag", "brownbag", "bag", "brown"}:
        return "brown_bag"

    return None


async def post_tater_find_alert(
    interaction: discord.Interaction,
    *,
    bottle: str,
    store: Optional[str],
    location: Optional[str],
    find_type: Optional[str],
    price: Optional[float],
    quantity: Optional[int],
    notes: Optional[str],
    source_link: Optional[str],
    photo: Optional[discord.Attachment] = None
):
    if price is not None and price < 0:
        await interaction.followup.send("Price cannot be negative.", ephemeral=True)
        return

    if quantity is not None and quantity < 1:
        await interaction.followup.send("Quantity needs to be at least 1.", ephemeral=True)
        return

    try:
        channel = interaction.channel

        if channel is None or not hasattr(channel, "send"):
            await interaction.followup.send(
                "I can’t post alerts in this channel.",
                ephemeral=True
            )
            return

        resolved_location = configured_tater_location(store, location)
        is_store_pick = has_store_pick_marker(bottle)
        bottle_lookup = strip_store_pick_marker(bottle) if is_store_pick else bottle
        bottle_name, _ = find_bottle(bottle_lookup)
        display_bottle = bottle_name or canonical_bottle_name(bottle_lookup)

        if is_store_pick:
            pick_source = store_pick_source_from_context(store, resolved_location)
            display_bottle = format_store_pick_name(display_bottle, pick_source)

        notes, extracted_source_link = extract_source_link_from_notes(notes)
        display_source_link = clean_source_link(source_link) or extracted_source_link
        display_source_preview = await source_post_preview(display_source_link)
        content = taterfind_message(
            bottle=display_bottle,
            store=store,
            location=resolved_location,
            find_type=find_type,
            price=price,
            quantity=quantity,
            notes=notes,
            source_link=display_source_link,
            source_preview=display_source_preview,
        )
        embed = None

        if photo:
            embed = discord.Embed(color=discord.Color.from_str("#C9973A"))
            embed.set_image(url=photo.url)

        post = await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True)
        )
    except ValueError:
        await interaction.followup.send(
            "Price must be a number and quantity must be a whole number.",
            ephemeral=True
        )
        return
    except discord.HTTPException:
        await interaction.followup.send(
            "I could not post in this channel. A mod may need to check my permissions.",
            ephemeral=True
        )
        return
    except Exception as error:
        print(f"/taterfind failed: {error}")
        await interaction.followup.send(
            "Something went sideways while posting that tater find. I logged the error so it can be fixed.",
            ephemeral=True
        )
        return

    await interaction.followup.send(
        f"Tater find posted: {post.jump_url}",
        ephemeral=True
    )


BOTY_VOTES = load_json(BOTY_VOTES_PATH, {})
BATTLE_VOTES = load_json(BATTLE_VOTES_PATH, {})
FLIP_HELP_SESSIONS = {}
FLIP_FORM_DRAFTS = {}

SASSY_ONE_LINERS = [
    "Your bottle flex has been reviewed by the committee and sentenced to the bottom shelf 💅",
    "That pour opened up after twenty minutes, unlike your personality at a bottle share 💅",
    "You call it a bunker, I call it a cry for oak-scented help 💅",
    "Your palate notes say dark fruit, but your buying habits say panic and poor lighting 💅",
    "Another allocated bottle acquired, another shred of dignity left in the parking lot 💅",
    "That cork pop was louder than your financial judgment 💅",
    "You nosed that sample like it owed you a Weller pick 💅",
    "The bottle is rare, the self-control is rarer 💅",
    "Your shelf looks curated by a raffle addiction with Wi-Fi 💅",
    "That was not a neck pour, that was your expectations falling down the stairs 💅",
    "You paid secondary and called it research, which is adorable 💅",
    "The tater energy is strong enough to power a warehouse fan 💅",
    "Your collection has more backup bottles than your life has backup plans 💅",
    "You said daily drinker and reached for something behind museum glass 💅",
    "That bottle is limited, unlike your ability to justify another purchase 💅",
    "You have achieved full barrel-proof delusion 💅",
    "Your palate detected vanilla, caramel, and the faint aroma of maxed-out patience 💅",
    "That trade offer has been aged twelve years and still tastes unbalanced 💅",
    "You do not need another store pick, you need a supervised cart 💅",
    "The mash bill is undisclosed, much like your actual bottle budget 💅",
    "Your ISO list has its own emotional support spreadsheet 💅",
    "You drink neat because ice would dilute the drama 💅",
    "That pour has legs, unlike your argument for buying a backup backup 💅",
    "You found one bottle and immediately became regional allocation clergy 💅",
    "Your tasting notes are just dessert words wearing a blazer 💅",
    "That bottle is so overhyped it needs its own waiting room 💅",
    "You brought a laser code to a vibes fight 💅",
    "Your bunker has more unopened bottles than your calendar has social plans 💅",
    "That dusty bottle saw your offer and resealed itself 💅",
    "Your bottle photo has better lighting than your decision-making 💅",
    "The proof is high and somehow your standards are still higher 💅",
    "You chased that drop like it was going to fix the week 💅",
    "Your local store saw you coming and raised the price out of muscle memory 💅",
    "That finish is long, unlike your restraint at release season 💅",
    "You are one lottery loss away from calling it a conspiracy 💅",
    "Your favorite distillery is apparently whoever says limited the loudest 💅",
    "You turned a shelf alert into a cardio event 💅",
    "That bottle did not need a glamour shot, but neither did your ego 💅",
    "Your tasting glass has seen things your accountant should not 💅",
    "You asked for MSRP and brought secondary energy 💅",
    "That pour tastes like oak, spice, and comments section warfare 💅",
    "Your cellar is just a museum where every exhibit says maybe later 💅",
    "You bought it to open someday, which is tater for never 💅",
    "That allocation hit your cart and your common sense left the building 💅",
    "Your trade math was done on a napkin soaked in barrel proof 💅",
    "You are not hunting bottles, you are being emotionally herded by scarcity 💅",
    "The label said small batch and your brain heard retirement plan 💅",
    "Your infinity bottle is just indecision with a funnel 💅",
    "That cork sniff told me everything and none of it was good 💅",
    "Your pour is balanced, unlike the group chat after a drop 💅",
    "You said just looking, which is bourbon code for unlock the trunk 💅",
    "That bottle has a better backstory than half the people at the tasting 💅",
    "Your shelf screams sophisticated until the backup Fireball makes eye contact 💅",
    "You have entered the rare air of tater enlightenment and retail confusion 💅",
    "Your receipt has tasting notes of regret and printer ink 💅",
    "That barrel pick has more stickers than personality 💅",
    "You chased a rumor across town and called it community engagement 💅",
    "Your palate found cinnamon because every proof over 120 is now cinnamon 💅",
    "You joined one bottle group and immediately developed market opinions 💅",
    "That offer needs a kicker and a small apology 💅",
    "Your bottle survived years in a rickhouse just to sit unopened behind a Funko 💅",
    "The line started at 6 AM and so did your villain arc 💅",
    "You said honey barrel and everyone quietly checked the exits 💅",
    "Your shelf is one more limited release from requiring zoning approval 💅",
    "That pour drinks hot, much like your take on store picks 💅",
    "Your tasting note says leather because you ran out of desserts 💅",
    "The bottle is allocated, the personality is general release 💅",
    "You cannot call it a sleeper when you posted it to eight channels 💅",
    "Your bourbon journey has entered the phase where shipping boxes spark joy 💅",
    "That sample swap came with more rules than a mortgage 💅",
    "You wanted unicorns and got horse-stopper cosplay 💅",
    "Your cabinet is less home bar and more amber hostage situation 💅",
    "That bottle is finished in the tears of people who missed the drop 💅",
    "Your ISO is so specific it needs a birth certificate 💅",
    "You did not find a honey hole, you found a cashier with boundaries 💅",
    "That neck pour was innocent and you slandered it in public 💅",
    "Your store pick sticker has a sticker, seek help 💅",
    "The proof point is aggressive and frankly so is your parking strategy 💅",
    "You said bourbon community and meant competitive cart refreshing 💅",
    "That dram opened up beautifully after everyone stopped pretending to taste banana 💅",
    "Your backup bottle has a backup bottle and both are judging you 💅",
    "The secondary market saw your enthusiasm and chose violence 💅",
    "Your bottle mail day has the emotional weight of a royal birth 💅",
    "That allocation tracker is just a leaderboard for public tatering 💅",
    "You described oak like it personally offended your family 💅",
    "Your pour was complex, but your explanation was a hostage note 💅",
    "That cork taunt was unnecessary and yet deeply educational 💅",
    "You are not collecting bourbon, you are assembling a retirement home for sealed glass 💅",
    "Your release calendar has more red circles than a crime board 💅",
    "That bottle is not rare enough to justify the victory lap 💅",
    "You called it a crushable pour and then wrote six paragraphs 💅",
    "Your glassware is Glencairn, your behavior is shopping cart thunderstorm 💅",
    "That bottle was distilled with patience and purchased with none 💅",
    "You found an allocated bottle and immediately became unbearable in high definition 💅",
    "Your shelf talker said limited and your wallet entered witness protection 💅",
    "That rye spice is not a personality, but points for trying 💅",
    "You are one price check away from saying juice unironically 💅",
    "Your bunker could survive winter, boredom, and three group buys 💅",
    "That pour has notes of caramel, oak, and someone refreshing Discord too hard 💅",
    "You do not need a decanter, you need a moderator for your impulses 💅",
]


def normalize(text: str) -> str:
    return text.lower().strip().replace("'", "").replace("’", "")


def bottle_aliases(data: dict):
    aliases = []
    raw_aliases = data.get("aliases", [])

    if isinstance(raw_aliases, str):
        aliases.append(raw_aliases)
    else:
        aliases.extend(raw_aliases)

    raw_alias = data.get("alias")

    if isinstance(raw_alias, str):
        aliases.append(raw_alias)
    elif isinstance(raw_alias, list):
        aliases.extend(raw_alias)

    return [alias for alias in aliases if alias]


def find_bottle(query: str):
    q = normalize(query)

    for name in BOTTLE_NAMES:
        if q == normalize(name):
            return name, BOTTLES[name]

    for name, data in BOTTLES.items():
        for alias in bottle_aliases(data):
            if q == normalize(alias):
                return name, data

    searchable = BOTTLE_NAMES[:]
    alias_to_name = {}

    for name, data in BOTTLES.items():
        for alias in bottle_aliases(data):
            searchable.append(alias)
            alias_to_name[alias] = name

    matches = difflib.get_close_matches(query, searchable, n=1, cutoff=0.55)

    if not matches:
        return None, None

    matched = matches[0]
    canonical = alias_to_name.get(matched, matched)

    return canonical, BOTTLES[canonical]


def find_exact_bottle(query: str):
    q = normalize(query)

    for name in BOTTLE_NAMES:
        if q == normalize(name):
            return name, BOTTLES[name]

    for name, data in BOTTLES.items():
        for alias in bottle_aliases(data):
            if q == normalize(alias):
                return name, data

    return None, None


def bottle_search_text(name: str, data: dict):
    aliases = " ".join(bottle_aliases(data))
    extra = " ".join(
        str(data.get(key) or "")
        for key in ("brand", "distillery", "category", "type", "style", "expression", "batch")
    )
    return normalize(f"{name} {aliases} {extra}")


def bottle_list_entries(search: Optional[str] = None):
    entries = list(BOTTLES.items())
    entries.reverse()

    if not search:
        return entries

    terms = [normalize(term) for term in re.findall(r"[a-z0-9’']+", search) if term.strip()]

    if not terms:
        return entries

    return [
        (name, data)
        for name, data in entries
        if all(term in bottle_search_text(name, data) for term in terms)
    ]


def clip_text(value: str, limit: int):
    if len(value) <= limit:
        return value

    return f"{value[:limit - 3]}..."


def bottle_list_page(entries, page: int, page_size: int = 8):
    total_pages = max(1, (len(entries) + page_size - 1) // page_size)
    safe_page = max(1, min(page, total_pages))
    start = (safe_page - 1) * page_size
    return entries[start:start + page_size], safe_page, total_pages


def bottle_list_line(index: int, name: str, data: dict):
    aliases = bottle_aliases(data)
    alias_text = f" — aliases: {', '.join(aliases[:2])}" if aliases else ""
    proof = data.get("proof")
    proof_text = f" · {proof} proof" if proof not in {None, ""} else ""
    return clip_text(f"`{index}.` **{name}**{proof_text}{alias_text}", 115)


def bottle_list_embed(search: Optional[str], page: int):
    entries = bottle_list_entries(search)
    page_entries, safe_page, total_pages = bottle_list_page(entries, page)
    title = "🥃 Bottle List"

    if search:
        title = f"🥃 Bottle List Search: {search}"

    embed = discord.Embed(
        title=title,
        description=(
            "Sorted newest-to-oldest by database entry. "
            "Use `/bottle name:<name>` for full details."
        ),
        color=discord.Color.from_str("#C9973A")
    )

    if page_entries:
        start_index = (safe_page - 1) * 8 + 1
        lines = [
            bottle_list_line(start_index + offset, name, data)
            for offset, (name, data) in enumerate(page_entries)
        ]
        embed.add_field(name=f"Results ({len(entries)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(
            name="No bottles found",
            value="Try a shorter search term, an alias, a brand, or a category.",
            inline=False
        )

    embed.set_footer(text=f"Page {safe_page}/{total_pages} • {len(entries)} matching bottle(s)")
    return embed, safe_page, total_pages


def split_aliases(value: Optional[str]):
    if not value:
        return []

    aliases = re.split(r"\s*(?:,|;|\n)\s*", value)
    return [alias.strip() for alias in aliases if alias.strip()]


def dedupe_aliases(aliases):
    seen = set()
    deduped = []

    for alias in aliases:
        key = normalize(alias)

        if not key or key in seen:
            continue

        seen.add(key)
        deduped.append(alias)

    return deduped


def merge_aliases(existing_aliases, new_aliases):
    return dedupe_aliases([*existing_aliases, *new_aliases])


def reload_bottle_names():
    global BOTTLE_NAMES
    BOTTLE_NAMES = list(BOTTLES.keys())


def submission_embed(submission_id: str, submission: dict):
    embed = discord.Embed(
        title="🥃 Bottle Submission Review",
        description="A member suggested a bottle for NeatBot’s supplemental database.",
        color=discord.Color.from_str("#C9973A")
    )
    embed.add_field(name="Bottle", value=submission["name"], inline=False)
    embed.add_field(
        name="Aliases",
        value=", ".join(submission.get("aliases", [])) or "None",
        inline=False
    )

    if submission.get("proof") is not None:
        embed.add_field(name="Proof", value=str(submission["proof"]), inline=True)

    if submission.get("msrp") is not None:
        embed.add_field(name="MSRP", value=dollars(submission["msrp"]), inline=True)

    if submission.get("category"):
        embed.add_field(name="Category", value=submission["category"], inline=True)

    if submission.get("source_url"):
        embed.add_field(name="Source", value=submission["source_url"], inline=False)

    if submission.get("notes"):
        embed.add_field(name="Notes", value=submission["notes"], inline=False)

    submitter = submission.get("submitter_mention") or f"<@{submission.get('submitter_id')}>"
    embed.add_field(name="Submitted by", value=submitter, inline=True)
    embed.add_field(name="Status", value=submission.get("status", "pending").title(), inline=True)
    embed.set_footer(text=f"Submission ID: {submission_id}")
    return embed


def exact_submission_match(submission: dict):
    existing_name, existing_data = find_exact_bottle(submission["name"])

    if existing_name:
        return existing_name, existing_data

    for alias in submission.get("aliases", []):
        existing_name, existing_data = find_exact_bottle(alias)

        if existing_name:
            return existing_name, existing_data

    return None, None


def submission_record_from_submission(submission: dict):
    record = {
        "name": submission["name"],
        "aliases": dedupe_aliases(submission.get("aliases", [])),
    }

    for key in ("proof", "msrp", "category", "source_url", "notes"):
        if submission.get(key) is not None:
            record[key] = submission[key]

    return record


def update_bottle_submission(submission_id: str, reviewer, updates: dict):
    submission = BOTTLE_SUBMISSIONS.get(submission_id)

    if not submission or submission.get("status") != "pending":
        return None

    clean_name = (updates.get("name") or "").strip()

    if len(clean_name) < 3:
        raise ValueError("Bottle name needs at least 3 characters.")

    proof = updates.get("proof")
    msrp = updates.get("msrp")

    if proof is not None and proof <= 0:
        raise ValueError("Proof needs to be a positive number.")

    if msrp is not None and msrp < 0:
        raise ValueError("MSRP cannot be negative.")

    submission["name"] = clean_name
    submission["aliases"] = dedupe_aliases(split_aliases(updates.get("aliases")))
    submission["proof"] = proof
    submission["msrp"] = msrp
    submission["category"] = (updates.get("category") or "").strip() or None
    submission["edited_by"] = reviewer.id
    submission["edited_at"] = discord.utils.utcnow().isoformat()
    save_json(BOTTLE_SUBMISSIONS_PATH, BOTTLE_SUBMISSIONS)
    return submission


def parse_optional_float_text(value: str, field_name: str):
    cleaned = (value or "").strip().replace("$", "").replace(",", "")

    if not cleaned:
        return None

    try:
        return float(cleaned)
    except ValueError as exc:
        raise ValueError(f"{field_name} needs to be a number or blank.") from exc


def remove_aliases_from_other_community_records(community_bottles: dict, target_name: str, aliases):
    normalized_aliases = {normalize(alias) for alias in aliases if alias}

    if not normalized_aliases:
        return

    for bottle_name, data in community_bottles.items():
        if bottle_name == target_name or not isinstance(data, dict):
            continue

        current_aliases = bottle_aliases(data)
        filtered_aliases = [
            alias for alias in current_aliases
            if normalize(alias) not in normalized_aliases
        ]

        if len(filtered_aliases) != len(current_aliases):
            data["aliases"] = filtered_aliases
            if bottle_name in BOTTLES and isinstance(BOTTLES[bottle_name], dict):
                BOTTLES[bottle_name]["aliases"] = filtered_aliases


def bottle_submission_record(
    *,
    submitter,
    name: str,
    aliases: Optional[str],
    proof: Optional[float],
    msrp: Optional[float],
    category: Optional[str],
    source_url: Optional[str],
    notes: Optional[str],
):
    clean_name = name.strip()
    alias_list = dedupe_aliases([
        *split_aliases(aliases),
        *common_bottle_aliases(clean_name)
    ])

    return {
        "name": clean_name,
        "aliases": alias_list,
        "proof": proof,
        "msrp": msrp,
        "category": category.strip() if category else None,
        "source_url": clean_source_link(source_url),
        "notes": notes.strip() if notes else None,
        "submitter_id": submitter.id,
        "submitter_mention": submitter.mention,
        "submitted_at": discord.utils.utcnow().isoformat(),
        "status": "pending",
    }


def safe_external_url(value: Optional[str]):
    url = clean_source_link(value)

    if not url:
        return None

    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    hostname = parsed.hostname or ""

    if hostname in {"localhost", "127.0.0.1", "::1"} or hostname.endswith(".local"):
        return None

    try:
        ip = ipaddress.ip_address(hostname)

        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return None
    except ValueError:
        pass

    return url


def html_meta_content(html: str, key: str):
    meta_tags = re.findall(r"<meta\b[^>]*>", html, re.IGNORECASE)
    attr_pattern = re.compile(r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", re.IGNORECASE | re.DOTALL)

    for tag in meta_tags:
        attrs = {
            name.lower(): clean_html_text(value)
            for name, _quote, value in attr_pattern.findall(tag)
        }

        if attrs.get("property") == key or attrs.get("name") == key:
            return attrs.get("content")

        if key == "product:name" and attrs.get("itemprop") == "name":
            return attrs.get("content")

    return None


def clean_html_text(value: Optional[str]):
    if not value:
        return None

    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def has_html_markup_leak(value: str):
    return bool(re.search(r"</?\w+|(?:name|property|content)=['\"]", value, re.IGNORECASE))


def html_title(html: str):
    for key in ("og:title", "twitter:title"):
        value = html_meta_content(html, key)

        if value:
            return value

    match = re.search(r"<title[^>]*>(?P<value>.*?)</title>", html, re.IGNORECASE | re.DOTALL)

    if match:
        return clean_html_text(match.group("value"))

    return None


def json_ld_names(html: str):
    names = []

    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<json>.*?)</script>',
        html,
        re.IGNORECASE | re.DOTALL
    ):
        raw_json = unescape(match.group("json")).strip()

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            for key in ("name", "headline"):
                value = item.get(key)

                if isinstance(value, str) and value.strip():
                    names.append(clean_html_text(value))

            for key in ("@graph", "itemListElement"):
                if isinstance(item.get(key), list):
                    stack.extend(item[key])

    return [name for name in names if name]


def html_heading_candidates(html: str):
    candidates = []

    for tag in ("h1", "h2"):
        for match in re.finditer(rf"<{tag}\b[^>]*>(?P<value>.*?)</{tag}>", html, re.IGNORECASE | re.DOTALL):
            value = clean_html_text(match.group("value"))

            if value:
                candidates.append(value)

    return candidates


def url_slug_candidate(url: str):
    parsed = urlparse(url)
    slug = unquote(parsed.path.rstrip("/").split("/")[-1])
    slug = re.sub(r"\.[a-z0-9]{2,5}$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"[-_]+", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip()

    if not slug or len(slug) < 3:
        return None

    return title_format_bottle_name(slug)


def strip_title_noise(title: str):
    text = title.strip()
    text = re.sub(r"^\s*(review|press release|bourbon review|whiskey review|whisky review)\s*:\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*(buy|shop|order)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^\s*(?:[A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,5})\s+"
        r"(?:unveils|announces|releases|launches|introduces|debuts|reveals|reintroduces)\s+",
        "",
        text,
        flags=re.IGNORECASE
    )

    for separator in (" | ", " – ", " — ", " - "):
        if separator in text:
            parts = [part.strip() for part in text.split(separator) if part.strip()]

            if parts:
                text = parts[0]
                break

    text = re.sub(r"\s+review\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(online|for sale|price and reviews?|ratings? and reviews?)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip(" -:|")


def bottle_name_candidate_score(candidate: str):
    cleaned = strip_title_noise(candidate)

    if not cleaned or len(cleaned) < 3:
        return None

    words = re.findall(r"[A-Za-z0-9]+", cleaned)

    if len(words) > 18 or len(cleaned) > 140:
        return None

    normalized = normalize(cleaned)
    score = 0

    bottle_terms = (
        "bourbon", "rye", "whiskey", "whisky", "tequila", "scotch",
        "single barrel", "barrel proof", "small batch", "straight",
        "bottled in bond", "proof", "year", "yr"
    )
    noisy_terms = (
        "privacy policy", "terms of service", "shipping", "delivery",
        "where to buy", "best bourbon", "best whiskey", "everything you need",
        "we tasted", "our review", "guide to", "liquor store"
    )

    if has_html_markup_leak(cleaned):
        score -= 20

    score += sum(3 for term in bottle_terms if term in normalized)
    score -= sum(6 for term in noisy_terms if term in normalized)

    if re.search(r"\b\d{2,3}(?:\.\d+)?\s*proof\b", cleaned, re.IGNORECASE):
        score += 3

    if re.search(r"\b(?:19|20)\d{2}\b|\b\d{1,2}\s*(?:year|yr)\b", cleaned, re.IGNORECASE):
        score += 2

    if len(words) <= 10:
        score += 2
    elif len(words) >= 14:
        score -= 3

    if cleaned.endswith((".", "!", "?")):
        score -= 4

    return cleaned[:180], score


def infer_bottle_name_from_page(html: str, url: Optional[str] = None):
    candidates = []

    for key in ("og:title", "twitter:title", "product:name"):
        value = html_meta_content(html, key)

        if value:
            candidates.append(value)

    candidates.extend(html_heading_candidates(html))
    candidates.extend(json_ld_names(html))
    title = html_title(html)

    if title:
        candidates.append(title)

    if url:
        slug = url_slug_candidate(url)

        if slug:
            candidates.append(slug)

    scored = []

    for index, candidate in enumerate(candidates):
        scored_candidate = bottle_name_candidate_score(candidate)

        if scored_candidate:
            cleaned, score = scored_candidate
            scored.append((score, -index, cleaned))

    if scored:
        return max(scored)[2]

    return None


def infer_proof_from_page(text: str):
    match = re.search(r"\b(?P<proof>\d{2,3}(?:\.\d+)?)\s*proof\b", text, re.IGNORECASE)

    if not match:
        return None

    try:
        return float(match.group("proof"))
    except ValueError:
        return None


def infer_msrp_from_page(text: str):
    patterns = [
        r"\bMSRP\b[^$\d]{0,20}\$?(?P<value>\d{2,5}(?:\.\d{1,2})?)",
        r"suggested\s+retail\s+price[^$\d]{0,30}\$?(?P<value>\d{2,5}(?:\.\d{1,2})?)",
        r"retail\s+price[^$\d]{0,30}\$?(?P<value>\d{2,5}(?:\.\d{1,2})?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            try:
                return float(match.group("value"))
            except ValueError:
                return None

    return None


def infer_category_from_page(name: str, text: str):
    categories = [
        ("Tennessee Whiskey", (r"\btennessee whiskey\b",)),
        ("Bourbon", (r"\bbourbon\b", r"\bstraight bourbon whiskey\b")),
        ("Rye", (r"\brye whiskey\b", r"\bstraight rye\b", r"\brye\b")),
        ("Tequila", (r"\btequila\b",)),
        ("Whisky", (r"\bwhisky\b",)),
        ("Whiskey", (r"\bwhiskey\b",)),
    ]
    normalized_name = normalize(name)

    for category, patterns in categories:
        if any(re.search(pattern, normalized_name) for pattern in patterns):
            return category

    normalized_text = normalize(text[:2500])
    scored_categories = []

    for index, (category, patterns) in enumerate(categories):
        score = sum(len(re.findall(pattern, normalized_text)) for pattern in patterns)

        if score:
            scored_categories.append((score, -index, category))

    if scored_categories:
        return max(scored_categories)[2]

    return None


def acronym_alias(name: str):
    words = re.findall(r"[A-Za-z0-9]+", name)
    ignore = {
        "the", "a", "an", "and", "of", "in", "for", "bourbon", "whiskey",
        "whisky", "rye", "tequila", "batch", "release", "edition", "straight",
        "single", "barrel", "small", "proof", "bottled", "bond", "s"
    }
    letters = [word[0].upper() for word in words if word.lower() not in ignore and not word.isdigit()]
    alias = "".join(letters)
    return alias if 2 <= len(alias) <= 5 else None


def proof_alias_value(value: str):
    return value.rstrip("0").rstrip(".") if "." in value else value


def bottle_alias_base(words: list[str]):
    if len(words) >= 3 and len(words[0]) == 1 and len(words[1]) == 1:
        return "".join(word[0].upper() for word in words[:3])

    return words[0] if words else None


def clipped_alias(value: Optional[str], max_length: int = 80):
    if not value:
        return None

    alias = re.sub(r"\s+", " ", value).strip(" -:;,.\"'")

    if len(alias) < 2 or len(alias) > max_length:
        return None

    if has_html_markup_leak(alias):
        return None

    return alias


def common_bottle_aliases(name: str):
    aliases = []
    acronym = acronym_alias(name)

    if acronym:
        aliases.append(acronym)

    no_punctuation = re.sub(r"[’']", "", name)

    if no_punctuation != name:
        aliases.append(no_punctuation)

    words = re.findall(r"[A-Za-z0-9]+", name)

    if not words:
        return dedupe_aliases(aliases)

    alias_base = bottle_alias_base(words)
    name_without_product_terms = re.sub(
        r"\b(?:kentucky|straight|single barrel|small batch|barrel proof|cask strength|"
        r"bottled in bond|bottled-in-bond|bourbon|whiskey|whisky|rye|tequila|edition|release)\b",
        " ",
        name,
        flags=re.IGNORECASE
    )
    name_without_product_terms = re.sub(r"\s+", " ", name_without_product_terms).strip()

    type_suffixes = []
    normalized_name = normalize(name)

    if "rye" in normalized_name:
        type_suffixes.append("Rye")
    if "bourbon" in normalized_name:
        type_suffixes.append("Bourbon")
    if "tequila" in normalized_name:
        type_suffixes.append("Tequila")

    for candidate in (name_without_product_terms, *[f"{name_without_product_terms} {suffix}" for suffix in type_suffixes]):
        alias = clipped_alias(candidate)

        if alias and normalize(alias) != normalize(name):
            aliases.append(alias)

    year_match = re.search(r"\b(?P<age>\d{1,2})\s*(?:year|yr|year-old)\b", name, re.IGNORECASE)

    if year_match:
        age = year_match.group("age")
        aliases.extend([f"{alias_base} {age}", f"{alias_base} {age}yr", f"{alias_base} {age} year"])

    proof_match = re.search(r"\b(?P<proof>\d{2,3}(?:\.\d+)?)\s*proof\b", name, re.IGNORECASE)

    if proof_match:
        proof = proof_alias_value(proof_match.group("proof"))
        aliases.append(f"{alias_base} {proof}")

    if re.search(r"\bbottled[-\s]in[-\s]bond\b", name, re.IGNORECASE):
        aliases.extend([f"{alias_base} BIB", f"{alias_base} Bottled in Bond"])

    expression_aliases = [
        (r"\bsingle\s+barrel\b", "SiB"),
        (r"\bsmall\s+batch\b", "SmB"),
        (r"\bbarrel\s+proof\b", "BP"),
        (r"\bcask\s+strength\b", "CS"),
        (r"\bfull\s+proof\b", "FP"),
        (r"\bbottled[-\s]in[-\s]bond\b", "BIB"),
    ]

    for pattern, shorthand in expression_aliases:
        if re.search(pattern, name, re.IGNORECASE):
            aliases.append(f"{alias_base} {shorthand}")

    ordinal_match = re.search(r"\b(?P<number>\d{2,4})(?:st|nd|rd|th)?\b", name, re.IGNORECASE)

    if ordinal_match:
        number = ordinal_match.group("number")
        aliases.append(f"{alias_base} {number}")

        if not re.fullmatch(r"(?:19|20)\d{2}", number):
            aliases.append(f"{alias_base} {number}th")

    batch_positions = [index for index, word in enumerate(words) if word.lower() == "batch"]

    if batch_positions:
        batch_index = batch_positions[-1]
        batch_words = []

        for word in reversed(words[:batch_index]):
            if re.fullmatch(r"\d{2,4}(?:-\d{1,2})?", word):
                continue

            if word.lower() in {"bourbon", "whiskey", "whisky", "rye", "batch", "s"}:
                continue

            batch_words.insert(0, word)

            if len(batch_words) >= 3:
                break

        if batch_words:
            batch_name = " ".join(batch_words)
            aliases.extend([batch_name, f"{batch_name} Batch"])

            if not normalize(batch_name).startswith(normalize(alias_base)):
                aliases.append(f"{alias_base} {batch_name}")

    return dedupe_aliases(aliases)


def review_text_aliases(name: str, text: str):
    aliases = []
    alias_base = bottle_alias_base(re.findall(r"[A-Za-z0-9]+", name))
    normalized_name = normalize(name)

    quoted_patterns = [
        r"(?:known as|called|nicknamed|aka|a\.k\.a\.)\s+[\"“”'‘’](?P<alias>[^\"“”'‘’]{2,80})[\"“”'‘’]",
        r"[\"“](?P<alias>[^\"“”]{2,80})[\"”]\s+(?:batch|release|edition|bottle)",
    ]

    for pattern in quoted_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            alias = clipped_alias(match.group("alias"))

            if alias and normalize(alias) not in normalized_name:
                aliases.append(alias)

    if alias_base:
        age_match = re.search(r"\b(?P<age>\d{1,2})[-\s]year[-\s]old\b", text, re.IGNORECASE)

        if age_match:
            age = age_match.group("age")
            aliases.extend([f"{alias_base} {age}", f"{alias_base} {age}yr", f"{alias_base} {age} Year"])

        proof_match = re.search(r"\b(?P<proof>\d{2,3}(?:\.\d+)?)\s*proof\b", text, re.IGNORECASE)

        if proof_match:
            proof = proof_alias_value(proof_match.group("proof"))
            aliases.append(f"{alias_base} {proof}")

        if re.search(r"\bbottled[-\s]in[-\s]bond\b", text, re.IGNORECASE):
            aliases.extend([f"{alias_base} BIB", f"{alias_base} Bottled in Bond"])

        if re.search(r"\blimited[-\s]edition\b", text, re.IGNORECASE):
            aliases.append(f"{alias_base} Limited Edition")

    return dedupe_aliases(aliases)


def url_submission_aliases(name: str, text: str = ""):
    return dedupe_aliases([
        *common_bottle_aliases(name),
        *review_text_aliases(name, text)
    ])


async def fetch_submission_page(url: str):
    timeout = aiohttp.ClientTimeout(total=8)
    headers = {
        "User-Agent": "NeatBot/1.0 bottle-submission-review"
    }

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise ValueError(f"Page returned HTTP {response.status}")

            content_type = response.headers.get("content-type", "")

            if "text/html" not in content_type and "application/xhtml" not in content_type:
                raise ValueError("That URL does not look like an HTML page")

            return await response.text(errors="ignore")


def page_text_for_inference(html: str):
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    return clean_html_text(text) or ""


async def bottle_submission_from_url(interaction: discord.Interaction, url: str, notes: Optional[str]):
    safe_url = safe_external_url(url)

    if not safe_url:
        raise ValueError("Give me a normal public http/https URL.")

    html = await fetch_submission_page(safe_url)
    name = infer_bottle_name_from_page(html, safe_url)

    if not name:
        raise ValueError("I could not find a bottle name on that page.")

    text = page_text_for_inference(html)
    proof = infer_proof_from_page(text)
    msrp = infer_msrp_from_page(text)
    category = infer_category_from_page(name, text)
    auto_notes = "Auto-filled from URL. Mods should verify before approving."

    if notes:
        auto_notes = f"{auto_notes}\nUser notes: {notes.strip()}"

    return bottle_submission_record(
        submitter=interaction.user,
        name=name,
        aliases=", ".join(url_submission_aliases(name, text)),
        proof=proof,
        msrp=msrp,
        category=category,
        source_url=safe_url,
        notes=auto_notes,
    )


def approve_bottle_submission(submission_id: str, reviewer, *, force_separate: bool = False):
    submission = BOTTLE_SUBMISSIONS.get(submission_id)

    if not submission or submission.get("status") != "pending":
        return None, "missing"

    name = submission["name"]
    aliases = submission.get("aliases", [])
    existing_name, existing_data = (None, None) if force_separate else exact_submission_match(submission)

    community_bottles = load_json(COMMUNITY_BOTTLES_PATH, {})

    if existing_name and existing_data:
        record = dict(existing_data)
        record["name"] = existing_name
        record["aliases"] = merge_aliases(bottle_aliases(existing_data), [name, *aliases])
        community_bottles[existing_name] = record
        BOTTLES[existing_name] = record
        approved_name = existing_name
        result = "updated"
    else:
        record = submission_record_from_submission(submission)
        remove_aliases_from_other_community_records(community_bottles, name, [name, *aliases])
        community_bottles[name] = record
        BOTTLES[name] = record
        approved_name = name
        result = "created separately" if force_separate else "created"

    reload_bottle_names()
    save_json(COMMUNITY_BOTTLES_PATH, community_bottles)

    submission["status"] = "approved"
    submission["reviewed_by"] = reviewer.id
    submission["reviewed_at"] = discord.utils.utcnow().isoformat()
    submission["approved_name"] = approved_name
    submission["approval_result"] = result
    save_json(BOTTLE_SUBMISSIONS_PATH, BOTTLE_SUBMISSIONS)

    return approved_name, result


def reject_bottle_submission(submission_id: str, reviewer):
    submission = BOTTLE_SUBMISSIONS.get(submission_id)

    if not submission or submission.get("status") != "pending":
        return None

    submission["status"] = "rejected"
    submission["reviewed_by"] = reviewer.id
    submission["reviewed_at"] = discord.utils.utcnow().isoformat()
    save_json(BOTTLE_SUBMISSIONS_PATH, BOTTLE_SUBMISSIONS)
    return submission


def can_use_bottle_review_channel(channel):
    if not isinstance(channel, discord.TextChannel):
        return False

    guild = channel.guild
    bot_member = guild.me or (guild.get_member(bot.user.id) if bot.user else None)

    if not bot_member:
        return False

    bot_permissions = channel.permissions_for(bot_member)

    if not bot_permissions.view_channel or not bot_permissions.send_messages or not bot_permissions.embed_links:
        return False

    default_permissions = channel.permissions_for(guild.default_role)
    return not default_permissions.view_channel


async def bottle_review_channel(interaction: discord.Interaction):
    if BOTTLE_REVIEW_CHANNEL_ID and DISCORD_ID_PATTERN.fullmatch(BOTTLE_REVIEW_CHANNEL_ID):
        channel_id = int(BOTTLE_REVIEW_CHANNEL_ID)

        try:
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)

            if can_use_bottle_review_channel(channel):
                return channel
        except discord.HTTPException:
            pass

    guild = interaction.guild

    if guild:
        review_names = {normalize(name).replace(" ", "-") for name in BOTTLE_REVIEW_CHANNEL_NAMES}

        for channel in guild.text_channels:
            channel_names = {normalize(channel.name), normalize(channel.name).replace(" ", "-")}

            if review_names & channel_names and can_use_bottle_review_channel(channel):
                return channel

    return None


async def post_bottle_submission_for_review(interaction: discord.Interaction, submission_id: str, submission: dict):
    review_channel = await bottle_review_channel(interaction)

    if not review_channel:
        return None, (
            "I saved the submission, but I couldn’t find a private mod-review channel. "
            "Set `BOTTLE_REVIEW_CHANNEL_ID`, or create a private channel named `bottle-review`."
        )

    existing_name, _ = exact_submission_match(submission)
    content = "🥃 Bottle submission needs mod review."

    if existing_name:
        content += (
            f"\nExact existing match: **{existing_name}**. "
            "Approve will merge aliases; Add Separately will create a new bottle."
        )
    else:
        content += "\nNo exact match found. Approve will create a new bottle."

    try:
        review_message = await review_channel.send(
            content=content,
            embed=submission_embed(submission_id, submission),
            view=BottleSubmissionReviewView(submission_id),
            allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException:
        return None, "I saved the submission, but I could not post it to the review channel. Check my channel permissions."

    return review_message, None


async def submit_bottle_suggestion(interaction: discord.Interaction, submission: dict):
    submission_id = uuid.uuid4().hex
    BOTTLE_SUBMISSIONS[submission_id] = submission
    save_json(BOTTLE_SUBMISSIONS_PATH, BOTTLE_SUBMISSIONS)
    review_message, error = await post_bottle_submission_for_review(interaction, submission_id, submission)

    if error:
        return None, error

    return review_message, None


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
        return "🟠 Only if you really want it", "That is collector/secondary-ish pricing."
    return "🔴 Pass", "That price is deep into emotional damage territory."


def dollars(value):
    if value is None:
        return "Unknown"

    return f"${value}"


def flip_taco_value(value: int):
    return f"🌮 {value:,}"


def has_value_mismatch(ft_value: Optional[int], iso_value: Optional[int]):
    return ft_value is not None and iso_value is not None and iso_value * 100 > ft_value * 115


def seller_kicker_amount(ft_value: Optional[int], iso_value: Optional[int]):
    if ft_value is None or iso_value is None or iso_value <= ft_value:
        return None

    return iso_value - ft_value


def buyer_kicker_amount(ft_value: Optional[int], iso_value: Optional[int]):
    if ft_value is None or iso_value is None or ft_value <= iso_value:
        return None

    return ft_value - iso_value


def kicker_label(amount: Optional[int]):
    if amount is None:
        return "🥾"

    return f"🥾 {flip_taco_value(amount)}"


def kicker_field_value(amount: Optional[int]):
    if amount is None:
        return "Yes"

    return f"Yes — {flip_taco_value(amount)}"


def seller_kicker_label(ft_value: Optional[int], iso_value: Optional[int]):
    return kicker_label(seller_kicker_amount(ft_value, iso_value))


def buyer_kicker_label(ft_value: Optional[int], iso_value: Optional[int]):
    return kicker_label(buyer_kicker_amount(ft_value, iso_value))


def seller_kicker_field_value(ft_value: Optional[int], iso_value: Optional[int]):
    return kicker_field_value(seller_kicker_amount(ft_value, iso_value))


def buyer_kicker_field_value(ft_value: Optional[int], iso_value: Optional[int]):
    return kicker_field_value(buyer_kicker_amount(ft_value, iso_value))


def flip_kicker_flags(ft_value: Optional[int], iso_value: Optional[int], seller_requested: Optional[bool], buyer_requested: Optional[bool]):
    if seller_kicker_amount(ft_value, iso_value) is not None:
        return True, False

    if buyer_kicker_amount(ft_value, iso_value) is not None:
        return False, True

    return bool(seller_requested), bool(buyer_requested)


def yes_no(value: Optional[bool]):
    return "Yes" if value else "No"


def sanitize_iso_text(value: Optional[str]):
    if not value:
        return None

    if re.search(r"\bcash\b|\btacos?\s+only\b|^tacos?$", value.strip(), flags=re.IGNORECASE):
        return "🌮 Tacos"

    return value


def strip_kicker_text(value: Optional[str], kicker: Optional[bool]):
    if not value:
        return None, bool(kicker)

    has_kicker = bool(kicker) or bool(re.search(r"🥾|\bboot\b|\bkicker\b", value, flags=re.IGNORECASE))
    text = re.sub(r"🥾|\bboot\b|\bkicker\b", "", value, flags=re.IGNORECASE)
    items = split_bottle_list(text)
    text = " + ".join(items)

    return text or None, has_kicker


def parse_iso_details(iso: Optional[str], iso_value: Optional[int], iso_kicker: Optional[bool]):
    if not iso:
        return None, iso_value, bool(iso_kicker)

    has_kicker = bool(iso_kicker) or bool(re.search(r"🥾|\bboot\b|\bkicker\b", iso, flags=re.IGNORECASE))
    text = sanitize_iso_text(iso)

    if text == "🌮 Tacos":
        return None, iso_value, has_kicker

    text, has_kicker = strip_kicker_text(text, has_kicker)

    value_match = re.search(r"\b\d{2,6}\b", text or "")

    if value_match and iso_value is None:
        iso_value = int(value_match.group(0))
        text = text[:value_match.start()] + text[value_match.end():]

    items = split_bottle_list(text or "")
    text = " + ".join(items)

    if not text:
        return None, iso_value, has_kicker

    return text, iso_value, has_kicker


def iso_thread_target(iso: Optional[str], iso_value: Optional[int], buyer_kicker: Optional[str] = None):
    parts = []

    if iso:
        parts.append(iso)
    elif iso_value is None:
        parts.append("🌮 Tacos")

    if iso_value is not None:
        parts.append(flip_taco_value(iso_value))

    if buyer_kicker:
        parts.append(buyer_kicker)

    return " + ".join(parts)


def parse_flip_form_details(value: Optional[str]):
    details = value or ""
    zip_match = ZIP_CODE_PATTERN.search(details)
    normalized = normalize(details)

    def flag_for(label: str):
        match = re.search(rf"\b{label}\b\s*[:=\-]?\s*(yes|y|true|no|n|false)", normalized)

        if match:
            return match.group(1) in {"yes", "y", "true"}

        return bool(re.search(rf"\b{label}\b", normalized))

    return {
        "zip_code": zip_match.group(0) if zip_match else None,
        "rtr": flag_for("rtr"),
        "x_posted": flag_for("xposted") or flag_for("xpost"),
        "ft_kicker": bool(re.search(r"\b(buyer|their|them)\s+kicker\b|\bbuyer\s+adds\b", normalized)),
        "iso_kicker": bool(re.search(r"\b(seller|my|me)\s+kicker\b|\bseller\s+adds\b", normalized)),
    }


def split_bottle_list(value: str):
    items = re.split(r"\s*(?:\+|,|\n)\s*", value)
    return [item.strip() for item in items if item.strip()]


def title_format_bottle_name(value: str):
    words = []

    for word in value.strip().split():
        if any(character.isdigit() for character in word):
            words.append(word.upper())
        elif word.isupper() and len(word) <= 5:
            words.append(word)
        else:
            words.append(word.capitalize())

    return " ".join(words)


def canonical_bottle_name(value: str):
    bottle_name, _ = find_exact_bottle(value)

    if bottle_name:
        return bottle_name

    return title_format_bottle_name(value)


def canonical_bottle_list(value: str):
    items = split_bottle_list(value)

    if not items:
        return value.strip()

    return " + ".join(canonical_bottle_name(item) for item in items)


ALLOCATION_EXTRA_ALIASES = {
    "RR15": "Russell’s Reserve 15 Year Bourbon (2024)",
    "GTS": "George T. Stagg 2024",
    "WLW": "William Larue Weller 2025",
    "ER17": "Eagle Rare 17-Year Bourbon 2025",
    "THH": "Thomas H. Handy Sazerac Rye 2025",
    "HANDY": "Thomas H. Handy Sazerac Rye 2025",
    "SAZ18": "Sazerac 18-Year Rye 2025",
    "EHT BP": "EH Taylor Barrel Proof",
    "EH TAYLOR BP": "EH Taylor Barrel Proof",
    "EHT": "E.H. Taylor Bottled-in-Bond 2025",
    "EH TAYLOR": "E.H. Taylor Bottled-in-Bond 2025",
    "E.H. TAYLOR": "E.H. Taylor Bottled-in-Bond 2025",
    "EHT SINGLE BARREL": "E.H. Taylor Single Barrel",
    "EH TAYLOR SINGLE BARREL": "E.H. Taylor Single Barrel",
    "E.H. TAYLOR SINGLE BARREL": "E.H. Taylor Single Barrel",
    "ELMER LEE": "Elmer T. Lee",
    "JD12": "Jack Daniel’s 12-Year-Old Tennessee Whiskey Batch 4",
    "JD14": "Jack Daniel’s 14-Year-Old Tennessee Whiskey Batch 2",
    "KOK": "King of Kentucky Small Batch Bourbon",
    "A107": "Weller Antique 107",
    "OWA": "Weller Antique 107",
    "W12": "Weller 12 Year",
    "CYPB": "Weller CYPB",
    "FP": "Weller Full Proof",
    "WFP": "Weller Full Proof",
}
ALLOCATION_POSITIVE_PATTERNS = [
    r"\bgot\b",
    r"\bgrabbed\b",
    r"\bsecured\b",
    r"\bfound\b",
    r"\bscored\b",
    r"\bpicked\s+up\b",
    r"\bacquired\b",
    r"\blanded\b",
]
ALLOCATION_NEGATIVE_PATTERNS = [
    r"\bmissed\b",
    r"\blooking\s+for\b",
    r"\banyone\s+(seen|see|spot|spotted)\b",
    r"\biso\b",
    r"\btrade\b",
    r"\btrading\b",
    r"\bselling\b",
    r"\bfor\s+sale\b",
    r"\bfs\b",
    r"\bft\b",
    r"\bwish\s+i\s+(got|had|found)\b",
    r"\bwhere\b",
]


def compact_alias_text(value: str):
    return re.sub(r"[^a-z0-9]", "", normalize(value))


def allocation_compact_tokens(value: str):
    return [compact_alias_text(token) for token in re.findall(r"[a-z0-9]+", normalize(value))]


def allocation_short_alias_match(value: str, compact_alias: str):
    tokens = [token for token in allocation_compact_tokens(value) if token]

    if compact_alias in tokens:
        return True

    return any(
        compact_alias == f"{left}{right}"
        for left, right in zip(tokens, tokens[1:])
    )


def allocation_alias_matches(value: str, alias: str):
    compact_alias = compact_alias_text(alias)

    if len(compact_alias) < 2:
        return False

    if len(compact_alias) <= 3:
        return allocation_short_alias_match(value, compact_alias)

    return compact_alias in compact_alias_text(value)


def allocation_alias_entries():
    entries = []

    for alias, bottle_name in ALLOCATION_EXTRA_ALIASES.items():
        entries.append((alias, bottle_name))

    for bottle_name, data in BOTTLES.items():
        entries.append((bottle_name, bottle_name))

        for alias in bottle_aliases(data):
            entries.append((alias, bottle_name))

    unique = {}

    for alias, bottle_name in entries:
        if alias:
            unique[compact_alias_text(alias)] = (alias, bottle_name)

    return sorted(unique.values(), key=lambda item: len(compact_alias_text(item[0])), reverse=True)


def allocation_batch_context(content: str):
    match = ALLOCATION_BATCH_PATTERN.search(content)

    if not match:
        return None

    prefix = content[:match.start()].strip(" -:|")
    batch = match.group("batch").strip(" .,-")

    if not prefix or not batch:
        return None

    return prefix, batch


def allocation_store_pick_source(content: str):
    match = re.search(
        r"\b(?:at|from)\s+(?P<source>[^.!?\n]+)",
        content,
        re.IGNORECASE
    )

    if not match:
        return None

    source = match.group("source").strip(" -:;,")
    source = re.sub(r"\b(today|yesterday|tonight|this morning|this afternoon|this evening)\b.*$", "", source, flags=re.IGNORECASE)
    source = re.sub(r"\s+", " ", source).strip(" -:;,")

    if not source:
        return None

    return source[:80]


def batch_label_matches(bottle_name: str, batch: str):
    normalized_name = normalize(bottle_name)
    normalized_batch = normalize(batch)
    return (
        re.search(rf"\bbatch\s*{re.escape(normalized_batch)}\b", normalized_name) is not None
        or re.search(rf"\b{re.escape(normalized_batch)}\b", normalized_name) is not None
    )


def allocation_bottle_display_name(bottle_name: str, batch: Optional[str] = None):
    if not batch or batch_label_matches(bottle_name, batch):
        return bottle_name

    return f"{bottle_name} Batch {batch}"


def detect_allocation_bottle(content: str):
    store_pick = has_store_pick_marker(content)
    lookup_content = strip_store_pick_marker(content) if store_pick else content
    store_pick_source = allocation_store_pick_source(content) if store_pick else None
    batch_context = allocation_batch_context(lookup_content)

    if batch_context:
        prefix, batch = batch_context

        # When someone writes "JD12 batch 4", the real bottle signal is before
        # "batch"; use that alias first, then preserve the batch value.
        for alias, bottle_name in allocation_alias_entries():
            if allocation_alias_matches(prefix, alias):
                canonical_name, _ = find_exact_bottle(bottle_name)
                display_name = allocation_bottle_display_name(canonical_name or bottle_name, batch)
                if store_pick:
                    display_name = format_store_pick_name(display_name, store_pick_source)
                return display_name, f"{alias} Batch {batch}"

    for alias, bottle_name in allocation_alias_entries():
        if allocation_alias_matches(lookup_content, alias):
            canonical_name, _ = find_exact_bottle(bottle_name)
            display_name = canonical_name or bottle_name
            if store_pick:
                display_name = format_store_pick_name(display_name, store_pick_source)
            return display_name, alias

    return None, None


def analyze_allocation_message(content: str):
    if not content or content.strip().startswith(("/", "!")):
        return None

    bottle_name, matched_alias = detect_allocation_bottle(content)

    if not bottle_name:
        return None

    normalized = normalize(content)
    positive = sum(1 for pattern in ALLOCATION_POSITIVE_PATTERNS if re.search(pattern, normalized))
    negative = sum(1 for pattern in ALLOCATION_NEGATIVE_PATTERNS if re.search(pattern, normalized))
    score = positive * 2 - negative * 3
    short_alias_match = len(compact_alias_text(matched_alias)) <= 3

    if short_alias_match and positive == 0:
        return None

    if "?" in content:
        score -= 2

    if re.search(r"\bat\b|\bfrom\b", normalized):
        score += 2

    if re.search(r"\btoday\b|\bin\b", normalized):
        score += 1

    # In the dedicated tracker channel, a clean bare bottle mention like "jd12 batch 4"
    # should still prompt, but obvious questions/trades should not.
    if positive == 0 and negative == 0 and "?" not in content:
        score = max(score, 2)

    if score < 2:
        return None

    return {
        "bottle_name": bottle_name,
        "matched_alias": matched_alias,
        "score": score,
    }


def allocation_year(dt=None):
    return (dt or discord.utils.utcnow()).year


async def init_allocation_db():
    ALLOCATION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        # History safety: deploys/restarts must never erase allocation data.
        # These migrations only create missing tables and preserve existing rows.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                bottle_name TEXT NOT NULL,
                original_message TEXT NOT NULL,
                message_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                year INTEGER NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS allocation_tracker_state (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                leaderboard_message_id TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id, year)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_allocations (
                pending_id TEXT PRIMARY KEY,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                bottle_name TEXT NOT NULL,
                original_message TEXT NOT NULL,
                message_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_allocations_guild_year ON allocations (guild_id, year)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_allocations_guild_year_user ON allocations (guild_id, year, user_id)"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_allocations_guild_year_bottle ON allocations (guild_id, year, bottle_name)"
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_allocations_recent_duplicate
            ON allocations (guild_id, user_id, bottle_name, created_at)
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_allocations_expires_at ON pending_allocations (expires_at)"
        )
        await db.execute(
            "DELETE FROM pending_allocations WHERE expires_at <= ?",
            (discord.utils.utcnow().isoformat(),),
        )
        await db.commit()


async def create_pending_allocation(message: discord.Message, bottle_name: str):
    await cleanup_expired_pending_allocations()

    pending_id = str(uuid.uuid4())
    created_at = discord.utils.utcnow()
    expires_at = created_at + timedelta(minutes=15)

    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO pending_allocations (
                pending_id, guild_id, channel_id, user_id, username,
                bottle_name, original_message, message_id, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pending_id,
                str(message.guild.id),
                str(message.channel.id),
                str(message.author.id),
                message.author.display_name,
                bottle_name,
                message.content,
                str(message.id),
                created_at.isoformat(),
                expires_at.isoformat(),
            ),
        )
        await db.commit()

    return pending_id


async def get_pending_allocation(pending_id: str):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pending_allocations WHERE pending_id = ?",
            (pending_id,),
        ) as cursor:
            pending = await cursor.fetchone()

        if not pending:
            return None

        if datetime.fromisoformat(pending["expires_at"]) <= discord.utils.utcnow():
            await db.execute("DELETE FROM pending_allocations WHERE pending_id = ?", (pending_id,))
            await db.commit()
            return None

        return pending


async def delete_pending_allocation(pending_id: str):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        await db.execute("DELETE FROM pending_allocations WHERE pending_id = ?", (pending_id,))
        await db.commit()


async def cleanup_expired_pending_allocations():
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        await db.execute(
            "DELETE FROM pending_allocations WHERE expires_at <= ?",
            (discord.utils.utcnow().isoformat(),),
        )
        await db.commit()


async def has_recent_allocation_duplicate(pending):
    cutoff = discord.utils.utcnow() - timedelta(hours=ALLOCATION_DUPLICATE_HOURS)

    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        async with db.execute(
            """
            SELECT id FROM allocations
            WHERE guild_id = ? AND user_id = ? AND bottle_name = ? AND created_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (pending["guild_id"], pending["user_id"], pending["bottle_name"], cutoff.isoformat()),
        ) as cursor:
            return await cursor.fetchone() is not None


async def save_confirmed_allocation(pending):
    created_at = discord.utils.utcnow()

    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO allocations (
                guild_id, channel_id, user_id, username, bottle_name,
                original_message, message_id, created_at, year
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pending["guild_id"],
                pending["channel_id"],
                pending["user_id"],
                pending["username"],
                pending["bottle_name"],
                pending["original_message"],
                pending["message_id"],
                created_at.isoformat(),
                allocation_year(created_at),
            ),
        )
        await db.commit()


async def claim_and_save_allocation(pending_id: str, user_id: int):
    now = discord.utils.utcnow()
    cutoff = now - timedelta(hours=ALLOCATION_DUPLICATE_HOURS)

    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")

        try:
            async with db.execute(
                "SELECT * FROM pending_allocations WHERE pending_id = ?",
                (pending_id,),
            ) as cursor:
                pending = await cursor.fetchone()

            if not pending:
                await db.commit()
                return "missing", None

            pending_data = dict(pending)

            if datetime.fromisoformat(pending_data["expires_at"]) <= now:
                await db.execute("DELETE FROM pending_allocations WHERE pending_id = ?", (pending_id,))
                await db.commit()
                return "expired", pending_data

            if str(user_id) != pending_data["user_id"]:
                await db.commit()
                return "not_owner", pending_data

            async with db.execute(
                """
                SELECT id FROM allocations
                WHERE guild_id = ? AND user_id = ? AND bottle_name = ? AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    pending_data["guild_id"],
                    pending_data["user_id"],
                    pending_data["bottle_name"],
                    cutoff.isoformat(),
                ),
            ) as cursor:
                duplicate = await cursor.fetchone()

            if duplicate:
                await db.execute("DELETE FROM pending_allocations WHERE pending_id = ?", (pending_id,))
                await db.commit()
                return "duplicate", pending_data

            await db.execute(
                """
                INSERT INTO allocations (
                    guild_id, channel_id, user_id, username, bottle_name,
                    original_message, message_id, created_at, year
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pending_data["guild_id"],
                    pending_data["channel_id"],
                    pending_data["user_id"],
                    pending_data["username"],
                    pending_data["bottle_name"],
                    pending_data["original_message"],
                    pending_data["message_id"],
                    now.isoformat(),
                    allocation_year(now),
                ),
            )
            await db.execute("DELETE FROM pending_allocations WHERE pending_id = ?", (pending_id,))
            await db.commit()
            return "saved", pending_data
        except Exception:
            await db.rollback()
            raise


async def allocation_leaderboard_data(guild_id: int, year: int):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) AS total FROM allocations WHERE guild_id = ? AND year = ?",
            (str(guild_id), year),
        ) as cursor:
            total = (await cursor.fetchone())["total"]

        async with db.execute(
            """
            SELECT username, COUNT(*) AS total
            FROM allocations
            WHERE guild_id = ? AND year = ?
            GROUP BY user_id, username
            ORDER BY total DESC, username COLLATE NOCASE ASC
            LIMIT 5
            """,
            (str(guild_id), year),
        ) as cursor:
            hunters = await cursor.fetchall()

        async with db.execute(
            """
            SELECT username, bottle_name
            FROM allocations
            WHERE guild_id = ? AND year = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 5
            """,
            (str(guild_id), year),
        ) as cursor:
            latest = await cursor.fetchall()

        async with db.execute(
            """
            SELECT bottle_name, COUNT(*) AS total
            FROM allocations
            WHERE guild_id = ? AND year = ?
            GROUP BY bottle_name
            ORDER BY total DESC, bottle_name COLLATE NOCASE ASC
            LIMIT 5
            """,
            (str(guild_id), year),
        ) as cursor:
            bottles = await cursor.fetchall()

    return total, hunters, latest, bottles


def allocation_rows(rows, *, latest=False):
    if not rows:
        return "None yet"

    if latest:
        return "\n".join(f"• {row['username']} — {row['bottle_name']}" for row in rows)

    rank_titles = {
        1: "🥇 Juice Supreme",
        2: "🥈 Juice Lite",
        3: "🥉 Slightly Juiced",
    }
    lines = []

    for index, row in enumerate(rows, start=1):
        if index in rank_titles:
            lines.append(f"{rank_titles[index]}: {row['username']} — {row['total']}")
        else:
            lines.append(f"{index}. {row['username']} — {row['total']}")

    return "\n".join(lines)


def allocation_bottle_rows(rows):
    if not rows:
        return "None yet"

    return "\n".join(f"{index}. {row['bottle_name']} — {row['total']}" for index, row in enumerate(rows, start=1))


async def allocation_leaderboard_embed(guild_id: int, year: int):
    total, hunters, latest, bottles = await allocation_leaderboard_data(guild_id, year)
    embed = discord.Embed(
        title=f"🥃 {year} Allocation Tracker",
        description=f"**Server Total:** {total} bottle{'s' if total != 1 else ''}",
        color=discord.Color.from_str("#C9973A"),
    )
    embed.add_field(name="Top Hunters", value=allocation_rows(hunters), inline=False)
    embed.add_field(name="Latest Allocations", value=allocation_rows(latest, latest=True), inline=False)
    embed.add_field(name="Top Bottles", value=allocation_bottle_rows(bottles), inline=False)
    embed.set_footer(text="Historical allocation data is preserved by year.")
    return embed


async def tracker_message_id(guild_id: int, channel_id: int, year: int):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        async with db.execute(
            """
            SELECT leaderboard_message_id FROM allocation_tracker_state
            WHERE guild_id = ? AND channel_id = ? AND year = ?
            """,
            (str(guild_id), str(channel_id), year),
        ) as cursor:
            row = await cursor.fetchone()

    return row[0] if row else None


async def save_tracker_message_id(guild_id: int, channel_id: int, year: int, message_id: int):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO allocation_tracker_state (guild_id, channel_id, year, leaderboard_message_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, year) DO UPDATE SET
                leaderboard_message_id = excluded.leaderboard_message_id,
                updated_at = excluded.updated_at
            """,
            (str(guild_id), str(channel_id), year, str(message_id), discord.utils.utcnow().isoformat()),
        )
        await db.commit()


async def update_allocation_leaderboard(channel: discord.TextChannel, year: Optional[int] = None):
    if not channel.guild:
        return

    year = year or allocation_year()
    embed = await allocation_leaderboard_embed(channel.guild.id, year)
    message_id = await tracker_message_id(channel.guild.id, channel.id, year)

    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
            await message.edit(embed=embed)
            return
        except discord.HTTPException:
            pass

    message = await channel.send(embed=embed)
    await save_tracker_message_id(channel.guild.id, channel.id, year, message.id)


async def allocation_user_stats(guild_id: int, user_id: int, year: int):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COUNT(*) AS total FROM allocations WHERE guild_id = ? AND user_id = ? AND year = ?",
            (str(guild_id), str(user_id), year),
        ) as cursor:
            total = (await cursor.fetchone())["total"]

        async with db.execute(
            """
            SELECT bottle_name, COUNT(*) AS total
            FROM allocations
            WHERE guild_id = ? AND user_id = ? AND year = ?
            GROUP BY bottle_name
            ORDER BY total DESC, bottle_name COLLATE NOCASE ASC
            LIMIT 1
            """,
            (str(guild_id), str(user_id), year),
        ) as cursor:
            favorite = await cursor.fetchone()

        async with db.execute(
            """
            SELECT bottle_name FROM allocations
            WHERE guild_id = ? AND user_id = ? AND year = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 5
            """,
            (str(guild_id), str(user_id), year),
        ) as cursor:
            recent = await cursor.fetchall()

        async with db.execute(
            """
            SELECT user_id, COUNT(*) AS total
            FROM allocations
            WHERE guild_id = ? AND year = ?
            GROUP BY user_id
            ORDER BY total DESC, user_id ASC
            """,
            (str(guild_id), year),
        ) as cursor:
            rankings = await cursor.fetchall()

    rank = next((index for index, row in enumerate(rankings, start=1) if row["user_id"] == str(user_id)), None)
    return total, favorite, recent, rank


async def allocation_rank_context(guild_id: int, user_id: int, year: int):
    async with aiosqlite.connect(ALLOCATION_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT user_id, username, COUNT(*) AS total
            FROM allocations
            WHERE guild_id = ? AND year = ?
            GROUP BY user_id, username
            ORDER BY total DESC, username COLLATE NOCASE ASC
            """,
            (str(guild_id), year),
        ) as cursor:
            rankings = await cursor.fetchall()

    leader = rankings[0] if rankings else None
    user_row = next((row for row in rankings if row["user_id"] == str(user_id)), None)
    rank = next((index for index, row in enumerate(rankings, start=1) if row["user_id"] == str(user_id)), None)

    return rank, user_row, leader


def allocation_sass(rank: Optional[int], user_row, leader):
    if not rank or not user_row:
        return random.choice([
            "The leaderboard briefly nosed an unlabeled sample and forgot how counting works. Deeply on-brand.",
            "Your rank is currently hiding behind the glass case with the allocated stuff. Suspicious.",
            "The tracker tried to calculate your rank, got distracted by a dusty, and wandered into the barrel warehouse."
        ])

    if rank == 1:
        return random.choice([
            (
                f"👑 Still **#1** with **{user_row['total']}** logged finds. "
                "The tater monarchy remains intact. Please wave regally from atop your throne of cardboard shippers."
            ),
            (
                f"🥔 ALERT: **#1** tater detected. **{user_row['total']}** finds logged. "
                "The line formed yesterday and somehow you were still first."
            ),
            (
                f"🏆 You remain **#1** with **{user_row['total']}** finds. "
                "The bourbon overlord has spoken, and the peasants may return to refreshing inventory pages."
            ),
            (
                f"🦅 **#1** again. **{user_row['total']}** bottles logged. "
                "At this point, Buffalo Trace checks under its bed for you."
            ),
            (
                f"🥃 You are still **#1** with **{user_row['total']}** finds. "
                "Your palate may be questionable, but your hunting disorder is clearly elite."
            )
        ])

    leader_name = leader["username"] if leader else "the leader"
    leader_total = leader["total"] if leader else "more"
    gap = leader["total"] - user_row["total"] if leader else None
    gap_text = f" You are **{gap}** behind." if gap else ""

    return random.choice([
        (
            f"📍 You are **#{rank}** with **{user_row['total']}** finds.{gap_text} "
            f"Meanwhile **{leader_name}** sits at **{leader_total}**, polishing a bunker bottle and judging your cardio."
        ),
        (
            f"🥔 Current tater ranking: **#{rank}**. Finds: **{user_row['total']}**.{gap_text} "
            f"To catch **{leader_name}**, you may need to start camping in the parking lot like it is a limited sneaker drop."
        ),
        (
            f"🔎 You are **#{rank}** with **{user_row['total']}** logged finds.{gap_text} "
            f"**{leader_name}** is still ahead at **{leader_total}**, because apparently sleep is optional and store aisles are a lifestyle."
        ),
        (
            f"📦 Rank **#{rank}**, total **{user_row['total']}**.{gap_text} "
            f"**{leader_name}** remains the final boss at **{leader_total}**. Bring snacks, low expectations, and comfortable shoes."
        ),
        (
            f"🧾 You are **#{rank}** with **{user_row['total']}** finds.{gap_text} "
            f"The leader, **{leader_name}**, has **{leader_total}**. NeatBot recommends less dignity and more shelf lurking."
        ),
        (
            f"🚨 Allocation acquired. Ego mildly inflated. Ranking: **#{rank}** with **{user_row['total']}**.{gap_text} "
            f"Still chasing **{leader_name}** at **{leader_total}**, the current warehouse whisperer."
        )
    ])


def parse_plain_int(value: str):
    match = re.search(r"\d[\d,]*", value)

    if not match:
        return None

    return int(match.group(0).replace(",", ""))


def parse_plain_ints(value: str):
    return [int(match.replace(",", "")) for match in re.findall(r"\d[\d,]*", value)]


def parse_yes_no(value: str):
    normalized = normalize(value)

    if normalized in {"yes", "y", "true", "t", "1", "sure", "yeah", "yep"}:
        return True

    if normalized in {"no", "n", "false", "f", "0", "nope"}:
        return False

    return None


def is_skip(value: str):
    return normalize(value) in {"skip", "none", "no", "n/a", "na", "blank", "leave blank"}


def starts_flip_helper(value: str):
    normalized = normalize(value).replace(":", " ")
    compacted = " ".join(normalized.split())

    return compacted in {
        "flip",
        "flip help",
        "/flip help",
        "help flip",
        "trade help",
        "ft help",
        "dm neatbot flip help",
        "dm neatbot /flip help",
        "neatbot flip help",
        "neatbot /flip help"
    } or "flip help" in compacted


def is_tacos_only(value: str):
    return bool(re.search(r"\btacos?\b|\bcash\b|\bmoney\b|\bpayment\b|\bdollars?\b|\bfunds\b", value, flags=re.IGNORECASE))


def format_flip_helper_bottles(value: str):
    text, _ = strip_kicker_text(value, False)

    if not text:
        return ""

    return canonical_bottle_list(text)


def format_bottle_list(value: str):
    items = split_bottle_list(value)

    if len(items) <= 1:
        return value.strip()

    return "\n".join(f"• {item}" for item in items)


def missing_flip_permissions(channel: discord.abc.GuildChannel, member: discord.Member):
    permissions = channel.permissions_for(member)
    checks = {
        "View Channel": permissions.view_channel,
        "Send Messages": permissions.send_messages,
        "Create Public Threads": permissions.create_public_threads,
        "Send Messages in Threads": permissions.send_messages_in_threads,
        "Embed Links": permissions.embed_links,
        "Add Reactions": permissions.add_reactions,
        "Manage Threads": permissions.manage_threads,
    }

    return [name for name, allowed in checks.items() if not allowed]


def thread_safe_name(name: str, limit: int = 100):
    return name[:limit]


def close_thread_title(title: str):
    cleaned = title

    if cleaned.startswith("🥃 "):
        cleaned = cleaned[len("🥃 "):]

    if cleaned.startswith("🔒 CLOSED — "):
        return thread_safe_name(cleaned)

    return thread_safe_name(f"🔒 CLOSED — {cleaned}")


def extract_embed_field(embed: discord.Embed, field_name: str):
    for field in embed.fields:
        if field.name == field_name:
            return field.value

    return None


def extract_user_id_from_mention(value: Optional[str]):
    if not value:
        return None

    match = USER_MENTION_PATTERN.search(value)

    if not match:
        return None

    return int(match.group("user_id"))


def flip_is_closed(embed: discord.Embed):
    return bool(
        extract_embed_field(embed, "🤝 Binned by:")
        or extract_embed_field(embed, "🔒 Closed by:")
    )


def flip_offer_kind(iso: Optional[str]):
    return "FT" if iso else "FS"


def flip_embed(
    *,
    ft: str,
    ft_value: Optional[int],
    iso: Optional[str],
    iso_value: Optional[int],
    ft_kicker: Optional[bool],
    iso_kicker: Optional[bool],
    rtr: Optional[bool],
    x_posted: Optional[bool],
    location: str,
    seller,
    posted_at,
    photo_url: Optional[str] = None,
    binner=None,
    binned_at=None
):
    offer_kind = flip_offer_kind(iso)
    iso_kicker, ft_kicker = flip_kicker_flags(ft_value, iso_value, iso_kicker, ft_kicker)
    embed = discord.Embed(
        title=f"🥃 {ft}",
        color=discord.Color.from_str("#C9973A")
    )
    embed.add_field(name=f"📦 {offer_kind}:", value=format_bottle_list(ft), inline=False)

    trade_only = bool(iso and ft_value is None and iso_value is None)

    if ft_value is not None:
        embed.add_field(name="💰 Est. Value (per seller):", value=flip_taco_value(ft_value), inline=True)

    if trade_only:
        embed.add_field(name="♻️ Trade Type:", value="Bottle-for-bottle trade only", inline=True)

    if iso_kicker:
        embed.add_field(name="🥾 Seller Kicker:", value=seller_kicker_field_value(ft_value, iso_value), inline=True)

    if ft_kicker:
        embed.add_field(name="🥾 Buyer Kicker:", value=buyer_kicker_field_value(ft_value, iso_value), inline=True)

    if iso:
        iso_text = format_bottle_list(iso)
        embed.add_field(name="🔍 ISO:", value=iso_text, inline=False)

        if iso_value is not None:
            embed.add_field(name="💵 ISO Value:", value=flip_taco_value(iso_value), inline=False)
    else:
        embed.add_field(name="🌮 Looking For:", value="Tacos only", inline=False)

        if iso_value is not None:
            embed.add_field(name="💵 ISO Value:", value=flip_taco_value(iso_value), inline=False)

    embed.add_field(name="📍 Location:", value=location, inline=True)

    rtr_value = "Yes *(Right to Refuse)*" if rtr else "No"
    embed.add_field(name="🚫 RTR:", value=rtr_value, inline=True)

    if x_posted:
        embed.add_field(name="📣 X-posted:", value="Yes", inline=True)

    embed.add_field(name="👤 Seller:", value=seller.mention, inline=True)
    embed.add_field(name="📅 Posted:", value=discord.utils.format_dt(posted_at, "f"), inline=False)

    if binner and binned_at:
        embed.add_field(
            name="🤝 Binned by:",
            value=f"{binner.mention} at {discord.utils.format_dt(binned_at, 'f')}",
            inline=False
        )

    if photo_url:
        embed.set_image(url=photo_url)

    embed.set_footer(
        text=(
            "React with ✅ to show interest • Hit BIN to close the deal • "
            "I am just a bot, hopefully a good bot and not a bad bot. "
            "Please check this post for accuracy. The poster is fully responsible for the post, "
            "not the bot or Discord server."
        )
    )

    return embed


async def resolve_zip_location(zip_code: str):
    if not ZIP_CODE_PATTERN.fullmatch(zip_code):
        return None

    url = f"https://ziptastic.com/v3/us/{zip_code}"

    try:
        timeout = aiohttp.ClientTimeout(total=4)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return zip_code

                data = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return zip_code

    city = data.get("city")
    state = data.get("state_short") or data.get("state")

    if not city or not state:
        return zip_code

    return f"{city.title()}, {state.upper()}"


def flip_helper_intro():
    return (
        "🥃 I can help format a `/flip` post. Reply `cancel` anytime.\n\n"
        "What bottle or bottles are you offering? Separate bundled bottles with `+` or commas."
    )


def flip_helper_command(ft: str, ft_value: int, data: dict):
    iso = data.get("iso")
    iso_value = data.get("iso_value")
    ft_kicker = bool(data.get("buyer_kicker") or (iso_value is not None and ft_value > iso_value))
    iso_kicker = bool(data.get("seller_kicker") or (iso_value is not None and iso_value > ft_value))
    rtr = data.get("rtr", False)
    x_posted = data.get("x_posted", False)

    parts = [
        f"/flip ft:{ft}",
        f"ft_value:{ft_value}",
        f"zip_code:{data['zip_code']}",
    ]

    if iso:
        parts.append(f"iso:{iso}")

    if iso_value is not None:
        parts.append(f"iso_value:{iso_value}")

    parts.extend([
        f"ft_kicker:{ft_kicker}",
        f"iso_kicker:{iso_kicker}",
        f"rtr:{rtr}",
        f"x_posted:{x_posted}",
    ])

    return " ".join(parts)


def flip_helper_preview(ft: str, ft_value: int, data: dict):
    iso = data.get("iso")
    iso_value = data.get("iso_value")
    seller_amount = seller_kicker_amount(ft_value, iso_value)
    buyer_amount = buyer_kicker_amount(ft_value, iso_value)
    kicker_text = ""

    if data.get("seller_kicker") or seller_amount is not None:
        if seller_amount is not None:
            kicker_text = f" plus a seller-side kicker of {seller_amount} tacos"
        else:
            kicker_text = " plus a seller-side kicker"

    target = iso or "tacos only"

    if data.get("buyer_kicker") or buyer_amount is not None:
        if buyer_amount is not None:
            target = f"{target} plus a buyer-side kicker of {buyer_amount} tacos"
        else:
            target = f"{target} plus a buyer-side kicker"

    return f"Preview: Offering {ft}{kicker_text} for {target}."


def finish_flip_helper(data: dict):
    if data.get("separate_posts"):
        return [
            (flip_helper_command(ft, ft_value, data), flip_helper_preview(ft, ft_value, data))
            for ft, ft_value in zip(data["ft_items"], data["ft_values"])
        ]

    command = flip_helper_command(data["ft"], data["ft_value"], data)
    preview = flip_helper_preview(data["ft"], data["ft_value"], data)
    return [(command, preview)]


async def send_finished_flip_helper(channel, data: dict):
    results = finish_flip_helper(data)

    if len(results) > 1:
        await channel.send("Here are your separate `/flip` posts. Each command is its own message for easier mobile copying.")
    else:
        await channel.send("Here is your copy/paste `/flip` command. The next message is only the command.")

    for index, (command, preview) in enumerate(results, start=1):
        if len(results) > 1:
            await channel.send(f"Command {index}:")

        await channel.send(command)
        await channel.send(preview)


async def handle_flip_helper_message(message: discord.Message):
    user_id = message.author.id
    content = message.content.strip()

    if normalize(content) == "cancel":
        FLIP_HELP_SESSIONS.pop(user_id, None)
        await message.channel.send("Cancelled. DM me `flip help` when you want to build another post.")
        return

    session = FLIP_HELP_SESSIONS.get(user_id)

    if not session:
        if starts_flip_helper(content):
            FLIP_HELP_SESSIONS[user_id] = {"step": "ft", "data": {}}
            await message.channel.send(flip_helper_intro())
        else:
            await message.channel.send("DM me `flip help` and I’ll walk you through a copy/paste `/flip` post.")

        return

    step = session["step"]
    data = session["data"]

    if step == "ft":
        ft_text, ft_kicker = strip_kicker_text(content, False)
        ft_items = [canonical_bottle_name(item) for item in split_bottle_list(ft_text or "")]

        if not ft_items:
            await message.channel.send("I need at least one bottle name. What bottle or bottles are you offering?")
            return

        data["ft_items"] = ft_items
        data["seller_kicker"] = ft_kicker

        if len(ft_items) > 1:
            session["step"] = "bundle"
            await message.channel.send("Are these bottles a bundle in one post, or separate posts? Reply `bundle` or `separate`.")
        else:
            data["ft"] = ft_items[0]
            session["step"] = "ft_value"
            await message.channel.send(f"What is the estimated FT value for **{data['ft']}**? Use a plain number.")

        return

    if step == "bundle":
        normalized = normalize(content)

        if normalized.startswith("separate"):
            data["separate_posts"] = True
            session["step"] = "separate_values"
            await message.channel.send(
                "Got it. Enter the estimated FT values in the same order, separated by commas.\n"
                f"Order: {', '.join(data['ft_items'])}"
            )
            return

        if normalized.startswith("bundle"):
            data["separate_posts"] = False
            data["ft"] = " + ".join(data["ft_items"])
            session["step"] = "ft_value"
            await message.channel.send("What is the total estimated FT value for the bundle? Use a plain number.")
            return

        await message.channel.send("Reply `bundle` if they move together, or `separate` if each bottle needs its own post.")
        return

    if step == "separate_values":
        values = parse_plain_ints(content)

        if len(values) != len(data["ft_items"]):
            await message.channel.send(f"I need {len(data['ft_items'])} values, one for each bottle, separated by commas.")
            return

        data["ft_values"] = values
        session["step"] = "iso"
        await message.channel.send("What are you looking for? Reply with bottle(s), or say `tacos only`.")
        return

    if step == "ft_value":
        value = parse_plain_int(content)

        if value is None:
            await message.channel.send("Please send the FT value as a plain number.")
            return

        data["ft_value"] = value
        session["step"] = "iso"
        await message.channel.send("What are you looking for? Reply with bottle(s), or say `tacos only`.")
        return

    if step == "iso":
        if is_tacos_only(content):
            data["iso"] = None
            session["step"] = "iso_value"
            await message.channel.send("How many tacos are you looking for? Reply with a number, or `skip`.")
            return

        iso_text, iso_kicker = strip_kicker_text(content, False)
        data["iso"] = format_flip_helper_bottles(iso_text or content)
        data["seller_kicker"] = iso_kicker

        if not VINTAGE_YEAR_PATTERN.search(data["iso"]) and "any year" not in normalize(data["iso"]):
            session["step"] = "vintage"
            await message.channel.send("Does a specific vintage/release year matter? Reply with a year, `any year`, or `skip`.")
        else:
            session["step"] = "iso_value"
            await message.channel.send("What is the estimated ISO value? Reply with a number, or `skip` if unknown.")

        return

    if step == "vintage":
        if normalize(content) == "any year":
            data["iso"] = f"{data['iso']} any year"
        elif not is_skip(content):
            year_match = VINTAGE_YEAR_PATTERN.search(content)

            if year_match:
                data["iso"] = f"{data['iso']} {year_match.group(0)}"

        session["step"] = "iso_value"
        await message.channel.send("What is the estimated ISO value? Reply with a number, or `skip` if unknown.")
        return

    if step == "iso_value":
        data["iso_value"] = None if is_skip(content) else parse_plain_int(content)

        if not is_skip(content) and data["iso_value"] is None:
            await message.channel.send("Please send the ISO value as a plain number, or `skip`.")
            return

        session["step"] = "kicker"
        await message.channel.send("Any kicker/extras beyond the value gap? Reply `seller`, `buyer`, or `no`.")
        return

    if step == "kicker":
        normalized = normalize(content)
        answer = parse_yes_no(content)

        if "seller" in normalized or "my" in normalized:
            data["seller_kicker"] = True
        elif "buyer" in normalized or "their" in normalized or "them" in normalized:
            data["buyer_kicker"] = True
        elif answer is True:
            iso_value = data.get("iso_value")
            ft_value = data.get("ft_value") or (data.get("ft_values") or [None])[0]

            if iso_value is not None and ft_value is not None and ft_value > iso_value:
                data["buyer_kicker"] = True
            else:
                data["seller_kicker"] = True
        elif answer is None:
            await message.channel.send("Reply `seller`, `buyer`, or `no`.")
            return

        session["step"] = "zip"
        await message.channel.send("What is your 5-digit ZIP?")
        return

    if step == "zip":
        if not ZIP_CODE_PATTERN.fullmatch(content):
            await message.channel.send("Please send a 5-digit ZIP.")
            return

        data["zip_code"] = content
        session["step"] = "rtr"
        await message.channel.send("Enable RTR / Right to Refuse? Reply yes or no.")
        return

    if step == "rtr":
        answer = parse_yes_no(content)

        if answer is None:
            await message.channel.send("Reply yes or no.")
            return

        data["rtr"] = answer
        session["step"] = "x_posted"
        await message.channel.send("Is this x-posted anywhere else? Reply yes or no.")
        return

    if step == "x_posted":
        answer = parse_yes_no(content)

        if answer is None:
            await message.channel.send("Reply yes or no.")
            return

        data["x_posted"] = answer
        FLIP_HELP_SESSIONS.pop(user_id, None)
        await send_finished_flip_helper(message.channel, data)
        return


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


def encode_vote_ledger(votes: dict):
    if not votes:
        return "No votes yet"

    return "\n".join(f"{user_id}:{vote}" for user_id, vote in sorted(votes.items()))


def decode_vote_ledger(value: Optional[str]):
    if not value or value == "No votes yet":
        return {}

    votes = {}

    for line in value.splitlines():
        if ":" not in line:
            continue

        user_id, vote = line.split(":", 1)
        user_id = user_id.strip()
        vote = vote.strip()

        if user_id.isdigit() and vote.isdigit():
            votes[user_id] = int(vote)

    return votes


def embed_field_value(embed: discord.Embed, field_name: str):
    for field in embed.fields:
        if field.name == field_name:
            return field.value

    return None


def attach_vote_message_context(state: dict, message: discord.Message):
    if isinstance(message.channel, discord.Thread):
        state.setdefault("thread_id", message.channel.id)
        state.setdefault("thread_message_id", message.id)
    else:
        state.setdefault("channel_id", message.channel.id)
        state.setdefault("message_id", message.id)

        thread = getattr(message, "thread", None)

        if thread:
            state.setdefault("thread_id", thread.id)


def boty_embed(vote_id: str):
    state = BOTY_VOTES[vote_id]
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
    embed.add_field(name="Vote Ledger", value=encode_vote_ledger(votes), inline=False)
    embed.set_footer(text="BOTY = Bottle of the Year. Discuss this bottle in the thread.")

    return embed


def battle_embed(vote_id: str):
    state = BATTLE_VOTES[vote_id]
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
    embed.add_field(name="Vote Ledger", value=encode_vote_ledger(votes), inline=False)
    embed.set_footer(text="Winner gets the trophy. Loser gets humbled.")

    return embed


def recover_boty_state(message: discord.Message):
    for embed in message.embeds:
        title = embed.title or ""
        prefix = "🏆 BOTY Score: "

        if title.startswith(prefix):
            bottle_name = title[len(prefix):].strip()

            if bottle_name and bottle_name != "Unknown bottle":
                state = {
                    "bottle": bottle_name,
                    "votes": decode_vote_ledger(embed_field_value(embed, "Vote Ledger"))
                }
                attach_vote_message_context(state, message)
                return state

    thread = getattr(message, "thread", None)

    if thread and thread.name.startswith("BOTY: "):
        bottle_name = thread.name[len("BOTY: "):].strip()

        if bottle_name:
            state = {
                "bottle": bottle_name,
                "thread_id": thread.id,
                "votes": {}
            }
            attach_vote_message_context(state, message)
            return state

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
                "votes": decode_vote_ledger(embed_field_value(embed, "Vote Ledger"))
            }

            thread = getattr(message, "thread", None)

            if thread:
                state["thread_id"] = thread.id

            attach_vote_message_context(state, message)
            return state

    return None


async def fetch_vote_message(channel_id: Optional[int], message_id: Optional[int]):
    if not channel_id or not message_id:
        return None

    try:
        channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
        return await channel.fetch_message(int(message_id))
    except (discord.HTTPException, discord.NotFound, discord.Forbidden, AttributeError, ValueError):
        return None


async def sync_vote_messages(state: dict, source_message: discord.Message, embed: discord.Embed, view: discord.ui.View):
    edited = {(source_message.channel.id, source_message.id)}
    await source_message.edit(embed=embed, view=view)

    targets = [
        (state.get("channel_id"), state.get("message_id")),
        (state.get("thread_id"), state.get("thread_message_id")),
    ]

    for channel_id, message_id in targets:
        if not channel_id or not message_id or (int(channel_id), int(message_id)) in edited:
            continue

        message = await fetch_vote_message(channel_id, message_id)

        if message:
            try:
                await message.edit(embed=embed, view=view)
                edited.add((int(channel_id), int(message_id)))
            except discord.HTTPException:
                pass


class BOTYView(discord.ui.View):
    def __init__(self, vote_id: str):
        super().__init__(timeout=None)

        for score in range(1, 11):
            self.add_item(BOTYScoreButton(vote_id, score))


class BOTYScoreButton(discord.ui.DynamicItem[discord.ui.Button], template=r"boty_score:(?P<vote_id>[0-9]+):(?P<score>[0-9]+)"):
    def __init__(self, vote_id: str, score: int):
        super().__init__(
            discord.ui.Button(
                label=str(score),
                style=discord.ButtonStyle.secondary,
                custom_id=f"boty_score:{vote_id}:{score}",
                row=0 if score <= 5 else 1
            )
        )
        self.vote_id = vote_id
        self.score = score

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("vote_id"), int(match.group("score")))

    async def callback(self, interaction: discord.Interaction):
        vote_id = self.vote_id

        if vote_id not in BOTY_VOTES:
            recovered_state = recover_boty_state(interaction.message)

            if not recovered_state:
                await interaction.response.send_message(
                    "I lost the saved state for this BOTY post. Please start a new `/boty` post for this bottle.",
                    ephemeral=True
                )
                return

            BOTY_VOTES[vote_id] = recovered_state

        attach_vote_message_context(BOTY_VOTES[vote_id], interaction.message)
        BOTY_VOTES[vote_id].setdefault("votes", {})[str(interaction.user.id)] = self.score
        save_json(BOTY_VOTES_PATH, BOTY_VOTES)

        await interaction.response.send_message(
            f"Your BOTY score is locked in: {self.score}/10.",
            ephemeral=True
        )
        await sync_vote_messages(
            BOTY_VOTES[vote_id],
            interaction.message,
            boty_embed(vote_id),
            BOTYView(vote_id)
        )


class BattleView(discord.ui.View):
    def __init__(self, vote_id: str):
        super().__init__(timeout=None)
        self.add_item(BattleVoteButton(vote_id, 1))
        self.add_item(BattleVoteButton(vote_id, 2))


class BattleVoteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"battle_vote:(?P<vote_id>[0-9]+):(?P<pick>[12])"):
    def __init__(self, vote_id: str, pick: int):
        super().__init__(
            discord.ui.Button(
                label=f"Vote Bottle {pick}",
                style=discord.ButtonStyle.primary if pick == 1 else discord.ButtonStyle.danger,
                custom_id=f"battle_vote:{vote_id}:{pick}"
            )
        )
        self.vote_id = vote_id
        self.pick = pick

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("vote_id"), int(match.group("pick")))

    async def callback(self, interaction: discord.Interaction):
        vote_id = self.vote_id

        if vote_id not in BATTLE_VOTES:
            recovered_state = recover_battle_state(interaction.message)

            if not recovered_state:
                await interaction.response.send_message(
                    "I can’t find this battle in the vote database anymore. Please start a new `/battle` post.",
                    ephemeral=True
                )
                return

            BATTLE_VOTES[vote_id] = recovered_state

        attach_vote_message_context(BATTLE_VOTES[vote_id], interaction.message)
        BATTLE_VOTES[vote_id].setdefault("votes", {})[str(interaction.user.id)] = self.pick
        save_json(BATTLE_VOTES_PATH, BATTLE_VOTES)

        chosen = BATTLE_VOTES[vote_id]["bottle_one"] if self.pick == 1 else BATTLE_VOTES[vote_id]["bottle_two"]
        await interaction.response.send_message(f"Vote counted for {chosen}.", ephemeral=True)
        await sync_vote_messages(
            BATTLE_VOTES[vote_id],
            interaction.message,
            battle_embed(vote_id),
            BattleView(vote_id)
        )


class FlipBinButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bin_(?P<message_id>[0-9]+)"):
    def __init__(self, original_message_id: int, *, disabled: bool = False):
        super().__init__(
            discord.ui.Button(
                label="BIN 🤝",
                style=discord.ButtonStyle.success,
                custom_id=f"bin_{original_message_id}",
                disabled=disabled
            )
        )
        self.original_message_id = original_message_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match.group("message_id")))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.message or not interaction.message.embeds:
            await interaction.response.send_message(
                "I can’t read this flip anymore. Please make a new `/flip` post.",
                ephemeral=True
            )
            return

        embed = interaction.message.embeds[0]

        if flip_is_closed(embed):
            await interaction.response.send_message(
                "This flip is already closed.",
                ephemeral=True
            )
            return

        seller_id = extract_user_id_from_mention(extract_embed_field(embed, "👤 Seller:"))

        if not seller_id:
            await interaction.response.send_message(
                "I can’t find the original seller on this flip. Please make a new `/flip` post.",
                ephemeral=True
            )
            return

        if interaction.user.id == seller_id:
            await interaction.response.send_message(
                "You can't bin your own flip, boss. 😄",
                ephemeral=True
            )
            return

        bottle_ft = (embed.title or "🥃 this bottle").replace("🥃 ", "", 1)
        await interaction.response.send_message(
            f"Are you sure you want to BIN **{bottle_ft}**?",
            view=ConfirmBinView(self.original_message_id, interaction.message, interaction.user.id),
            ephemeral=True
        )


async def perform_bin(interaction: discord.Interaction, original_message_id: int, flip_message: discord.Message):
    if not flip_message or not flip_message.embeds:
        await interaction.response.edit_message(
            content="I can’t read this flip anymore. Please make a new `/flip` post.",
            view=None
        )
        return

    embed = flip_message.embeds[0]

    if flip_is_closed(embed):
        await interaction.response.edit_message(
            content="This flip is already closed.",
            view=None
        )
        return

    seller_id = extract_user_id_from_mention(extract_embed_field(embed, "👤 Seller:"))

    if not seller_id:
        await interaction.response.edit_message(
            content="I can’t find the original seller on this flip. Please make a new `/flip` post.",
            view=None
        )
        return

    if interaction.user.id == seller_id:
        await interaction.response.edit_message(
            content="You can't bin your own flip, boss. 😄",
            view=None
        )
        return

    bottle_ft = (embed.title or "🥃 this bottle").replace("🥃 ", "", 1)
    binned_at = discord.utils.utcnow()
    updated_embed = discord.Embed.from_dict(embed.to_dict())
    updated_embed.add_field(
        name="🤝 Binned by:",
        value=f"{interaction.user.mention} at {discord.utils.format_dt(binned_at, 'f')}",
        inline=False
    )

    await flip_message.edit(
        embed=updated_embed,
        view=FlipBinView(original_message_id, disabled=True)
    )

    await interaction.response.edit_message(content="Confirmed. This offer is now binned.", view=None)

    author = interaction.guild.get_member(seller_id) if interaction.guild else None

    if author is None:
        try:
            author = await bot.fetch_user(seller_id)
        except discord.HTTPException:
            author = None

    dm_sent = False

    if author:
        try:
            await author.send(
                f"Hey {author.mention}! 🥃 {interaction.user.mention} binned your flip for "
                f"**{bottle_ft}**. Reach out to get the deal done!"
            )
            dm_sent = True
        except discord.HTTPException:
            dm_sent = False

    thread = flip_message.channel

    if isinstance(thread, discord.Thread):
        await thread.send(f"🔒 Deal closed! {interaction.user.mention} binned this one. Thread is now locked.")

        if author and not dm_sent:
            await thread.send(f"{author.mention} has DMs closed — reach out to {interaction.user.mention} directly!")

        try:
            await thread.edit(name=close_thread_title(thread.name), locked=True)
        except discord.HTTPException:
            await thread.send("I could not lock this thread automatically. A mod may need to lock it.")


class ConfirmBinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Yes, BIN it 🤝", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, ConfirmBinView):
            await interaction.response.send_message("I lost the BIN confirmation context. Please click BIN again.", ephemeral=True)
            return

        if interaction.user.id != view.binner_id:
            await interaction.response.send_message("Only the person who clicked BIN can confirm this.", ephemeral=True)
            return

        await perform_bin(interaction, view.original_message_id, view.flip_message)


class CancelBinButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if isinstance(view, ConfirmBinView) and interaction.user.id != view.binner_id:
            await interaction.response.send_message("Only the person who clicked BIN can cancel this confirmation.", ephemeral=True)
            return

        await interaction.response.edit_message(content="BIN cancelled.", view=None)


class ConfirmBinView(discord.ui.View):
    def __init__(self, original_message_id: int, flip_message: discord.Message, binner_id: int):
        super().__init__(timeout=60)
        self.original_message_id = original_message_id
        self.flip_message = flip_message
        self.binner_id = binner_id
        self.add_item(ConfirmBinButton())
        self.add_item(CancelBinButton())


class FlipCloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"closeflip_(?P<message_id>[0-9]+)"):
    def __init__(self, original_message_id: int, *, disabled: bool = False):
        super().__init__(
            discord.ui.Button(
                label="Close Offer 🔒",
                style=discord.ButtonStyle.secondary,
                custom_id=f"closeflip_{original_message_id}",
                disabled=disabled
            )
        )
        self.original_message_id = original_message_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match.group("message_id")))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.message or not interaction.message.embeds:
            await interaction.response.send_message(
                "I can’t read this flip anymore. Please make a new `/flip` post.",
                ephemeral=True
            )
            return

        embed = interaction.message.embeds[0]

        if flip_is_closed(embed):
            await interaction.response.send_message(
                "This flip is already closed.",
                ephemeral=True
            )
            return

        seller_id = extract_user_id_from_mention(extract_embed_field(embed, "👤 Seller:"))

        if not seller_id:
            await interaction.response.send_message(
                "I can’t find the original seller on this flip. Please ask a mod to close it manually.",
                ephemeral=True
            )
            return

        permissions = interaction.channel.permissions_for(interaction.user) if interaction.channel else None
        can_manage_threads = bool(permissions and permissions.manage_threads)

        if interaction.user.id != seller_id and not can_manage_threads:
            await interaction.response.send_message(
                "Only the original poster or a mod with Manage Threads can close this offer.",
                ephemeral=True
            )
            return

        closed_at = discord.utils.utcnow()
        updated_embed = discord.Embed.from_dict(embed.to_dict())
        updated_embed.add_field(
            name="🔒 Closed by:",
            value=f"{interaction.user.mention} at {discord.utils.format_dt(closed_at, 'f')}",
            inline=False
        )

        await interaction.response.edit_message(
            embed=updated_embed,
            view=FlipBinView(self.original_message_id, disabled=True)
        )

        thread = interaction.channel

        if isinstance(thread, discord.Thread):
            await thread.send(f"🔒 Offer closed by {interaction.user.mention}. Thread is now locked.")

            try:
                await thread.edit(name=close_thread_title(thread.name), locked=True)
            except discord.HTTPException:
                await thread.send("I could not lock this thread automatically. A mod may need to lock it.")


class FlipBinView(discord.ui.View):
    def __init__(self, original_message_id: int, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.add_item(FlipBinButton(original_message_id, disabled=disabled))
        self.add_item(FlipCloseButton(original_message_id, disabled=disabled))


class AllocationConfirmButton(discord.ui.DynamicItem[discord.ui.Button], template=r"alloc_confirm:(?P<pending_id>[a-f0-9-]+)"):
    def __init__(self, pending_id: str):
        super().__init__(
            discord.ui.Button(
                label="Confirm",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"alloc_confirm:{pending_id}"
            )
        )
        self.pending_id = pending_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("pending_id"))

    async def callback(self, interaction: discord.Interaction):
        status, pending = await claim_and_save_allocation(self.pending_id, interaction.user.id)

        if status in {"missing", "expired"}:
            await interaction.response.send_message("That allocation confirmation expired. Post it again if needed.", ephemeral=True)
            return

        if status == "not_owner":
            await interaction.response.send_message("Only the original poster can confirm this allocation.", ephemeral=True)
            return

        if status == "duplicate":
            await interaction.response.edit_message(
                content="Duplicate protection kicked in. This bottle was already logged for you recently.",
                embed=None,
                view=None,
            )
            return

        year = allocation_year()
        rank, user_row, leader = await allocation_rank_context(interaction.guild.id, interaction.user.id, year)
        sass = allocation_sass(rank, user_row, leader)
        await interaction.response.edit_message(
            content=f"Logged **{pending['bottle_name']}** for {interaction.user.mention}.\n\n{sass}",
            embed=None,
            view=AllocationLoggedView(year),
        )

        if isinstance(interaction.channel, discord.TextChannel):
            await update_allocation_leaderboard(interaction.channel, year)


class AllocationCancelButton(discord.ui.DynamicItem[discord.ui.Button], template=r"alloc_cancel:(?P<pending_id>[a-f0-9-]+)"):
    def __init__(self, pending_id: str):
        super().__init__(
            discord.ui.Button(
                label="Cancel",
                emoji="❌",
                style=discord.ButtonStyle.secondary,
                custom_id=f"alloc_cancel:{pending_id}"
            )
        )
        self.pending_id = pending_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("pending_id"))

    async def callback(self, interaction: discord.Interaction):
        pending = await get_pending_allocation(self.pending_id)

        if pending and str(interaction.user.id) != pending["user_id"]:
            await interaction.response.send_message("Only the original poster can cancel this allocation.", ephemeral=True)
            return

        await delete_pending_allocation(self.pending_id)
        await interaction.response.edit_message(content="Allocation log canceled.", embed=None, view=None)


class AllocationConfirmView(discord.ui.View):
    def __init__(self, pending_id: str):
        super().__init__(timeout=None)
        self.add_item(AllocationConfirmButton(pending_id))
        self.add_item(AllocationCancelButton(pending_id))


class AllocationLeaderboardButton(discord.ui.DynamicItem[discord.ui.Button], template=r"alloc_leaderboard:(?P<year>\d{4})"):
    def __init__(self, year: int):
        super().__init__(
            discord.ui.Button(
                label="Leaderboard",
                emoji="🏆",
                style=discord.ButtonStyle.primary,
                custom_id=f"alloc_leaderboard:{year}"
            )
        )
        self.year = year

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match.group("year")))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This leaderboard only works in a server.", ephemeral=True)
            return

        embed = await allocation_leaderboard_embed(interaction.guild.id, self.year)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class AllocationLoggedView(discord.ui.View):
    def __init__(self, year: int):
        super().__init__(timeout=None)
        self.add_item(AllocationLeaderboardButton(year))


class BottleListButton(discord.ui.Button):
    def __init__(self, direction: int, *, disabled: bool = False):
        super().__init__(
            label="Previous" if direction < 0 else "Next",
            emoji="◀️" if direction < 0 else "▶️",
            style=discord.ButtonStyle.secondary,
            disabled=disabled
        )
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, BottleListView):
            await interaction.response.send_message("This bottle list expired. Run `/bottlelist` again.", ephemeral=True)
            return

        if interaction.user.id != view.user_id:
            await interaction.response.send_message("This is someone else’s bottle list. Run `/bottlelist` to make your own.", ephemeral=True)
            return

        view.page += self.direction
        embed, safe_page, total_pages = bottle_list_embed(view.search, view.page)
        view.page = safe_page
        view.refresh_buttons(total_pages)
        await interaction.response.edit_message(embed=embed, view=view)


class BottleListView(discord.ui.View):
    def __init__(self, user_id: int, search: Optional[str], page: int, total_pages: int):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.search = search
        self.page = page
        self.refresh_buttons(total_pages)

    def refresh_buttons(self, total_pages: int):
        self.clear_items()
        self.add_item(BottleListButton(-1, disabled=self.page <= 1))
        self.add_item(BottleListButton(1, disabled=self.page >= total_pages))


class BottleSubmissionApproveButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bottle_submit_approve:(?P<submission_id>[a-f0-9]+)"):
    def __init__(self, submission_id: str):
        super().__init__(
            discord.ui.Button(
                label="Approve / Merge",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id=f"bottle_submit_approve:{submission_id}"
            )
        )
        self.submission_id = submission_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("submission_id"))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Bottle submissions can only be reviewed in a server.", ephemeral=True)
            return

        permissions = interaction.channel.permissions_for(interaction.user) if interaction.channel else None

        if not permissions or not permissions.manage_guild:
            await interaction.response.send_message("Only mods with Manage Server can approve bottle submissions.", ephemeral=True)
            return

        approved_name, result = approve_bottle_submission(self.submission_id, interaction.user)

        if not approved_name:
            await interaction.response.send_message("That submission is already handled or missing.", ephemeral=True)
            return

        submission = BOTTLE_SUBMISSIONS[self.submission_id]
        embed = submission_embed(self.submission_id, submission)
        await interaction.response.edit_message(embed=embed, view=None)

        submitter = interaction.guild.get_member(submission["submitter_id"])

        if submitter:
            try:
                await submitter.send(
                    f"🥃 Your bottle submission for **{approved_name}** was approved. "
                    f"NeatBot can now find it. Nice little database pour."
                )
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"Approved **{approved_name}** ({result}).",
            ephemeral=True
        )


class BottleSubmissionSeparateButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bottle_submit_separate:(?P<submission_id>[a-f0-9]+)"):
    def __init__(self, submission_id: str):
        super().__init__(
            discord.ui.Button(
                label="Add Separately",
                emoji="➕",
                style=discord.ButtonStyle.primary,
                custom_id=f"bottle_submit_separate:{submission_id}"
            )
        )
        self.submission_id = submission_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("submission_id"))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Bottle submissions can only be reviewed in a server.", ephemeral=True)
            return

        permissions = interaction.channel.permissions_for(interaction.user) if interaction.channel else None

        if not permissions or not permissions.manage_guild:
            await interaction.response.send_message("Only mods with Manage Server can add bottle submissions.", ephemeral=True)
            return

        approved_name, result = approve_bottle_submission(self.submission_id, interaction.user, force_separate=True)

        if not approved_name:
            await interaction.response.send_message("That submission is already handled or missing.", ephemeral=True)
            return

        submission = BOTTLE_SUBMISSIONS[self.submission_id]
        embed = submission_embed(self.submission_id, submission)
        await interaction.response.edit_message(embed=embed, view=None)

        submitter = interaction.guild.get_member(submission["submitter_id"])

        if submitter:
            try:
                await submitter.send(
                    f"🥃 Your bottle submission for **{approved_name}** was approved as a separate bottle. "
                    "NeatBot can now find it."
                )
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"Added **{approved_name}** separately.",
            ephemeral=True
        )


class BottleSubmissionRejectButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bottle_submit_reject:(?P<submission_id>[a-f0-9]+)"):
    def __init__(self, submission_id: str):
        super().__init__(
            discord.ui.Button(
                label="Reject",
                emoji="❌",
                style=discord.ButtonStyle.danger,
                custom_id=f"bottle_submit_reject:{submission_id}"
            )
        )
        self.submission_id = submission_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("submission_id"))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Bottle submissions can only be reviewed in a server.", ephemeral=True)
            return

        permissions = interaction.channel.permissions_for(interaction.user) if interaction.channel else None

        if not permissions or not permissions.manage_guild:
            await interaction.response.send_message("Only mods with Manage Server can reject bottle submissions.", ephemeral=True)
            return

        submission = reject_bottle_submission(self.submission_id, interaction.user)

        if not submission:
            await interaction.response.send_message("That submission is already handled or missing.", ephemeral=True)
            return

        embed = submission_embed(self.submission_id, submission)
        await interaction.response.edit_message(embed=embed, view=None)

        submitter = interaction.guild.get_member(submission["submitter_id"])

        if submitter:
            try:
                await submitter.send(
                    f"Your bottle submission for **{submission['name']}** was rejected by the mod team."
                )
            except discord.HTTPException:
                pass


class BottleSubmissionEditModal(discord.ui.Modal, title="Edit Bottle Draft"):
    def __init__(self, submission_id: str, submission: dict):
        super().__init__()
        self.submission_id = submission_id
        self.name = discord.ui.TextInput(
            label="Bottle name",
            default=submission.get("name") or "",
            required=True,
            max_length=180
        )
        self.aliases = discord.ui.TextInput(
            label="Aliases",
            default=", ".join(submission.get("aliases", [])),
            required=False,
            max_length=300
        )
        self.category = discord.ui.TextInput(
            label="Category",
            placeholder="Bourbon, Rye, Tennessee Whiskey, Tequila...",
            default=submission.get("category") or "",
            required=False,
            max_length=60
        )
        self.proof = discord.ui.TextInput(
            label="Proof",
            default="" if submission.get("proof") is None else str(submission["proof"]),
            required=False,
            max_length=20
        )
        self.msrp = discord.ui.TextInput(
            label="MSRP",
            default="" if submission.get("msrp") is None else str(submission["msrp"]),
            required=False,
            max_length=20
        )

        self.add_item(self.name)
        self.add_item(self.aliases)
        self.add_item(self.category)
        self.add_item(self.proof)
        self.add_item(self.msrp)

    async def on_submit(self, interaction: discord.Interaction):
        permissions = interaction.channel.permissions_for(interaction.user) if interaction.channel else None

        if not permissions or not permissions.manage_guild:
            await interaction.response.send_message("Only mods with Manage Server can edit bottle submissions.", ephemeral=True)
            return

        try:
            submission = update_bottle_submission(
                self.submission_id,
                interaction.user,
                {
                    "name": str(self.name),
                    "aliases": str(self.aliases),
                    "category": str(self.category),
                    "proof": parse_optional_float_text(str(self.proof), "Proof"),
                    "msrp": parse_optional_float_text(str(self.msrp), "MSRP"),
                }
            )
        except ValueError as error:
            await interaction.response.send_message(f"Could not update that draft: {error}", ephemeral=True)
            return

        if not submission:
            await interaction.response.send_message("That submission is already handled or missing.", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=submission_embed(self.submission_id, submission),
            view=BottleSubmissionReviewView(self.submission_id)
        )


class BottleSubmissionEditButton(discord.ui.DynamicItem[discord.ui.Button], template=r"bottle_submit_edit:(?P<submission_id>[a-f0-9]+)"):
    def __init__(self, submission_id: str):
        super().__init__(
            discord.ui.Button(
                label="Edit Draft",
                emoji="🛠️",
                style=discord.ButtonStyle.secondary,
                custom_id=f"bottle_submit_edit:{submission_id}"
            )
        )
        self.submission_id = submission_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match.group("submission_id"))

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("Bottle submissions can only be reviewed in a server.", ephemeral=True)
            return

        permissions = interaction.channel.permissions_for(interaction.user) if interaction.channel else None

        if not permissions or not permissions.manage_guild:
            await interaction.response.send_message("Only mods with Manage Server can edit bottle submissions.", ephemeral=True)
            return

        submission = BOTTLE_SUBMISSIONS.get(self.submission_id)

        if not submission or submission.get("status") != "pending":
            await interaction.response.send_message("That submission is already handled or missing.", ephemeral=True)
            return

        await interaction.response.send_modal(BottleSubmissionEditModal(self.submission_id, submission))


class BottleSubmissionReviewView(discord.ui.View):
    def __init__(self, submission_id: str):
        super().__init__(timeout=None)
        self.add_item(BottleSubmissionEditButton(submission_id))
        self.add_item(BottleSubmissionApproveButton(submission_id))
        self.add_item(BottleSubmissionSeparateButton(submission_id))
        self.add_item(BottleSubmissionRejectButton(submission_id))


UTILITY_ACTIONS = {
    "messageneat": {
        "label": "Message Neat",
        "emoji": "💬",
        "style": discord.ButtonStyle.success,
        "title": "💬 Message Neat",
        "description": "I’ll DM you and walk you through a copy/paste `/flip` post."
    },
    "flip": {
        "label": "Flip",
        "emoji": "🔁",
        "style": discord.ButtonStyle.primary,
        "title": "🔁 /flip",
        "description": "Creates an FT/ISO post with a discussion thread, BIN button, Close Offer button, and optional photo.",
        "example": "/flip ft:RR15 zip_code:60657 ft_value:700 iso:HH22 iso_value:750 ft_kicker:False iso_kicker:True rtr:True x_posted:False photo:<attach image>"
    },
    "bottle": {
        "label": "Bottle",
        "emoji": "🥃",
        "style": discord.ButtonStyle.secondary,
        "title": "🥃 /bottle",
        "description": "Looks up proof, style, MSRP, profile, and similar bottles.",
        "example": "/bottle name:RR15"
    },
    "bottlelist": {
        "label": "Bottle List",
        "emoji": "📚",
        "style": discord.ButtonStyle.secondary,
        "title": "📚 /bottlelist",
        "description": "Browse the whole bottle database newest-first, or search by name, alias, brand, or category.",
        "example": "/bottlelist search:weller"
    },
    "worth": {
        "label": "Worth",
        "emoji": "🌮",
        "style": discord.ButtonStyle.secondary,
        "title": "🌮 /worth",
        "description": "Checks a bottle against MSRP, fair range, and secondary-ish range.",
        "example": "/worth name:Weller Antique 107 price:90"
    },
    "compare": {
        "label": "Compare",
        "emoji": "⚖️",
        "style": discord.ButtonStyle.secondary,
        "title": "⚖️ /compare",
        "description": "Compares two bottles side by side and picks one based on NeatBot score.",
        "example": "/compare bottle_one:Stagg bottle_two:Elijah Craig Barrel Proof"
    },
    "suggestbottle": {
        "label": "Suggest Bottle",
        "emoji": "➕",
        "style": discord.ButtonStyle.secondary,
        "title": "➕ /suggestbottle",
        "description": "Submits a bottle or alias to mods for approval before NeatBot adds it.",
        "example": "/suggestbottle name:Rare Bottle 2026 aliases:RB26, Rare Bottle proof:115 msrp:150 source_url:https://example.com"
    },
    "suggestbottleurl": {
        "label": "Suggest URL",
        "emoji": "🔗",
        "style": discord.ButtonStyle.secondary,
        "title": "🔗 /suggestbottleurl",
        "description": "Fetches a bottle page URL, drafts bottle details, and sends it to mods for approval.",
        "example": "/suggestbottleurl url:https://www.breakingbourbon.com/review/example-bottle"
    },
    "taterfind": {
        "label": "Tater Find",
        "emoji": "🔔",
        "style": discord.ButtonStyle.secondary,
        "title": "🔔 /taterfind",
        "description": "Posts a rare bottle shelf alert in the current channel. Only the bottle name is required.",
        "example": "/taterfind bottle:RR15 find_type:On Shelf store:Binny's Lakeview price:250 quantity:1 notes:Behind customer service"
    },
    "juicetrip": {
        "label": "JuiceTrip",
        "emoji": "🚌",
        "style": discord.ButtonStyle.secondary,
        "title": "🚌 /juicetrip",
        "description": "Mod-only RSVP board for bourbon trips, tours, Airbnb capacity, maybes, and day-trip folks.",
        "example": "/juicetrip destination:Bardstown dates:Oct 10-12, 2026 airbnb_capacity:8 estimated_cost:150-200 tours:Heaven Hill, Willett, Bardstown Bourbon Co deadline:Sept 30"
    },
    "boty": {
        "label": "BOTY",
        "emoji": "🏆",
        "style": discord.ButtonStyle.secondary,
        "title": "🏆 /boty",
        "description": "Starts a Bottle of the Year score post with 1-10 voting buttons and a thread.",
        "example": "/boty name:Russell's Reserve 15 Year Bourbon (2024)"
    },
    "battle": {
        "label": "Battle",
        "emoji": "⚔️",
        "style": discord.ButtonStyle.secondary,
        "title": "⚔️ /battle",
        "description": "Starts a head-to-head bottle vote with a discussion thread.",
        "example": "/battle bottle_one:RR15 bottle_two:HH22"
    },
    "whadd": {
        "label": "WHADD",
        "emoji": "❓",
        "style": discord.ButtonStyle.secondary,
        "title": "❓ /whadd",
        "description": "Posts the WHADD?? image in this channel.",
        "example": "/whadd"
    },
    "bricked": {
        "label": "Bricked",
        "emoji": "🧱",
        "style": discord.ButtonStyle.secondary,
        "title": "🧱 /bricked",
        "description": "Posts the bricked image in this channel.",
        "example": "/bricked"
    },
    "doxxed": {
        "label": "Doxxed",
        "emoji": "📍",
        "style": discord.ButtonStyle.secondary,
        "title": "📍 /doxxed",
        "description": "Posts the doxxed image in this channel.",
        "example": "/doxxed"
    }
}


async def start_flip_helper_dm(interaction: discord.Interaction):
    FLIP_HELP_SESSIONS[interaction.user.id] = {"step": "ft", "data": {}}

    try:
        await interaction.user.send(flip_helper_intro())
    except discord.HTTPException:
        FLIP_HELP_SESSIONS.pop(interaction.user.id, None)
        await interaction.response.send_message(
            "I couldn’t DM you. Check your Discord privacy settings for this server, then try again.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        "I sent you a DM to build your `/flip` post.",
        ephemeral=True
    )


def utility_embed():
    embed = discord.Embed(
        title="🥃 NeatBot Utility Board",
        description=(
            "Use the buttons below to jump into NeatBot tools. "
            "Commands that need bottle names or values will show you a private quick-start example."
        ),
        color=discord.Color.from_str("#C9973A")
    )
    embed.add_field(name="💬 Message Neat", value="Starts the private `/flip` formatting wizard.", inline=False)
    embed.add_field(name="🔁 Trading", value="Use `/flip`, `/bottle`, `/bottlelist`, `/worth`, and `/compare` helpers.", inline=False)
    embed.add_field(name="➕ Bottle Database", value="Use `/suggestbottle` or `/suggestbottleurl` to submit missing bottles for mod approval.", inline=False)
    embed.add_field(name="🔔 Finds", value="Use `/taterfind` to post rare bottle shelf alerts.", inline=False)
    embed.add_field(name="🏆 Community", value="Start BOTY ratings, bottle battles, JuiceTrip RSVPs, or the WHADD image.", inline=False)
    embed.set_footer(text="NeatBot buttons preserve post history. Slash command examples are shown privately.")
    return embed


def utility_tip_embed(action: str):
    config = UTILITY_ACTIONS[action]
    embed = discord.Embed(
        title=config["title"],
        description=config["description"],
        color=discord.Color.from_str("#C9973A")
    )

    if config.get("example"):
        embed.add_field(name="Try this", value=f"```text\n{config['example']}\n```", inline=False)

    embed.set_footer(text="Run the slash command in the channel where you want NeatBot to respond.")
    return embed


class TaterFindModal(discord.ui.Modal, title="Tater Find Alert"):
    bottle = discord.ui.TextInput(
        label="Bottle",
        placeholder="RR15, Blanton's, GTS 2025...",
        required=True,
        max_length=120
    )
    store_location = discord.ui.TextInput(
        label="Store or location",
        placeholder="Binny's Lakeview, Costco, 123 Main St...",
        required=False,
        max_length=180
    )
    find_type = discord.ui.TextInput(
        label="On shelf or Brown Bag",
        placeholder="On shelf or Brown Bag",
        required=False,
        max_length=30
    )
    price = discord.ui.TextInput(
        label="Price",
        placeholder="250",
        required=False,
        max_length=20
    )
    notes = discord.ui.TextInput(
        label="Notes / qty",
        placeholder="Qty 2, behind customer service, limit 1, or paste source link...",
        required=False,
        max_length=400,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        store, location = match_tater_store(str(self.store_location))

        await post_tater_find_alert(
            interaction,
            bottle=str(self.bottle),
            store=store,
            location=location,
            find_type=parse_tater_find_type(str(self.find_type)),
            price=parse_tater_price(str(self.price)),
            quantity=None,
            notes=str(self.notes).strip() or None,
            source_link=None
        )


class FlipFormModal(discord.ui.Modal):
    def __init__(self, *, defaults: Optional[dict] = None, error: Optional[str] = None):
        super().__init__(title="Fix Flip Post" if error else "Create Flip Post")
        defaults = defaults or {}
        zip_placeholder = "60657"

        if error:
            zip_placeholder = f"{error} Example: 60657"[:100]

        self.ft = discord.ui.TextInput(
            label="FT or FS bottle(s)",
            placeholder="RR15, HH22 + GTS 2025, or Kentucky Nectar",
            default=defaults.get("ft"),
            required=True,
            max_length=220
        )
        self.iso = discord.ui.TextInput(
            label="ISO / looking for",
            placeholder="RR15, Blanton's Gold, tacos only, or leave blank for tacos only",
            default=defaults.get("iso"),
            required=False,
            max_length=220
        )
        self.ft_value = discord.ui.TextInput(
            label="FT/FS value",
            placeholder="Optional. Example: 700",
            default=defaults.get("ft_value"),
            required=False,
            max_length=20
        )
        self.iso_value = discord.ui.TextInput(
            label="ISO value",
            placeholder="Optional. Example: 750",
            default=defaults.get("iso_value"),
            required=False,
            max_length=20
        )
        self.zip_code = discord.ui.TextInput(
            label="ZIP code",
            placeholder=zip_placeholder,
            default=defaults.get("zip_code") or defaults.get("details"),
            required=True,
            max_length=5
        )

        self.add_item(self.ft)
        self.add_item(self.iso)
        self.add_item(self.ft_value)
        self.add_item(self.iso_value)
        self.add_item(self.zip_code)

    def current_defaults(self):
        return {
            "ft": str(self.ft).strip(),
            "iso": str(self.iso).strip(),
            "ft_value": str(self.ft_value).strip(),
            "iso_value": str(self.iso_value).strip(),
            "zip_code": str(self.zip_code).strip(),
        }

    async def retry_response(self, interaction: discord.Interaction, message: str, defaults: dict):
        await interaction.response.send_message(
            message,
            view=FlipFormRetryView(defaults, message),
            ephemeral=True
        )

    async def on_submit(self, interaction: discord.Interaction):
        defaults = self.current_defaults()
        ft_value_text = str(self.ft_value).strip()
        iso_value_text = str(self.iso_value).strip()
        ft_value = parse_plain_int(ft_value_text) if ft_value_text else None
        iso_value = parse_plain_int(iso_value_text) if iso_value_text else None

        if ft_value_text and ft_value is None:
            await self.retry_response(interaction, "Fix FT value: use a number like `700`.", defaults)
            return

        if iso_value_text and iso_value is None:
            await self.retry_response(interaction, "Fix ISO value: use a number like `750`.", defaults)
            return

        zip_code = str(self.zip_code).strip()

        if not ZIP_CODE_PATTERN.fullmatch(zip_code):
            await self.retry_response(interaction, "Add a valid 5-digit ZIP code.", defaults)
            return

        draft_id = uuid.uuid4().hex
        FLIP_FORM_DRAFTS[draft_id] = {
            "user_id": interaction.user.id,
            "ft": str(self.ft).strip(),
            "ft_value": ft_value,
            "zip_code": zip_code,
            "iso": str(self.iso).strip() or None,
            "iso_value": iso_value,
            "ft_kicker": False,
            "iso_kicker": False,
            "rtr": False,
            "x_posted": False,
        }

        await interaction.response.send_message(
            embed=flip_form_review_embed(draft_id),
            view=FlipFormReviewView(draft_id),
            ephemeral=True
        )


class FlipFormRetryButton(discord.ui.Button):
    def __init__(self, defaults: dict, error: str):
        super().__init__(
            label="Fix Flip Form",
            emoji="🛠️",
            style=discord.ButtonStyle.primary
        )
        self.defaults = defaults
        self.error = error

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FlipFormModal(defaults=self.defaults, error=self.error))


class FlipFormRetryView(discord.ui.View):
    def __init__(self, defaults: dict, error: str):
        super().__init__(timeout=900)
        self.add_item(FlipFormRetryButton(defaults, error))


def flip_form_review_embed(draft_id: str):
    draft = FLIP_FORM_DRAFTS.get(draft_id, {})
    embed = discord.Embed(
        title="Review Flip Questions",
        description="Answer each question below with the buttons, then post the flip.",
        color=discord.Color.from_str("#C9973A")
    )
    embed.add_field(name="📦 FT / FS", value=draft.get("ft") or "Missing", inline=False)
    embed.add_field(name="🌮 FT/FS Value", value=flip_taco_value(draft["ft_value"]) if draft.get("ft_value") is not None else "Blank", inline=True)
    embed.add_field(name="🔍 ISO", value=draft.get("iso") or "Tacos only", inline=False)
    embed.add_field(name="💵 ISO Value", value=flip_taco_value(draft["iso_value"]) if draft.get("iso_value") is not None else "Blank", inline=True)
    embed.add_field(name="📍 ZIP", value=draft.get("zip_code") or "Missing", inline=True)
    embed.add_field(name="🚫 RTR?", value=yes_no(draft.get("rtr")), inline=True)
    embed.add_field(name="📣 X-posted?", value=yes_no(draft.get("x_posted")), inline=True)
    embed.add_field(name="🥾 Buyer kicker?", value=yes_no(draft.get("ft_kicker")), inline=True)
    embed.add_field(name="🥾 Seller kicker?", value=yes_no(draft.get("iso_kicker")), inline=True)
    embed.set_footer(text="Photos are supported on /flip because Discord modals cannot upload files.")
    return embed


class FlipFormReviewButton(discord.ui.Button):
    def __init__(self, draft_id: str, action: str, label: str, emoji: str, *, row: int, style=discord.ButtonStyle.secondary):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            custom_id=f"flip_form:{action}:{draft_id}",
            row=row
        )
        self.draft_id = draft_id
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        draft = FLIP_FORM_DRAFTS.get(self.draft_id)

        if not draft:
            await interaction.response.edit_message(
                content="This flip draft expired. Run `/flipform` again.",
                embed=None,
                view=None
            )
            return

        if interaction.user.id != draft["user_id"]:
            await interaction.response.send_message("Only the person building this flip can use these buttons.", ephemeral=True)
            return

        if self.action == "post":
            await interaction.response.defer(ephemeral=True, thinking=True)
            posted = await post_flip_from_inputs(
                interaction,
                ft=draft["ft"],
                ft_value=draft["ft_value"],
                zip_code=draft["zip_code"],
                iso=draft["iso"],
                iso_value=draft["iso_value"],
                ft_kicker=draft["ft_kicker"],
                iso_kicker=draft["iso_kicker"],
                rtr=draft["rtr"],
                x_posted=draft["x_posted"],
                send_via_channel=True,
                send_success_followup=False
            )
            if not posted:
                return

            FLIP_FORM_DRAFTS.pop(self.draft_id, None)
            await interaction.edit_original_response(
                content="Posted your flip and created the thread.",
                embed=None,
                view=None
            )
            return

        if self.action in {"rtr", "x_posted", "ft_kicker", "iso_kicker"}:
            draft[self.action] = not draft.get(self.action, False)
            await interaction.response.edit_message(
                embed=flip_form_review_embed(self.draft_id),
                view=FlipFormReviewView(self.draft_id)
            )
            return


class FlipFormReviewView(discord.ui.View):
    def __init__(self, draft_id: str):
        super().__init__(timeout=900)
        self.add_item(FlipFormReviewButton(draft_id, "rtr", "RTR?", "🚫", row=0))
        self.add_item(FlipFormReviewButton(draft_id, "x_posted", "X-posted?", "📣", row=0))
        self.add_item(FlipFormReviewButton(draft_id, "ft_kicker", "Buyer kicker?", "🥾", row=1))
        self.add_item(FlipFormReviewButton(draft_id, "iso_kicker", "Seller kicker?", "🥾", row=1))
        self.add_item(FlipFormReviewButton(draft_id, "post", "Post Flip", "✅", row=2, style=discord.ButtonStyle.success))


class UtilityButton(discord.ui.Button):
    def __init__(self, action: str, *, row: int):
        config = UTILITY_ACTIONS[action]
        super().__init__(
            label=config["label"],
            emoji=config["emoji"],
            style=config["style"],
            custom_id=f"utility:{action}",
            row=row
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        if self.action == "messageneat":
            await start_flip_helper_dm(interaction)
            return

        if self.action == "whadd":
            if not WHADD_IMAGE_PATH.exists():
                await interaction.response.send_message(
                    "I can’t find the WHADD image file on the server.",
                    ephemeral=True
                )
                return

            file = discord.File(WHADD_IMAGE_PATH, filename="whadd.png")
            await interaction.response.send_message(file=file)
            return

        if self.action == "bricked":
            if not BRICKED_IMAGE_PATH.exists():
                await interaction.response.send_message(
                    "I can’t find the bricked image file on the server.",
                    ephemeral=True
                )
                return

            file = discord.File(BRICKED_IMAGE_PATH, filename="bricked.png")
            await interaction.response.send_message(file=file)
            return

        if self.action == "doxxed":
            if not DOXXED_IMAGE_PATH.exists():
                await interaction.response.send_message(
                    "I can’t find the doxxed image file on the server.",
                    ephemeral=True
                )
                return

            file = discord.File(DOXXED_IMAGE_PATH, filename="doxxed.jpg")
            await interaction.response.send_message(file=file)
            return

        if self.action == "taterfind":
            await interaction.response.send_modal(TaterFindModal())
            return

        if self.action == "flip":
            await interaction.response.send_modal(FlipFormModal())
            return

        await interaction.response.send_message(embed=utility_tip_embed(self.action), ephemeral=True)


class UtilityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(UtilityButton("messageneat", row=0))
        self.add_item(UtilityButton("flip", row=0))
        self.add_item(UtilityButton("bottle", row=0))
        self.add_item(UtilityButton("bottlelist", row=0))
        self.add_item(UtilityButton("worth", row=1))
        self.add_item(UtilityButton("compare", row=1))
        self.add_item(UtilityButton("taterfind", row=1))
        self.add_item(UtilityButton("juicetrip", row=2))
        self.add_item(UtilityButton("suggestbottleurl", row=2))
        self.add_item(UtilityButton("suggestbottle", row=2))
        self.add_item(UtilityButton("boty", row=3))
        self.add_item(UtilityButton("battle", row=2))
        self.add_item(UtilityButton("whadd", row=4))
        self.add_item(UtilityButton("bricked", row=4))
        self.add_item(UtilityButton("doxxed", row=4))


def is_allocation_tracker_channel(channel):
    return isinstance(channel, discord.TextChannel) and (
        channel.name == ALLOCATION_TRACKER_CHANNEL_NAME
        or channel.name.endswith("allocation-tracker")
    )


async def handle_allocation_tracker_message(message: discord.Message):
    if not message.guild or not is_allocation_tracker_channel(message.channel):
        return

    if not message.content.strip() or message.content.strip().startswith(("/", "!")):
        return

    if message.reference:
        return

    analysis = analyze_allocation_message(message.content)

    if not analysis:
        return

    pending_id = await create_pending_allocation(message, analysis["bottle_name"])
    embed = discord.Embed(
        title="🥃 Log this allocation?",
        description=f"I think you acquired **{analysis['bottle_name']}**.",
        color=discord.Color.from_str("#C9973A"),
    )
    embed.add_field(name="Matched", value=analysis["matched_alias"], inline=True)
    embed.add_field(name="Confidence", value=str(analysis["score"]), inline=True)
    embed.set_footer(text="Confirm to add this to the annual allocation tracker.")

    await message.reply(
        embed=embed,
        view=AllocationConfirmView(pending_id),
        mention_author=True,
    )


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    await bot.load_extension("group_trip")
    await init_allocation_db()
    bot.add_dynamic_items(BOTYScoreButton)
    bot.add_dynamic_items(BattleVoteButton)
    bot.add_dynamic_items(FlipBinButton)
    bot.add_dynamic_items(FlipCloseButton)
    bot.add_dynamic_items(AllocationConfirmButton)
    bot.add_dynamic_items(AllocationCancelButton)
    bot.add_dynamic_items(AllocationLeaderboardButton)
    bot.add_dynamic_items(BottleSubmissionApproveButton)
    bot.add_dynamic_items(BottleSubmissionSeparateButton)
    bot.add_dynamic_items(BottleSubmissionRejectButton)
    bot.add_dynamic_items(BottleSubmissionEditButton)
    bot.add_view(UtilityView())
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


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if isinstance(message.channel, discord.DMChannel):
        await handle_flip_helper_message(message)
        return

    await handle_allocation_tracker_message(message)
    await bot.process_commands(message)


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


@bot.tree.command(name="bottlelist", description="Browse or search the full NeatBot bottle list.")
@app_commands.describe(
    search="Optional search by name, alias, brand, category, or style",
    page="Optional page number"
)
async def bottlelist(
    interaction: discord.Interaction,
    search: Optional[str] = None,
    page: Optional[int] = 1
):
    safe_page = max(1, page or 1)
    clean_search = search.strip() if search and search.strip() else None
    embed, safe_page, total_pages = bottle_list_embed(clean_search, safe_page)
    await interaction.response.send_message(
        embed=embed,
        view=BottleListView(interaction.user.id, clean_search, safe_page, total_pages),
        ephemeral=True
    )


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


@bot.tree.command(name="suggestbottle", description="Suggest a bottle for mods to add to NeatBot.")
@app_commands.describe(
    name="Formal bottle name",
    aliases="Comma-separated aliases, e.g. RR15, Russell's 15, RR15 2024",
    proof="Optional proof",
    msrp="Optional MSRP",
    category="Optional category, e.g. Bourbon, Rye, Tennessee Whiskey, Tequila",
    source_url="Optional source/review/product URL",
    notes="Optional notes for the mod team"
)
async def suggestbottle(
    interaction: discord.Interaction,
    name: str,
    aliases: Optional[str] = None,
    proof: Optional[float] = None,
    msrp: Optional[float] = None,
    category: Optional[str] = None,
    source_url: Optional[str] = None,
    notes: Optional[str] = None,
):
    if not interaction.guild:
        await interaction.response.send_message("Bottle suggestions need to be submitted inside a server.", ephemeral=True)
        return

    clean_name = name.strip()

    if len(clean_name) < 3:
        await interaction.response.send_message("Give me a real bottle name, not a barrel whisper.", ephemeral=True)
        return

    if proof is not None and proof <= 0:
        await interaction.response.send_message("Proof needs to be a positive number.", ephemeral=True)
        return

    if msrp is not None and msrp < 0:
        await interaction.response.send_message("MSRP cannot be negative.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    submission = bottle_submission_record(
        submitter=interaction.user,
        name=clean_name,
        aliases=aliases,
        proof=proof,
        msrp=msrp,
        category=category,
        source_url=source_url,
        notes=notes,
    )

    review_message, error = await submit_bottle_suggestion(interaction, submission)

    if error:
        await interaction.followup.send(
            error,
            ephemeral=True
        )
        return

    await interaction.followup.send(
        f"Submitted **{submission['name']}** for mod review: {review_message.jump_url}",
        ephemeral=True
    )


@bot.tree.command(name="suggestbottleurl", description="Suggest a bottle by URL for mods to review.")
@app_commands.describe(
    url="Review, product, or press-release URL to scan",
    notes="Optional notes for the mod team"
)
async def suggestbottleurl(
    interaction: discord.Interaction,
    url: str,
    notes: Optional[str] = None,
):
    if not interaction.guild:
        await interaction.response.send_message("Bottle suggestions need to be submitted inside a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    try:
        submission = await bottle_submission_from_url(interaction, url, notes)
    except (aiohttp.ClientError, TimeoutError, ValueError) as error:
        await interaction.followup.send(
            f"I couldn’t build a bottle draft from that URL: {error}",
            ephemeral=True
        )
        return

    review_message, error = await submit_bottle_suggestion(interaction, submission)

    if error:
        await interaction.followup.send(error, ephemeral=True)
        return

    await interaction.followup.send(
        f"Submitted **{submission['name']}** for mod review: {review_message.jump_url}",
        ephemeral=True
    )


@bot.tree.command(name="alloc-leaderboard", description="Show allocation tracker rankings.")
@app_commands.describe(year="Optional year, e.g. 2025")
async def alloc_leaderboard(interaction: discord.Interaction, year: Optional[int] = None):
    if not interaction.guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return

    year = year or allocation_year()
    embed = await allocation_leaderboard_embed(interaction.guild.id, year)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="alloc-stats", description="Show your allocation tracker stats.")
@app_commands.describe(year="Optional year, e.g. 2025")
async def alloc_stats(interaction: discord.Interaction, year: Optional[int] = None):
    if not interaction.guild:
        await interaction.response.send_message("This command only works in a server.", ephemeral=True)
        return

    year = year or allocation_year()
    total, favorite, recent, rank = await allocation_user_stats(interaction.guild.id, interaction.user.id, year)
    embed = discord.Embed(
        title=f"🥃 {year} Allocation Stats",
        description=f"{interaction.user.mention} allocation report",
        color=discord.Color.from_str("#C9973A"),
    )
    embed.add_field(name="Total Allocations", value=str(total), inline=True)
    embed.add_field(name="Ranking", value=f"#{rank}" if rank else "Unranked", inline=True)
    embed.add_field(
        name="Favorite Bottle",
        value=f"{favorite['bottle_name']} ({favorite['total']})" if favorite else "None yet",
        inline=False,
    )
    embed.add_field(
        name="Recent Pickups",
        value="\n".join(f"• {row['bottle_name']}" for row in recent) if recent else "None yet",
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


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


@bot.tree.command(name="whadd", description="Post the WHADD?? image.")
async def whadd(interaction: discord.Interaction):
    if not WHADD_IMAGE_PATH.exists():
        await interaction.response.send_message(
            "I can’t find the WHADD image file on the server.",
            ephemeral=True
        )
        return

    file = discord.File(WHADD_IMAGE_PATH, filename="whadd.png")
    await interaction.response.send_message(file=file)


@bot.tree.command(name="nerd", description="Post the nerd image.")
async def nerd(interaction: discord.Interaction):
    if not NERD_IMAGE_PATH.exists():
        await interaction.response.send_message(
            "I can’t find the nerd image file on the server.",
            ephemeral=True
        )
        return

    try:
        file = discord.File(NERD_IMAGE_PATH, filename="nerd.jpg")
        await interaction.response.send_message(file=file)
    except discord.HTTPException:
        await interaction.response.send_message(
            "Discord wouldn’t let me post that image here. A mod may need to give NeatBot Attach Files permission.",
            ephemeral=True
        )


@bot.tree.command(name="bricked", description="Post the bricked image.")
async def bricked(interaction: discord.Interaction):
    if not BRICKED_IMAGE_PATH.exists():
        await interaction.response.send_message(
            "I can’t find the bricked image file on the server.",
            ephemeral=True
        )
        return

    try:
        file = discord.File(BRICKED_IMAGE_PATH, filename="bricked.png")
        await interaction.response.send_message(file=file)
    except discord.HTTPException:
        await interaction.response.send_message(
            "Discord wouldn’t let me post that image here. A mod may need to give NeatBot Attach Files permission.",
            ephemeral=True
        )


@bot.tree.command(name="doxxed", description="Post the doxxed image.")
async def doxxed(interaction: discord.Interaction):
    if not DOXXED_IMAGE_PATH.exists():
        await interaction.response.send_message(
            "I can’t find the doxxed image file on the server.",
            ephemeral=True
        )
        return

    try:
        file = discord.File(DOXXED_IMAGE_PATH, filename="doxxed.jpg")
        await interaction.response.send_message(file=file)
    except discord.HTTPException:
        await interaction.response.send_message(
            "Discord wouldn’t let me post that image here. A mod may need to give NeatBot Attach Files permission.",
            ephemeral=True
        )


@bot.tree.command(name="sassy", description="Get a ridiculous bourbon/tater one-liner.")
async def sassy(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(SASSY_ONE_LINERS))


@bot.tree.command(name="messageneat", description="Start a DM with NeatBot to format a /flip post.")
async def messageneat(interaction: discord.Interaction):
    await start_flip_helper_dm(interaction)


@bot.tree.command(name="utility", description="Post the NeatBot utility board with buttons for common tools.")
async def utility(interaction: discord.Interaction):
    await interaction.response.send_message(embed=utility_embed(), view=UtilityView(), ephemeral=True)


@bot.tree.command(name="taterfind", description="Post a rare bottle shelf alert in the current channel.")
@app_commands.describe(
    bottle="Name of the rare bottle spotted",
    find_type="Whether the bottle was on shelf or brown bag",
    store="Store group/location to alert",
    location="Specific store address or location",
    price="Retail price seen on shelf",
    quantity="Number of bottles spotted",
    notes="Shelf location, limits, timing, or other useful details",
    source="Link to the original Discord post or forwarded source",
    photo="Photo of the find"
)
@app_commands.choices(store=TATER_STORE_CHOICES)
@app_commands.choices(find_type=TATER_FIND_TYPE_CHOICES)
async def taterfind(
    interaction: discord.Interaction,
    bottle: str,
    find_type: Optional[str] = None,
    store: Optional[str] = None,
    location: Optional[str] = None,
    price: Optional[float] = None,
    quantity: Optional[int] = None,
    notes: Optional[str] = None,
    source: Optional[str] = None,
    photo: Optional[discord.Attachment] = None
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    await post_tater_find_alert(
        interaction,
        bottle=bottle,
        store=store,
        location=location,
        find_type=find_type,
        price=price,
        quantity=quantity,
        notes=notes,
        source_link=source,
        photo=photo
    )


async def post_flip_from_inputs(
    interaction: discord.Interaction,
    *,
    ft: str,
    ft_value: Optional[int],
    zip_code: str,
    iso: Optional[str] = None,
    iso_value: Optional[int] = None,
    ft_kicker: Optional[bool] = False,
    iso_kicker: Optional[bool] = False,
    rtr: Optional[bool] = False,
    x_posted: Optional[bool] = False,
    send_via_channel: bool = False,
    photo_url: Optional[str] = None,
    send_success_followup: bool = True,
):
    async def send_private_error(message: str):
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    if not interaction.guild or not isinstance(interaction.channel, discord.abc.GuildChannel):
        await send_private_error("`/flip` can only be used inside a server channel.")
        return False

    bot_member = interaction.guild.me

    if bot_member:
        missing_permissions = missing_flip_permissions(interaction.channel, bot_member)

        if missing_permissions:
            await send_private_error(
                "I need these channel permissions before I can create and close flip threads:\n"
                f"{', '.join(missing_permissions)}"
            )
            return False

    if not ft or not ft.strip():
        await send_private_error("Tell me what bottle is FT/FS first.")
        return False

    if ft_value is not None and ft_value <= 0:
        await send_private_error("Use a positive FT value, or leave it blank for a straight bottle-for-bottle trade.")
        return False

    if iso_value is not None and iso_value <= 0:
        await send_private_error("Use a positive value for the ISO bottle, or leave it blank for a straight bottle-for-bottle trade.")
        return False

    ft, seller_text_kicker = strip_kicker_text(ft, False)
    ft = canonical_bottle_list(ft or "")
    iso, iso_value, iso_kicker = parse_iso_details(iso, iso_value, iso_kicker)
    iso_kicker = bool(iso_kicker or seller_text_kicker)

    if iso and iso != "🌮 Tacos":
        iso = canonical_bottle_list(iso)

    value_warning = has_value_mismatch(ft_value, iso_value)
    iso_needs_vintage_tip = bool(iso) and not VINTAGE_YEAR_PATTERN.search(iso)
    location = await resolve_zip_location(zip_code)

    if location is None:
        await send_private_error("Enter a 5-digit US ZIP so I can show City, State.")
        return False

    seller_kicker, buyer_kicker = flip_kicker_flags(ft_value, iso_value, iso_kicker, ft_kicker)
    seller_kicker_text = seller_kicker_label(ft_value, iso_value) if seller_kicker else None
    buyer_kicker_text = buyer_kicker_label(ft_value, iso_value) if buyer_kicker else None
    ft_target = f"{ft} + {seller_kicker_text}" if seller_kicker_text else ft
    target = iso_thread_target(iso, iso_value, buyer_kicker_text)
    offer_kind = flip_offer_kind(iso)
    trade_only = bool(iso and ft_value is None and iso_value is None)
    thread_name = thread_safe_name(f"🥃 {offer_kind}: {ft_target} ↔ {target}")
    seller_name = interaction.user.display_name
    announcement_ft = ft_target

    if iso:
        trade_note = " Bottle-for-bottle trade only ♻️" if trade_only else ""
        announcement_description = (
            f"{seller_name} is offering **{announcement_ft}** — ISO **{target}**. "
            f"Drop a ✅ or hit BIN below 👇{trade_note}"
        )
    else:
        announcement_description = (
            f"{seller_name} is offering **{announcement_ft}** — looking for tacos only. "
            "Drop a ✅ or hit BIN below 👇"
        )

    announcement = discord.Embed(
        title=f"🥃 {offer_kind}: {ft}",
        description=announcement_description,
        color=discord.Color.from_str("#C9973A")
    )

    if send_via_channel:
        message = await interaction.channel.send(embed=announcement)
    else:
        await interaction.response.send_message(embed=announcement)
        message = await interaction.original_response()

    try:
        thread = await message.create_thread(name=thread_name)
    except discord.HTTPException:
        await message.reply("I could not create the flip thread. A mod may need to check my thread permissions.")
        return False

    detail_embed = flip_embed(
        ft=ft,
        ft_value=ft_value,
        iso=iso,
        iso_value=iso_value,
        ft_kicker=buyer_kicker,
        iso_kicker=seller_kicker,
        rtr=rtr,
        x_posted=x_posted,
        location=location,
        seller=interaction.user,
        posted_at=interaction.created_at,
        photo_url=photo_url
    )
    detail_message = await thread.send(
        embed=detail_embed,
        view=FlipBinView(message.id)
    )

    try:
        await detail_message.add_reaction("✅")
    except discord.HTTPException:
        pass

    if send_via_channel and send_success_followup:
        await interaction.followup.send("Posted your flip and created the thread.", ephemeral=True)

    if value_warning:
        await interaction.followup.send(
            f"⚠️ Your ISO value ({flip_taco_value(iso_value)}) is significantly higher than "
            f"your FT value ({flip_taco_value(ft_value)}). Consider adding a seller kicker or adjusting values.",
            ephemeral=True
        )

    if iso_needs_vintage_tip:
        await interaction.followup.send(
            "📅 Tip: Your ISO doesn't mention a vintage year. If you're open to any year, "
            'consider adding "any year" to your ISO description next time.',
            ephemeral=True
        )

    return True


@bot.tree.command(name="flip", description="Post a bottle flip with a BIN button and discussion thread.")
@app_commands.describe(
    ft="Bottle or bottles being offered, e.g. RR15 + Weller 12",
    zip_code="Your 5-digit US ZIP for City, State display",
    ft_value="Optional estimated FT value",
    iso="Optional ISO bottle or bottles. Leave blank for tacos only.",
    iso_value="Optional ISO value",
    ft_kicker="Whether the buyer needs to add a kicker toward your FT",
    iso_kicker="Whether you need to add a kicker toward your ISO",
    rtr="Right to refuse",
    x_posted="Whether this flip is x-posted",
    photo="Optional bottle photo to show in the flip thread"
)
async def flip(
    interaction: discord.Interaction,
    ft: str,
    zip_code: str,
    ft_value: Optional[int] = None,
    iso: Optional[str] = None,
    iso_value: Optional[int] = None,
    ft_kicker: Optional[bool] = False,
    iso_kicker: Optional[bool] = False,
    rtr: Optional[bool] = False,
    x_posted: Optional[bool] = False,
    photo: Optional[discord.Attachment] = None
):
    await post_flip_from_inputs(
        interaction,
        ft=ft,
        ft_value=ft_value,
        zip_code=zip_code,
        iso=iso,
        iso_value=iso_value,
        ft_kicker=ft_kicker,
        iso_kicker=iso_kicker,
        rtr=rtr,
        x_posted=x_posted,
        photo_url=photo.url if photo else None
    )


@bot.tree.command(name="flipform", description="Open a private form that builds a bottle flip post.")
async def flipform(interaction: discord.Interaction):
    await interaction.response.send_modal(FlipFormModal())


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

    await interaction.response.send_message(embed=starter_embed)
    message = await interaction.original_response()
    message_id = str(message.id)

    BOTY_VOTES[message_id] = {
        "bottle": bottle_name,
        "channel_id": message.channel.id,
        "message_id": message.id,
        "votes": {}
    }
    save_json(BOTY_VOTES_PATH, BOTY_VOTES)

    try:
        thread = await message.create_thread(name=f"BOTY: {bottle_name}"[:100])
        BOTY_VOTES[message_id]["thread_id"] = thread.id
        thread_message = await thread.send(embed=boty_embed(message_id), view=BOTYView(message_id))
        BOTY_VOTES[message_id]["thread_message_id"] = thread_message.id
        save_json(BOTY_VOTES_PATH, BOTY_VOTES)
        await thread.send(f"Discuss **{bottle_name}** here. What score did it earn and why?")
    except discord.HTTPException:
        pass

    await message.edit(embed=boty_embed(message_id), view=BOTYView(message_id))


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

    await interaction.response.send_message(embed=starter_embed)
    message = await interaction.original_response()
    message_id = str(message.id)

    BATTLE_VOTES[message_id] = {
        "bottle_one": name1,
        "bottle_two": name2,
        "channel_id": message.channel.id,
        "message_id": message.id,
        "votes": {}
    }
    save_json(BATTLE_VOTES_PATH, BATTLE_VOTES)

    try:
        thread = await message.create_thread(name=f"Battle: {name1} vs {name2}"[:100])
        BATTLE_VOTES[message_id]["thread_id"] = thread.id
        thread_message = await thread.send(embed=battle_embed(message_id), view=BattleView(message_id))
        BATTLE_VOTES[message_id]["thread_message_id"] = thread_message.id
        save_json(BATTLE_VOTES_PATH, BATTLE_VOTES)
        await thread.send(
            f"Battle thread: **{name1}** vs **{name2}**.\n"
            "Make your case. Flavor, value, proof, hype, bottle kill stories, all of it."
        )
    except discord.HTTPException:
        pass

    await message.edit(embed=battle_embed(message_id), view=BattleView(message_id))


if not TOKEN:
    raise RuntimeError("Missing DISCORD_TOKEN. Put it in your .env file.")

if __name__ == "__main__":
    bot.run(TOKEN)
