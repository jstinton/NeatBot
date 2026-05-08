import asyncio
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


DB_PATH = Path(__file__).parent / "trips.db"
JUICED_IMAGE_PATH = Path(__file__).parent / "assets" / "nerd.jpg"
DEFAULT_MOD_CHANNEL_ID = os.getenv("JUICETRIP_MOD_CHANNEL_ID")
STATUS_LABELS = {
    "confirmed": "✅ Confirmed",
    "maybe": "🤔 Maybe",
    "daytrip": "🏨 Day Trip",
    "out": "❌ Can't Make It",
    "waitlist": "⏳ Waitlist",
}
BUTTONS = [
    ("confirmed", "I'm In", "🥃", discord.ButtonStyle.success),
    ("maybe", "Maybe", "🤔", discord.ButtonStyle.secondary),
    ("daytrip", "Day Trip Only", "🏨", discord.ButtonStyle.primary),
    ("out", "Can't Make It", "💧", discord.ButtonStyle.danger),
]
BOURBON_EASTER_EGGS = [
    "Hydrate like a pro. Sip like a legend.",
    "No unopened bottle left behind.",
    "The itinerary has legs, finish, and questionable restraint.",
    "Allocated bottles are not guaranteed, but questionable decisions are possible.",
    "Remember: shared pours count as group bonding.",
]


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_deadline(deadline: Optional[str]):
    if not deadline:
        return None

    cleaned = deadline.strip().replace(",", "")
    cleaned = cleaned.replace("Sept ", "Sep ").replace("sept ", "sep ")
    now = datetime.now()
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%b %d %Y",
        "%B %d %Y",
        "%b %d",
        "%B %d",
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(cleaned, fmt)

            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=now.year)

                if parsed.date() < now.date():
                    parsed = parsed.replace(year=now.year + 1)

            return datetime.combine(parsed.date(), time.max).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


def deadline_is_past(deadline: Optional[str]):
    parsed = parse_deadline(deadline)
    return bool(parsed and datetime.now(timezone.utc) > parsed)


def progress_bar(filled: int, capacity: int, width: int = 10):
    if capacity <= 0:
        return "░" * width

    filled_blocks = min(width, round((filled / capacity) * width))
    return "█" * filled_blocks + "░" * (width - filled_blocks)


def bourbon_easter_egg(trip_id: int):
    return BOURBON_EASTER_EGGS[trip_id % len(BOURBON_EASTER_EGGS)]


def truncate_names(names: list[str], limit: int = 900):
    if not names:
        return "None yet"

    value = "\n".join(f"• {name}" for name in names)

    if len(value) <= limit:
        return value

    remaining = len(names)
    lines = []

    for name in names:
        candidate = "\n".join(lines + [f"• {name}"])

        if len(candidate) > limit - 40:
            break

        lines.append(f"• {name}")
        remaining -= 1

    lines.append(f"…and {remaining} more")
    return "\n".join(lines)


def answer_or_dash(value: Optional[str]):
    if value is None:
        return "—"

    value = str(value).strip()
    return value or "—"


def rsvp_detail_rows(rows, limit: int = 950):
    if not rows:
        return "None yet"

    lines = []

    for row in rows:
        details = [
            f"nights: {answer_or_dash(row['nights'])}",
            f"max/night: {answer_or_dash(row['max_cost_per_night'])}",
            f"share bed: {answer_or_dash(row['share_bed'])}",
        ]

        notes = answer_or_dash(row["notes"])

        if notes != "—":
            details.append(f"notes: {notes}")

        lines.append(f"• {row['username']} — {' · '.join(details)}")

    value = "\n".join(lines)

    if len(value) <= limit:
        return value

    clipped = []
    remaining = len(lines)

    for line in lines:
        candidate = "\n".join(clipped + [line])

        if len(candidate) > limit - 40:
            break

        clipped.append(line)
        remaining -= 1

    clipped.append(f"…and {remaining} more")
    return "\n".join(clipped)


