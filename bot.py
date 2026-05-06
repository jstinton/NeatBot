import os
import json
import difflib
import re
from pathlib import Path
from typing import Optional

import aiohttp
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
WHADD_IMAGE_PATH = Path(__file__).parent / "assets" / "whadd.png"
ZIP_CODE_PATTERN = re.compile(r"^\d{5}$")
USER_MENTION_PATTERN = re.compile(r"<@!?(?P<user_id>\d+)>")
VINTAGE_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
DISCORD_ID_PATTERN = re.compile(r"^\d{15,25}$")


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


def configured_tater_location(store: str, location: Optional[str]):
    store_config = STORE_ROLE_MAP.get(store, {})
    configured_address = store_config.get("address")

    if configured_address and configured_address != "TBD":
        return configured_address

    return location


def tater_store_needs_location(store: str):
    return STORE_ROLE_MAP.get(store, {}).get("address") == "TBD"


def tater_role_tag(store: str):
    role_id = STORE_ROLE_MAP.get(store, {}).get("role_id")

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


def taterfind_message(
    *,
    bottle: str,
    store: str,
    location: str,
    price: Optional[float],
    quantity: Optional[int],
    notes: Optional[str],
):
    lines = [
        "🥃 **TATER FIND ALERT** 🥃",
        "",
        f"**Bottle:** {bottle}",
        f"**Store:** {store} — {location}",
    ]

    formatted_price = tater_price(price)

    if formatted_price:
        lines.append(f"**Price:** {formatted_price}")

    if quantity is not None:
        lines.append(f"**Qty Seen:** {quantity}")

    if notes:
        lines.append(f"**Notes:** {notes}")

    role_tag = tater_role_tag(store)

    if role_tag:
        lines.extend(["", f"{role_tag} — heads up! 🔔"])

    lines.extend(["", "_Posted via /taterfind · NeatBot_"])

    return "\n".join(lines)


BOTY_VOTES = load_json(BOTY_VOTES_PATH, {})
BATTLE_VOTES = load_json(BATTLE_VOTES_PATH, {})
FLIP_HELP_SESSIONS = {}


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


def has_value_mismatch(ft_value: int, iso_value: Optional[int]):
    return iso_value is not None and iso_value * 100 > ft_value * 115


def seller_kicker_amount(ft_value: int, iso_value: Optional[int]):
    if iso_value is None or iso_value <= ft_value:
        return None

    return iso_value - ft_value


def buyer_kicker_amount(ft_value: int, iso_value: Optional[int]):
    if iso_value is None or ft_value <= iso_value:
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


def seller_kicker_label(ft_value: int, iso_value: Optional[int]):
    return kicker_label(seller_kicker_amount(ft_value, iso_value))


def buyer_kicker_label(ft_value: int, iso_value: Optional[int]):
    return kicker_label(buyer_kicker_amount(ft_value, iso_value))


def seller_kicker_field_value(ft_value: int, iso_value: Optional[int]):
    return kicker_field_value(seller_kicker_amount(ft_value, iso_value))


def buyer_kicker_field_value(ft_value: int, iso_value: Optional[int]):
    return kicker_field_value(buyer_kicker_amount(ft_value, iso_value))


