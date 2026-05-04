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


def find_exact_bottle(query: str):
    q = normalize(query)

    for name in BOTTLE_NAMES:
        if q == normalize(name):
            return name, BOTTLES[name]

    for name, data in BOTTLES.items():
        for alias in data.get("aliases", []):
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


def seller_kicker_label(ft_value: int, iso_value: Optional[int]):
    amount = seller_kicker_amount(ft_value, iso_value)

    if amount is None:
        return "🥾"

    return f"🥾 {flip_taco_value(amount)}"


def seller_kicker_field_value(ft_value: int, iso_value: Optional[int]):
    amount = seller_kicker_amount(ft_value, iso_value)

    if amount is None:
        return "Yes"

    return f"Yes — {flip_taco_value(amount)}"


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


def iso_thread_target(iso: Optional[str], iso_value: Optional[int]):
    parts = []

    if iso:
        parts.append(iso)
    elif iso_value is None:
        parts.append("🌮 Tacos")

    if iso_value is not None:
        parts.append(flip_taco_value(iso_value))

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
    embed = discord.Embed(
        title=f"🥃 {ft}",
        color=discord.Color.from_str("#C9973A")
    )
    embed.add_field(name="📦 FT:", value=format_bottle_list(ft), inline=False)
    embed.add_field(name="💰 Est. Value (per seller):", value=flip_taco_value(ft_value), inline=True)

    if ft_kicker or iso_kicker:
        embed.add_field(name="🥾 Seller Kicker:", value=seller_kicker_field_value(ft_value, iso_value), inline=True)

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

        if extract_embed_field(embed, "🤝 Binned by:"):
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
        binned_at = discord.utils.utcnow()
        updated_embed = discord.Embed.from_dict(embed.to_dict())
        updated_embed.add_field(
            name="🤝 Binned by:",
            value=f"{interaction.user.mention} at {discord.utils.format_dt(binned_at, 'f')}",
            inline=False
        )

        await interaction.response.edit_message(
            embed=updated_embed,
            view=FlipBinView(self.original_message_id, disabled=True)
        )

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

        thread = interaction.channel

        if isinstance(thread, discord.Thread):
            await thread.send(f"🔒 Deal closed! {interaction.user.mention} binned this one. Thread is now locked.")

            if author and not dm_sent:
                await thread.send(f"{author.mention} has DMs closed — reach out to {interaction.user.mention} directly!")

            try:
                await thread.edit(name=close_thread_title(thread.name), locked=True)
            except discord.HTTPException:
                await thread.send("I could not lock this thread automatically. A mod may need to lock it.")


class FlipBinView(discord.ui.View):
    def __init__(self, original_message_id: int, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.add_item(FlipBinButton(original_message_id, disabled=disabled))


intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    bot.add_dynamic_items(BOTYScoreButton)
    bot.add_dynamic_items(BattleVoteButton)
    bot.add_dynamic_items(FlipBinButton)
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


@bot.tree.command(name="flip", description="Post a bottle flip with a BIN button and discussion thread.")
@app_commands.describe(
    ft="Bottle or bottles being offered, e.g. RR15 + Weller 12",
    ft_value="Estimated FT value",
    zip_code="Your 5-digit US ZIP for City, State display",
    iso="Optional ISO bottle or bottles. Leave blank for tacos only.",
    iso_value="Optional ISO value",
    ft_kicker="Whether your FT side includes a kicker",
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

    ft, ft_kicker = strip_kicker_text(ft, ft_kicker)
    ft = canonical_bottle_list(ft)
    iso, iso_value, iso_kicker = parse_iso_details(iso, iso_value, iso_kicker)

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

    seller_kicker = bool(ft_kicker or iso_kicker)
    kicker_label = seller_kicker_label(ft_value, iso_value) if seller_kicker else None
    ft_target = f"{ft} + {kicker_label}" if kicker_label else ft
    target = iso_thread_target(iso, iso_value)
    thread_name = thread_safe_name(f"🥃 FT: {ft_target} ↔ {target}")
    seller_name = interaction.user.display_name
    announcement_ft = ft_target

    if iso:
        announcement_description = (
            f"{seller_name} is offering **{announcement_ft}** — ISO **{iso}**. "
            "Drop a ✅ or hit BIN below 👇"
        )
    else:
        announcement_description = (
            f"{seller_name} is offering **{announcement_ft}** — looking for tacos only. "
            "Drop a ✅ or hit BIN below 👇"
        )

    announcement = discord.Embed(
        title=f"🥃 FT: {ft}",
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
        ft_kicker=ft_kicker,
        iso_kicker=iso_kicker,
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