class GroupTripView(discord.ui.View):
    def __init__(self, cog: "GroupTripCog", trip_id: int, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        self.trip_id = trip_id

        for status, label, emoji, style in BUTTONS:
            self.add_item(GroupTripButton(cog, trip_id, status, label, emoji, style, disabled=disabled))


class GroupTripButton(discord.ui.Button):
    def __init__(
        self,
        cog: "GroupTripCog",
        trip_id: int,
        status: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle,
        *,
        disabled: bool = False,
    ):
        super().__init__(
            label=label,
            emoji=emoji,
            style=style,
            custom_id=f"juicetrip:{trip_id}:{status}",
            disabled=disabled,
        )
        self.cog = cog
        self.trip_id = trip_id
        self.status = status

    async def callback(self, interaction: discord.Interaction):
        await self.cog.handle_rsvp(interaction, self.trip_id, self.status)


class GroupTripRSVPModal(discord.ui.Modal):
    def __init__(self, cog: "GroupTripCog", trip_id: int, requested_status: str, source_message: discord.Message):
        label = STATUS_LABELS[requested_status].split(" ", 1)[1]
        super().__init__(title=f"JuiceTrip RSVP: {label}")
        self.cog = cog
        self.trip_id = trip_id
        self.requested_status = requested_status
        self.source_message = source_message
        self.nights = discord.ui.TextInput(
            label="How many nights would you stay?",
            placeholder="Example: 2, 3, day trip only, not sure",
            required=False,
            max_length=40,
        )
        self.max_cost_per_night = discord.ui.TextInput(
            label="Max cost per night?",
            placeholder="Example: 150, 200, flexible",
            required=False,
            max_length=60,
        )
        self.share_bed = discord.ui.TextInput(
            label="Comfortable sharing a bed?",
            placeholder="Yes / No / Only with someone I know",
            required=False,
            max_length=80,
        )
        self.notes = discord.ui.TextInput(
            label="Anything else mods should know?",
            placeholder="Tours you want, arrival timing, roommate preferences...",
            required=False,
            max_length=300,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.nights)
        self.add_item(self.max_cost_per_night)
        self.add_item(self.share_bed)
        self.add_item(self.notes)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.record_rsvp_from_form(
            interaction,
            self.trip_id,
            self.requested_status,
            source_message=self.source_message,
            nights=self.nights.value.strip() or None,
            max_cost_per_night=self.max_cost_per_night.value.strip() or None,
            share_bed=self.share_bed.value.strip() or None,
            notes=self.notes.value.strip() or None,
        )


class FollowUpMaybeView(discord.ui.View):
    def __init__(self, cog: "GroupTripCog", trip_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.trip_id = trip_id

    @discord.ui.button(label="DM Maybes", emoji="📬", style=discord.ButtonStyle.primary)
    async def dm_maybes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Only mods can DM maybes.", ephemeral=True)
            return

        trip = await self.cog.active_trip_for_channel(interaction.channel_id)

        if not trip or trip["trip_id"] != self.trip_id:
            await interaction.response.send_message("I couldn't find that active trip anymore.", ephemeral=True)
            return

        maybes = await self.cog.rsvps_for_status(self.trip_id, "maybe")
        sent = 0
        failed = 0

        for maybe in maybes:
            try:
                user = interaction.client.get_user(maybe["user_id"]) or await interaction.client.fetch_user(maybe["user_id"])
                await user.send(
                    f"Quick JuiceTrip barrel check: are you in for **{trip['destination']}** ({trip['dates']})? "
                    "Please update your RSVP when you know. The maybes are still nosing the glass."
                )
                sent += 1
            except discord.HTTPException:
                failed += 1

        await interaction.response.send_message(
            f"Follow-up DMs sent: {sent}. Failed: {failed}.",
            ephemeral=True,
        )


class GroupTripCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = DB_PATH
        self.deadline_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        await self.init_db()
        await self.register_active_views()
        self.deadline_task = asyncio.create_task(self.deadline_loop())

    async def cog_unload(self):
        if self.deadline_task:
            self.deadline_task.cancel()

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS trips (
                    trip_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    destination TEXT NOT NULL,
                    dates TEXT NOT NULL,
                    airbnb_capacity INTEGER NOT NULL,
                    estimated_cost TEXT NOT NULL,
                    tours TEXT,
                    deadline TEXT,
                    mod_channel_id INTEGER,
                    mod_message_id INTEGER,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS rsvps (
                    trip_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    status TEXT NOT NULL,
                    nights TEXT,
                    max_cost_per_night TEXT,
                    share_bed TEXT,
                    notes TEXT,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (trip_id, user_id)
                )
                """
            )
            await self.migrate_trip_columns(db)
            await self.migrate_rsvp_columns(db)
            await db.commit()

    async def migrate_trip_columns(self, db):
        async with db.execute("PRAGMA table_info(trips)") as cursor:
            existing_columns = {row[1] for row in await cursor.fetchall()}

        migrations = {
            "mod_channel_id": "ALTER TABLE trips ADD COLUMN mod_channel_id INTEGER",
            "mod_message_id": "ALTER TABLE trips ADD COLUMN mod_message_id INTEGER",
        }

        for column, statement in migrations.items():
            if column not in existing_columns:
                await db.execute(statement)

    async def migrate_rsvp_columns(self, db):
        async with db.execute("PRAGMA table_info(rsvps)") as cursor:
            existing_columns = {row[1] for row in await cursor.fetchall()}

        migrations = {
            "nights": "ALTER TABLE rsvps ADD COLUMN nights TEXT",
            "max_cost_per_night": "ALTER TABLE rsvps ADD COLUMN max_cost_per_night TEXT",
            "share_bed": "ALTER TABLE rsvps ADD COLUMN share_bed TEXT",
            "notes": "ALTER TABLE rsvps ADD COLUMN notes TEXT",
        }

        for column, statement in migrations.items():
            if column not in existing_columns:
                await db.execute(statement)

    async def register_active_views(self):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trips WHERE active = 1") as cursor:
                trips = await cursor.fetchall()

        for trip in trips:
            disabled = deadline_is_past(trip["deadline"])
            self.bot.add_view(GroupTripView(self, trip["trip_id"], disabled=disabled), message_id=trip["message_id"])

    async def deadline_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            try:
                await self.disable_expired_trips()
            except Exception as error:
                print(f"juicetrip deadline loop failed: {error}")

            await asyncio.sleep(60)

    async def disable_expired_trips(self):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trips WHERE active = 1 AND deadline IS NOT NULL") as cursor:
                trips = await cursor.fetchall()

        for trip in trips:
            if not deadline_is_past(trip["deadline"]):
                continue

            channel = self.bot.get_channel(trip["channel_id"])

            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(trip["channel_id"])
                except discord.HTTPException:
                    continue

            try:
                message = await channel.fetch_message(trip["message_id"])
                embed = await self.trip_embed(trip["trip_id"])
                await message.edit(embed=embed, view=GroupTripView(self, trip["trip_id"], disabled=True))
            except discord.HTTPException:
                continue

    async def active_trip_for_channel(self, channel_id: Optional[int]):
        if not channel_id:
            return None

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trips WHERE channel_id = ? AND active = 1 ORDER BY trip_id DESC LIMIT 1",
                (channel_id,),
            ) as cursor:
                return await cursor.fetchone()

    async def trip_by_id(self, trip_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trips WHERE trip_id = ?", (trip_id,)) as cursor:
                return await cursor.fetchone()

    async def rsvps_by_status(self, trip_id: int):
        grouped = {status: [] for status in STATUS_LABELS}

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM rsvps WHERE trip_id = ? ORDER BY timestamp ASC",
                (trip_id,),
            ) as cursor:
                rows = await cursor.fetchall()

        for row in rows:
            grouped.setdefault(row["status"], []).append(row)

        return grouped

    async def rsvps_for_status(self, trip_id: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM rsvps WHERE trip_id = ? AND status = ? ORDER BY timestamp ASC",
                (trip_id, status),
            ) as cursor:
                return await cursor.fetchall()

    async def confirmed_count(self, trip_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM rsvps WHERE trip_id = ? AND status = 'confirmed'",
                (trip_id,),
            ) as cursor:
                row = await cursor.fetchone()

        return int(row[0])

    async def resolve_mod_channel(self, channel: Optional[discord.abc.GuildChannel]):
        if channel and hasattr(channel, "send"):
            return channel

        if not DEFAULT_MOD_CHANNEL_ID:
            return None

        try:
            channel_id = int(DEFAULT_MOD_CHANNEL_ID)
        except ValueError:
            return None

        return self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)

    async def set_mod_summary_target(self, trip_id: int, channel_id: int, message_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trips SET mod_channel_id = ?, mod_message_id = ? WHERE trip_id = ?",
                (channel_id, message_id, trip_id),
            )
            await db.commit()

    async def trip_status_embed(self, trip_id: int):
        trip = await self.trip_by_id(trip_id)
        grouped = await self.rsvps_by_status(trip_id)
        confirmed = grouped.get("confirmed", [])
        capacity = trip["airbnb_capacity"]
        remaining = max(0, capacity - len(confirmed))
        fill_rate = f"{len(confirmed)}/{capacity}"
        embed = discord.Embed(
            title=f"JuiceTrip Mod Summary: {trip['destination']}",
            description=(
                f"**Dates:** {trip['dates']}\n"
                f"**Airbnb Fill:** {fill_rate} spots filled · **{remaining}** remaining\n"
                f"**Public Channel:** <#{trip['channel_id']}>"
            ),
            color=discord.Color.blurple(),
        )

        for status in ("confirmed", "maybe", "daytrip", "out", "waitlist"):
            rows = grouped.get(status, [])
            embed.add_field(
                name=f"{STATUS_LABELS[status]} ({len(rows)})",
                value=rsvp_detail_rows(rows, limit=950),
                inline=False,
            )

        maybes = grouped.get("maybe", [])
        embed.add_field(
            name="Needs Follow-Up",
            value=truncate_names([row["username"] for row in maybes], limit=950),
            inline=False,
        )
        embed.set_footer(text="Live JuiceTrip planning summary. Keep this channel mod-only.")
        return embed

    async def sync_mod_summary(self, trip_id: int):
        trip = await self.trip_by_id(trip_id)

        if not trip or not trip["mod_channel_id"]:
            return None

        try:
            channel = self.bot.get_channel(trip["mod_channel_id"]) or await self.bot.fetch_channel(trip["mod_channel_id"])

            if not hasattr(channel, "send"):
                return None

            embed = await self.trip_status_embed(trip_id)

            if trip["mod_message_id"]:
                try:
                    message = await channel.fetch_message(trip["mod_message_id"])
                    await message.edit(embed=embed)
                    return message
                except discord.HTTPException:
                    pass

            message = await channel.send(embed=embed)
            await self.set_mod_summary_target(trip_id, channel.id, message.id)
            return message
        except discord.HTTPException:
            return None

    async def send_juiced_dm(self, user: discord.abc.User, label: str, destination: str, dates: str):
        content = (
            "Thanks for the input, YOUVE BEEN JUICED\n\n"
            f"You're marked as {label} for {destination} ({dates})!"
        )

        if JUICED_IMAGE_PATH.exists():
            await user.send(
                content,
                file=discord.File(JUICED_IMAGE_PATH, filename="youve-been-juiced.jpg"),
            )
            return

        await user.send(content)

    async def set_rsvp(
        self,
        trip_id: int,
        user: discord.abc.User,
        status: str,
        *,
        nights: Optional[str],
        max_cost_per_night: Optional[str],
        share_bed: Optional[str],
        notes: Optional[str],
    ):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO rsvps (
                    trip_id, user_id, username, status, nights,
                    max_cost_per_night, share_bed, notes, timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trip_id, user_id) DO UPDATE SET
                    username = excluded.username,
                    status = excluded.status,
                    nights = excluded.nights,
                    max_cost_per_night = excluded.max_cost_per_night,
                    share_bed = excluded.share_bed,
                    notes = excluded.notes,
                    timestamp = excluded.timestamp
                """,
                (
                    trip_id,
                    user.id,
                    user.display_name,
                    status,
                    nights,
                    max_cost_per_night,
                    share_bed,
                    notes,
                    utcnow_iso(),
                ),
            )
            await db.commit()

    async def trip_embed(self, trip_id: int):
        trip = await self.trip_by_id(trip_id)
        grouped = await self.rsvps_by_status(trip_id)
        confirmed = grouped.get("confirmed", [])
        capacity = trip["airbnb_capacity"]
        filled = min(len(confirmed), capacity)
        remaining = max(0, capacity - len(confirmed))

        embed = discord.Embed(
            title=f"🥃 JuiceTrip: {trip['destination']}",
            description=(
                f"**Dates:** {trip['dates']}\n"
                f"**Estimated Cost:** {trip['estimated_cost']}\n"
                f"**Tours / Stops:** {trip['tours'] or 'TBD'}\n"
                f"*{bourbon_easter_egg(trip_id)}*"
            ),
            color=discord.Color.from_str("#C9973A"),
        )
        embed.add_field(
            name=f"🥃 Confirmed · 🛏️ {filled} of {capacity} barrel bunk spots filled",
            value=(
                f"`{progress_bar(filled, capacity)}`\n"
                f"Remaining Airbnb spots: **{remaining}**\n"
                f"{truncate_names([row['username'] for row in confirmed])}"
            ),
            inline=False,
        )
        embed.add_field(
            name="🤔 Maybe",
            value=truncate_names([row["username"] for row in grouped.get("maybe", [])]),
            inline=False,
        )
        embed.add_field(
            name="🏨 Day Trip",
            value=truncate_names([row["username"] for row in grouped.get("daytrip", [])]),
            inline=False,
        )
        embed.add_field(
            name="❌ Can't Make It",
            value=truncate_names([row["username"] for row in grouped.get("out", [])]),
            inline=False,
        )

        waitlist = grouped.get("waitlist", [])

        if waitlist:
            embed.add_field(
                name="⏳ Waitlist",
                value=truncate_names([row["username"] for row in waitlist]),
                inline=False,
            )

        footer = "RSVP barrel is closed." if deadline_is_past(trip["deadline"]) else "Pick your pour below to RSVP."

        if trip["deadline"]:
            footer = f"{footer} RSVP deadline: {trip['deadline']}"

        embed.set_footer(text=f"{footer} · NeatBot JuiceTrip Department")
        return embed

    async def refresh_trip_message(self, trip_id: int, source_message: Optional[discord.Message] = None):
        trip = await self.trip_by_id(trip_id)

        if not trip:
            return

        embed = await self.trip_embed(trip_id)
        disabled = deadline_is_past(trip["deadline"])
        view = GroupTripView(self, trip_id, disabled=disabled)

        if source_message:
            await source_message.edit(embed=embed, view=view)
            return

        channel = self.bot.get_channel(trip["channel_id"]) or await self.bot.fetch_channel(trip["channel_id"])
        message = await channel.fetch_message(trip["message_id"])
        await message.edit(embed=embed, view=view)

    async def handle_rsvp(self, interaction: discord.Interaction, trip_id: int, requested_status: str):
        trip = await self.trip_by_id(trip_id)

        if not trip or not trip["active"]:
            await interaction.response.send_message("That trip is no longer active.", ephemeral=True)
            return

        if deadline_is_past(trip["deadline"]):
            await interaction.response.send_message("RSVPs are closed for this trip.", ephemeral=True)
            await self.refresh_trip_message(trip_id, interaction.message)
            return

        if not interaction.message:
            await interaction.response.send_message("I can’t open the RSVP form from here. Try the button again.", ephemeral=True)
            return

        await interaction.response.send_modal(
            GroupTripRSVPModal(self, trip_id, requested_status, interaction.message)
        )

    async def record_rsvp_from_form(
        self,
        interaction: discord.Interaction,
        trip_id: int,
        requested_status: str,
        *,
        source_message: discord.Message,
        nights: Optional[str],
        max_cost_per_night: Optional[str],
        share_bed: Optional[str],
        notes: Optional[str],
    ):
        trip = await self.trip_by_id(trip_id)

        if not trip or not trip["active"]:
            await interaction.response.send_message("That trip is no longer active.", ephemeral=True)
            return

        if deadline_is_past(trip["deadline"]):
            await interaction.response.send_message("RSVPs are closed for this trip.", ephemeral=True)
            await self.refresh_trip_message(trip_id, source_message)
            return

        final_status = requested_status

        if requested_status == "confirmed":
            confirmed_count = await self.confirmed_count(trip_id)

            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT status FROM rsvps WHERE trip_id = ? AND user_id = ?",
                    (trip_id, interaction.user.id),
                ) as cursor:
                    existing = await cursor.fetchone()

            already_confirmed = bool(existing and existing[0] == "confirmed")

            if confirmed_count >= trip["airbnb_capacity"] and not already_confirmed:
                final_status = "waitlist"

        await self.set_rsvp(
            trip_id,
            interaction.user,
            final_status,
            nights=nights,
            max_cost_per_night=max_cost_per_night,
            share_bed=share_bed,
            notes=notes,
        )
        await self.refresh_trip_message(trip_id, source_message)
        await self.sync_mod_summary(trip_id)

        label = STATUS_LABELS[final_status]
        await interaction.response.send_message(
            f"You're marked as **{label}** for **{trip['destination']}**. The barrel bunk details are saved for mods.",
            ephemeral=True
        )

        try:
            await self.send_juiced_dm(interaction.user, label, trip["destination"], trip["dates"])
        except discord.HTTPException:
            pass

    @app_commands.command(name="juicetrip", description="Create an interactive bourbon trip RSVP post.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        destination="Name/location of the trip",
        dates='Date range, e.g. "Oct 10-12, 2025"',
        airbnb_capacity="Max Airbnb headcount",
        estimated_cost='Estimated per-person cost, e.g. "$150-$200"',
        tours="Comma-separated tour/distillery stops",
        deadline='RSVP deadline, e.g. "Sept 30"',
        mod_channel="Optional mod-only channel for the live planning summary",
    )
    async def juicetrip(
        self,
        interaction: discord.Interaction,
        destination: str,
        dates: str,
        airbnb_capacity: int,
        estimated_cost: str,
        tours: Optional[str] = None,
        deadline: Optional[str] = None,
        mod_channel: Optional[discord.TextChannel] = None,
    ):
        if airbnb_capacity < 1:
            await interaction.response.send_message("Airbnb capacity must be at least 1.", ephemeral=True)
            return

        await interaction.response.defer()
        resolved_mod_channel = await self.resolve_mod_channel(mod_channel)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trips SET active = 0 WHERE channel_id = ? AND active = 1",
                (interaction.channel_id,),
            )
            cursor = await db.execute(
                """
                INSERT INTO trips (
                    channel_id, message_id, destination, dates, airbnb_capacity,
                    estimated_cost, tours, deadline, mod_channel_id, active
                )
                VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    interaction.channel_id,
                    destination,
                    dates,
                    airbnb_capacity,
                    estimated_cost,
                    tours,
                    deadline,
                    resolved_mod_channel.id if resolved_mod_channel else None,
                ),
            )
            trip_id = cursor.lastrowid
            await db.commit()

        embed = await self.trip_embed(trip_id)
        view = GroupTripView(self, trip_id, disabled=deadline_is_past(deadline))
        message = await interaction.followup.send(embed=embed, view=view, wait=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE trips SET message_id = ? WHERE trip_id = ?",
                (message.id, trip_id),
            )
            await db.commit()

        mod_message = await self.sync_mod_summary(trip_id)

        if resolved_mod_channel and not mod_message:
            await interaction.followup.send(
                "JuiceTrip was posted, but I could not post the mod summary. Check my permissions in the mod channel.",
                ephemeral=True,
            )

    @juicetrip.error
    async def juicetrip_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Only mods can create JuiceTrip posts.", ephemeral=True)
            return

        raise error

    @app_commands.command(name="tripstatus", description="Show the active JuiceTrip RSVP tally.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def tripstatus(self, interaction: discord.Interaction):
        trip = await self.active_trip_for_channel(interaction.channel_id)

        if not trip:
            await interaction.response.send_message("No active trip found in this channel.", ephemeral=True)
            return

        grouped = await self.rsvps_by_status(trip["trip_id"])
        maybes = grouped.get("maybe", [])
        view = FollowUpMaybeView(self, trip["trip_id"]) if maybes else None
        embed = await self.trip_status_embed(trip["trip_id"])
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @tripstatus.error
    async def tripstatus_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Only mods can view trip status.", ephemeral=True)
            return

        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(GroupTripCog(bot))