def flip_kicker_flags(ft_value: int, iso_value: Optional[int], seller_requested: Optional[bool], buyer_requested: Optional[bool]):
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

    if re.search(r"\bcash\b", value, flags=re.IGNORECASE):
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
    ft_value: int,
    iso: Optional[str],
    iso_value: Optional[int],
    ft_kicker: Optional[bool],
    iso_kicker: Optional[bool],
    rtr: Optional[bool],
    x_posted: Optional[bool],
    location: str,
    seller,
    posted_at,
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
    embed.add_field(name="💰 Est. Value (per seller):", value=flip_taco_value(ft_value), inline=True)

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
        "description": "Creates an FT/ISO post with a discussion thread, BIN button, and Close Offer button.",
        "example": "/flip ft:RR15 ft_value:700 zip_code:60657 iso:HH22 iso_value:750 ft_kicker:False iso_kicker:True rtr:True x_posted:False"
    },
    "bottle": {
        "label": "Bottle",
        "emoji": "🥃",
        "style": discord.ButtonStyle.secondary,
        "title": "🥃 /bottle",
        "description": "Looks up proof, style, MSRP, profile, and similar bottles.",
        "example": "/bottle name:RR15"
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
    embed.add_field(name="🔁 Trading", value="Use `/flip`, `/bottle`, `/worth`, and `/compare` helpers.", inline=False)
    embed.add_field(name="🏆 Community", value="Start BOTY ratings, bottle battles, or the WHADD image.", inline=False)
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

        await interaction.response.send_message(embed=utility_tip_embed(self.action), ephemeral=True)


class UtilityView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(UtilityButton("messageneat", row=0))
        self.add_item(UtilityButton("flip", row=0))
        self.add_item(UtilityButton("bottle", row=0))
        self.add_item(UtilityButton("worth", row=0))
        self.add_item(UtilityButton("compare", row=0))
        self.add_item(UtilityButton("boty", row=1))
        self.add_item(UtilityButton("battle", row=1))
        self.add_item(UtilityButton("whadd", row=1))


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    bot.add_dynamic_items(BOTYScoreButton)
    bot.add_dynamic_items(BattleVoteButton)
    bot.add_dynamic_items(FlipBinButton)
    bot.add_dynamic_items(FlipCloseButton)
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


@bot.tree.command(name="messageneat", description="Start a DM with NeatBot to format a /flip post.")
async def messageneat(interaction: discord.Interaction):
    await start_flip_helper_dm(interaction)


@bot.tree.command(name="utility", description="Post the NeatBot utility board with buttons for common tools.")
async def utility(interaction: discord.Interaction):
    await interaction.response.send_message(embed=utility_embed(), view=UtilityView(), ephemeral=True)


@bot.tree.command(name="taterfind", description="Post a rare bottle shelf alert to the tater-finds channel.")
@app_commands.describe(
    bottle="Name of the rare bottle spotted",
    store="Store group/location to alert",
    location="Specific store address or location. Only needed for TBD regions.",
    price="Retail price seen on shelf",
    quantity="Number of bottles spotted",
    notes="Shelf location, limits, timing, or other useful details",
    photo="Photo of the find"
)
@app_commands.choices(store=TATER_STORE_CHOICES)
async def taterfind(
    interaction: discord.Interaction,
    bottle: str,
    store: str,
    location: Optional[str] = None,
    price: Optional[float] = None,
    quantity: Optional[int] = None,
    notes: Optional[str] = None,
    photo: Optional[discord.Attachment] = None
):
    await interaction.response.defer(ephemeral=True, thinking=True)

    if price is not None and price < 0:
        await interaction.followup.send("Price cannot be negative.", ephemeral=True)
        return

    if quantity is not None and quantity < 1:
        await interaction.followup.send("Quantity needs to be at least 1.", ephemeral=True)
        return

    if tater_store_needs_location(store) and not location:
        await interaction.followup.send(
            "That store group needs a location, since it does not have a saved address yet.",
            ephemeral=True
        )
        return

    try:
        channel = interaction.channel

        if channel is None or not hasattr(channel, "send"):
            await interaction.followup.send(
                "I can’t post alerts in this channel.",
                ephemeral=True
            )
            return

        bottle_name, _ = find_bottle(bottle)
        display_bottle = bottle_name or canonical_bottle_name(bottle)
        resolved_location = configured_tater_location(store, location)
        content = taterfind_message(
            bottle=display_bottle,
            store=store,
            location=resolved_location,
            price=price,
            quantity=quantity,
            notes=notes,
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


@bot.tree.command(name="flip", description="Post a bottle flip with a BIN button and discussion thread.")
@app_commands.describe(
    ft="Bottle or bottles being offered, e.g. RR15 + Weller 12",
    ft_value="Estimated FT value",
    zip_code="Your 5-digit US ZIP for City, State display",
    iso="Optional ISO bottle or bottles. Leave blank for tacos only.",
    iso_value="Optional ISO value",
    ft_kicker="Whether the buyer needs to add a kicker toward your FT",
    iso_kicker="Whether you need to add a kicker toward your ISO",
    rtr="Right to refuse",
    x_posted="Whether this flip is x-posted"
)
async def flip(
    interaction: discord.Interaction,
    ft: str,
    ft_value: int,
    zip_code: str,
    iso: Optional[str] = None,
    iso_value: Optional[int] = None,
    ft_kicker: Optional[bool] = False,
    iso_kicker: Optional[bool] = False,
    rtr: Optional[bool] = False,
    x_posted: Optional[bool] = False
):
    if not interaction.guild or not isinstance(interaction.channel, discord.abc.GuildChannel):
        await interaction.response.send_message(
            "`/flip` can only be used inside a server channel.",
            ephemeral=True
        )
        return

    bot_member = interaction.guild.me

    if bot_member:
        missing_permissions = missing_flip_permissions(interaction.channel, bot_member)

        if missing_permissions:
            await interaction.response.send_message(
                "I need these channel permissions before I can create and close flip threads:\n"
                f"{', '.join(missing_permissions)}",
                ephemeral=True
            )
            return

    if ft_value <= 0:
        await interaction.response.send_message(
            "Use a positive FT value.",
            ephemeral=True
        )
        return

    if iso_value is not None and iso_value <= 0:
        await interaction.response.send_message(
            "Use a positive value for the ISO bottle.",
            ephemeral=True
        )
        return

    ft, seller_text_kicker = strip_kicker_text(ft, False)
    ft = canonical_bottle_list(ft)
    iso, iso_value, iso_kicker = parse_iso_details(iso, iso_value, iso_kicker)
    iso_kicker = bool(iso_kicker or seller_text_kicker)

    if iso and iso != "🌮 Tacos":
        iso = canonical_bottle_list(iso)

    value_warning = has_value_mismatch(ft_value, iso_value)
    iso_needs_vintage_tip = bool(iso) and not VINTAGE_YEAR_PATTERN.search(iso)
    location = await resolve_zip_location(zip_code)

    if location is None:
        await interaction.response.send_message(
            "Enter a 5-digit US ZIP so I can show City, State.",
            ephemeral=True
        )
        return

    seller_kicker, buyer_kicker = flip_kicker_flags(ft_value, iso_value, iso_kicker, ft_kicker)
    seller_kicker_text = seller_kicker_label(ft_value, iso_value) if seller_kicker else None
    buyer_kicker_text = buyer_kicker_label(ft_value, iso_value) if buyer_kicker else None
    ft_target = f"{ft} + {seller_kicker_text}" if seller_kicker_text else ft
    target = iso_thread_target(iso, iso_value, buyer_kicker_text)
    offer_kind = flip_offer_kind(iso)
    thread_name = thread_safe_name(f"🥃 {offer_kind}: {ft_target} ↔ {target}")
    seller_name = interaction.user.display_name
    announcement_ft = ft_target

    if iso:
        announcement_description = (
            f"{seller_name} is offering **{announcement_ft}** — ISO **{target}**. "
            "Drop a ✅ or hit BIN below 👇"
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

    await interaction.response.send_message(embed=announcement)
    message = await interaction.original_response()

    try:
        thread = await message.create_thread(name=thread_name)
    except discord.HTTPException:
        await message.reply("I could not create the flip thread. A mod may need to check my thread permissions.")
        return

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
        posted_at=interaction.created_at
    )
    detail_message = await thread.send(
        embed=detail_embed,
        view=FlipBinView(message.id)
    )

    try:
        await detail_message.add_reaction("✅")
    except discord.HTTPException:
        pass

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
