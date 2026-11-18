import asyncio
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands


DB_PATH = Path(
    os.getenv(
        "REFERRAL_DB_PATH",
        "/data/referrals.db" if Path("/data").exists() else Path(__file__).parent / "referrals.db"
    )
)
# Default: the contest closes at the end of Dec 1, Central time (CST is UTC-6 in December).
CONTEST_END_RAW = os.getenv("REFERRAL_CONTEST_END", "2026-12-01T23:59:59-06:00")
CONTEST_START_RAW = os.getenv("REFERRAL_CONTEST_START", "")


def channel_id_setting(name: str):
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw.isdigit() else None


ANNOUNCE_CHANNEL_ID = channel_id_setting("REFERRAL_ANNOUNCE_CHANNEL_ID")
LOG_CHANNEL_ID = channel_id_setting("REFERRAL_LOG_CHANNEL_ID")
WELCOME_CHANNEL_ID = channel_id_setting("REFERRAL_WELCOME_CHANNEL_ID")
ROYAL_PURPLE = discord.Color.from_str("#6B2D8F")
ROYAL_DECREES = [
    "Hear ye, hear ye! By decree of His Majesty Jon, {member} is hereby admitted to The Royal House of Juice, "
    "on the sworn word of {inviter}. Pour them something worthy.",
    "Let the trumpets sound! {inviter} has vouched for {member}, and the gates of The Royal House of Juice "
    "swing open. His Majesty Jon has given his blessing. Few are chosen. Fewer still are allocated.",
    "Be it known throughout the realm of Jon and the Juice: {member} now walks among the elite, sponsored by "
    "{inviter}. May their pours be neat and their shelves never dusty. Long live His Majesty Jon!",
    "The Royal Council has convened and His Majesty Jon has spoken. On the recommendation of {inviter}, "
    "{member} is hereby inducted into The Royal House of Juice, this secret and elite club. Kneel, and rise a Sipper.",
]
ROYAL_DECREES_NO_INVITER = [
    "Hear ye, hear ye! {member} has entered The Royal House of Juice, this secret and elite club. "
    "Who vouched for them? That remains a mystery known only to His Majesty Jon.",
    "Let the trumpets sound! {member} has slipped past the palace guards and into the court of Jon and the Juice. "
    "Their sponsor wishes to remain anonymous. His Majesty Jon will allow it.",
]
ROYAL_RETURNS = [
    "Hear ye, hear ye! {member} returns to The Royal House of Juice. "
    "By the grace of His Majesty Jon, the realm welcomes them home.",
]
ANNOUNCE_CHECK_SECONDS = 300
GOLD = discord.Color.from_str("#C9973A")
PLACES = ["🥇 1st Place", "🥈 2nd Place", "🥉 3rd Place"]


def parse_timestamp(raw: str):
    parsed = datetime.fromisoformat(raw.strip())

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


CONTEST_END = parse_timestamp(CONTEST_END_RAW)
CONTEST_START = parse_timestamp(CONTEST_START_RAW) if CONTEST_START_RAW.strip() else None


def utcnow():
    return datetime.now(timezone.utc)


def to_db_time(dt: datetime):
    # One fixed format so timestamps compare correctly as strings in SQLite.
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def contest_over(now: Optional[datetime] = None):
    return (now or utcnow()) > CONTEST_END


def contest_end_text():
    stamp = int(CONTEST_END.timestamp())
    return f"<t:{stamp}:F> (<t:{stamp}:R>)"


class ReferralCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = DB_PATH
        # guild_id -> {invite code: (uses, inviter_id, max_uses)}
        self.invite_cache: dict[int, Optional[dict[str, tuple[int, Optional[int], int]]]] = {}
        self.invite_locks: dict[int, asyncio.Lock] = {}
        self.warned_no_channel: set[int] = set()
        self.announce_task: Optional[asyncio.Task] = None

    async def cog_load(self):
        await self.init_db()
        self.announce_task = asyncio.create_task(self.announce_loop())

    async def cog_unload(self):
        if self.announce_task:
            self.announce_task.cancel()

    async def init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if not str(self.db_path).startswith("/data"):
            print(
                f"WARNING: referral DB is at {self.db_path}, which is not a mounted volume. "
                "Referral history will be erased on the next deploy or restart."
            )

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS referrals (
                    guild_id TEXT NOT NULL,
                    member_id TEXT NOT NULL,
                    member_name TEXT NOT NULL,
                    inviter_id TEXT,
                    invite_code TEXT,
                    source TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    left_at TEXT,
                    PRIMARY KEY (guild_id, member_id)
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS referral_announcements (
                    guild_id TEXT NOT NULL,
                    contest_end TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    announced_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, contest_end)
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_referrals_guild_inviter ON referrals (guild_id, inviter_id)"
            )
            await db.commit()

    # ---------- invite tracking ----------

    def guild_lock(self, guild_id: int):
        if guild_id not in self.invite_locks:
            self.invite_locks[guild_id] = asyncio.Lock()

        return self.invite_locks[guild_id]

    async def snapshot_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            print(
                f"WARNING: NeatBot needs the Manage Server permission in {guild.name} "
                "to see which invite a new member used. Referrals there must be set with /referral-set."
            )
            return None
        except discord.HTTPException as exc:
            print(f"Could not read invites for {guild.name}: {exc}")
            return None

        return {
            invite.code: (invite.uses or 0, invite.inviter.id if invite.inviter else None, invite.max_uses or 0)
            for invite in invites
        }

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            async with self.guild_lock(guild.id):
                self.invite_cache[guild.id] = await self.snapshot_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        async with self.guild_lock(guild.id):
            self.invite_cache[guild.id] = await self.snapshot_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if not invite.guild:
            return

        cache = self.invite_cache.get(invite.guild.id)

        if cache is not None:
            cache[invite.code] = (
                invite.uses or 0,
                invite.inviter.id if invite.inviter else None,
                invite.max_uses or 0,
            )

    # Deleted invites are deliberately left in the cache: when a limited-use invite
    # hits its cap Discord deletes it, and the cached entry is how that join gets credited.

    def find_used_invite(self, before, after):
        used = [
            code for code, (uses, _, _) in after.items()
            if uses > before.get(code, (0, None, 0))[0]
        ]

        if len(used) == 1:
            return used[0], after[used[0]][1]

        if not used:
            consumed = [
                code for code, (uses, _, max_uses) in before.items()
                if code not in after and max_uses and uses + 1 >= max_uses
            ]

            if len(consumed) == 1:
                return consumed[0], before[consumed[0]][1]

        return None, None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        guild = member.guild

        async with self.guild_lock(guild.id):
            before = self.invite_cache.get(guild.id)
            after = await self.snapshot_invites(guild)
            self.invite_cache[guild.id] = after

        code, inviter_id = (None, None)

        if before is not None and after is not None:
            code, inviter_id = self.find_used_invite(before, after)

        if inviter_id == member.id:
            inviter_id = None

        inviter = guild.get_member(inviter_id) if inviter_id else None

        if inviter and inviter.bot:
            inviter_id, inviter = None, None

        existing = await self.get_referral(guild.id, member.id)

        if existing:
            # Rejoining never earns anyone new credit; the original referral stands.
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE referrals SET left_at = NULL, member_name = ? WHERE guild_id = ? AND member_id = ?",
                    (str(member), str(guild.id), str(member.id)),
                )
                await db.commit()

            await self.log(
                guild,
                f"↩️ {member.mention} rejoined. Original referral kept"
                + (f" (<@{existing['inviter_id']}>)." if existing["inviter_id"] else " (no inviter on record)."),
            )
            await self.royal_announcement(member, None, returning=True)
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO referrals (
                    guild_id, member_id, member_name, inviter_id, invite_code, source, joined_at, left_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    str(guild.id),
                    str(member.id),
                    str(member),
                    str(inviter_id) if inviter_id else None,
                    code,
                    "invite" if inviter_id else "unknown",
                    to_db_time(member.joined_at or utcnow()),
                ),
            )
            await db.commit()

        if inviter_id:
            await self.log(guild, f"🤝 {member.mention} joined, invited by <@{inviter_id}> (invite `{code}`).")
        else:
            await self.log(
                guild,
                f"❓ {member.mention} joined, but I couldn't tell who invited them. "
                f"A mod can credit someone with `/referral-set`.",
            )

        await self.royal_announcement(member, inviter_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE referrals SET left_at = ? WHERE guild_id = ? AND member_id = ? AND left_at IS NULL",
                (to_db_time(utcnow()), str(member.guild.id), str(member.id)),
            )
            await db.commit()

    async def royal_announcement(self, member: discord.Member, inviter_id: Optional[int], returning: bool = False):
        guild = member.guild
        channel = guild.get_channel(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
        channel = channel or guild.system_channel

        if not channel:
            return

        if returning:
            template = random.choice(ROYAL_RETURNS)
        elif inviter_id:
            template = random.choice(ROYAL_DECREES)
        else:
            template = random.choice(ROYAL_DECREES_NO_INVITER)

        embed = discord.Embed(
            title="👑 A Royal Announcement 👑",
            description=template.format(member=member.mention, inviter=f"<@{inviter_id}>" if inviter_id else ""),
            color=ROYAL_PURPLE,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Member #{guild.member_count} of The Royal House of Juice" if guild.member_count else "Long live His Majesty Jon")

        try:
            # Plain-text mentions so both the newcomer and their sponsor get pinged.
            ping = member.mention + (f" <@{inviter_id}>" if inviter_id else "")
            await channel.send(
                content=ping,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.HTTPException:
            pass

    async def log(self, guild: discord.Guild, text: str):
        if not LOG_CHANNEL_ID:
            return

        channel = guild.get_channel(LOG_CHANNEL_ID)

        if not channel:
            return

        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    # ---------- data ----------

    async def get_referral(self, guild_id: int, member_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM referrals WHERE guild_id = ? AND member_id = ?",
                (str(guild_id), str(member_id)),
            )
            return await cursor.fetchone()

    async def standings(self, guild_id: int):
        """Inviters ranked by referrals that joined in the contest window and were
        still in the server when it closed (or are still here, while it's running).
        Ties go to whoever reached their total first."""
        params = [str(guild_id), to_db_time(CONTEST_END), to_db_time(CONTEST_END)]
        start_clause = ""

        if CONTEST_START:
            start_clause = "AND joined_at >= ?"
            params.append(to_db_time(CONTEST_START))

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT inviter_id, COUNT(*) AS total, MAX(joined_at) AS reached_at
                FROM referrals
                WHERE guild_id = ?
                  AND inviter_id IS NOT NULL
                  AND joined_at <= ?
                  AND (left_at IS NULL OR left_at > ?)
                  {start_clause}
                GROUP BY inviter_id
                ORDER BY total DESC, reached_at ASC
                """,
                params,
            )
            return await cursor.fetchall()

    async def invited_by(self, guild_id: int, inviter_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT member_id, member_name, joined_at, left_at
                FROM referrals
                WHERE guild_id = ? AND inviter_id = ?
                ORDER BY joined_at DESC
                """,
                (str(guild_id), str(inviter_id)),
            )
            return await cursor.fetchall()

    # ---------- embeds ----------

    async def leaderboard_embed(self, guild: discord.Guild):
        rows = await self.standings(guild.id)
        over = contest_over()
        embed = discord.Embed(
            title="🤝 Referral Contest — Final Results" if over else "🤝 Referral Contest Leaderboard",
            color=GOLD,
        )
        embed.description = (
            f"Closed {contest_end_text()}." if over else f"Ends {contest_end_text()}."
        )

        if not rows:
            embed.add_field(name="No referrals yet", value="Invite a friend to get on the board.", inline=False)
        else:
            lines = []

            for index, row in enumerate(rows[:10]):
                place = ["🥇", "🥈", "🥉"][index] if index < 3 else f"`#{index + 1}`"
                noun = "referral" if row["total"] == 1 else "referrals"
                lines.append(f"{place} <@{row['inviter_id']}> — **{row['total']}** {noun}")

            embed.add_field(name="Standings", value="\n".join(lines), inline=False)

        embed.set_footer(text="Counts members who joined through your invite and stayed. Ties go to whoever got there first.")
        return embed

    async def winners_embed(self, guild: discord.Guild):
        rows = await self.standings(guild.id)
        over = contest_over()
        embed = discord.Embed(
            title="🏆 Referral Contest Winners" if over else "🏆 Referral Contest — Current Top 3",
            description=(
                f"The contest closed {contest_end_text()}. Thanks to everyone who brought in new members!"
                if over
                else f"Not final yet: the contest ends {contest_end_text()}."
            ),
            color=GOLD,
        )

        for index, label in enumerate(PLACES):
            if index < len(rows):
                row = rows[index]
                noun = "referral" if row["total"] == 1 else "referrals"
                embed.add_field(name=label, value=f"<@{row['inviter_id']}>\n**{row['total']}** {noun}", inline=True)
            else:
                embed.add_field(name=label, value="Nobody", inline=True)

        embed.set_footer(text="Ties go to whoever reached their total first.")
        return embed, rows[:3]

    # ---------- winner announcement ----------

    async def already_announced(self, guild_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM referral_announcements WHERE guild_id = ? AND contest_end = ?",
                (str(guild_id), to_db_time(CONTEST_END)),
            )
            return await cursor.fetchone() is not None

    async def mark_announced(self, guild_id: int, message: discord.Message):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO referral_announcements (
                    guild_id, contest_end, channel_id, message_id, announced_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(guild_id), to_db_time(CONTEST_END), str(message.channel.id), str(message.id), to_db_time(utcnow())),
            )
            await db.commit()

    def announce_channel(self, guild: discord.Guild):
        if ANNOUNCE_CHANNEL_ID:
            channel = guild.get_channel(ANNOUNCE_CHANNEL_ID)

            if channel:
                return channel

        return guild.system_channel

    async def post_winners(self, channel: discord.abc.Messageable, guild: discord.Guild):
        embed, winners = await self.winners_embed(guild)
        content = None

        if contest_over() and winners:
            content = "🎉 Congrats " + ", ".join(f"<@{row['inviter_id']}>" for row in winners) + "!"

        return await channel.send(
            content=content,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    async def announce_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            if contest_over():
                for guild in self.bot.guilds:
                    try:
                        await self.maybe_announce(guild)
                    except Exception as exc:
                        print(f"Referral winner announcement failed for {guild.name}: {exc}")

            await asyncio.sleep(ANNOUNCE_CHECK_SECONDS)

    async def maybe_announce(self, guild: discord.Guild):
        if await self.already_announced(guild.id):
            return

        channel = self.announce_channel(guild)

        if not channel:
            if guild.id not in self.warned_no_channel:
                self.warned_no_channel.add(guild.id)
                print(
                    f"Referral contest is over but {guild.name} has no announcement channel. "
                    "Set REFERRAL_ANNOUNCE_CHANNEL_ID or run /referral-winners in a channel."
                )
            return

        message = await self.post_winners(channel, guild)
        await self.mark_announced(guild.id, message)

    # ---------- commands ----------

    @app_commands.command(name="referrals", description="Show the referral contest leaderboard.")
    async def referrals(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        embed = await self.leaderboard_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="referral-stats", description="See how many people you (or someone else) brought in.")
    @app_commands.describe(member="Optional: check someone else")
    async def referral_stats(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        target = member or interaction.user
        rows = await self.standings(interaction.guild.id)
        rank, total = None, 0

        for index, row in enumerate(rows):
            if row["inviter_id"] == str(target.id):
                rank, total = index + 1, row["total"]
                break

        invited = await self.invited_by(interaction.guild.id, target.id)
        embed = discord.Embed(title="🤝 Referral Stats", description=f"{target.mention}", color=GOLD)
        embed.add_field(name="Contest Referrals", value=str(total), inline=True)
        embed.add_field(name="Rank", value=f"#{rank}" if rank else "Unranked", inline=True)

        if invited:
            lines = [
                f"• <@{row['member_id']}>" + (" (left)" if row["left_at"] else "")
                for row in invited[:15]
            ]

            if len(invited) > 15:
                lines.append(f"…and {len(invited) - 15} more")

            embed.add_field(name="Invited", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Invited", value="Nobody yet", inline=False)

        embed.set_footer(text="Members who left the server don't count toward the contest.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="referral-set", description="Mods: credit a member's referral to the person who invited them.")
    @app_commands.describe(member="The member who joined", inviter="The person who invited them")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def referral_set(self, interaction: discord.Interaction, member: discord.Member, inviter: discord.Member):
        if member.id == inviter.id:
            await interaction.response.send_message("Nobody can refer themselves.", ephemeral=True)
            return

        if member.bot or inviter.bot:
            await interaction.response.send_message("Bots can't take part in referrals.", ephemeral=True)
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO referrals (
                    guild_id, member_id, member_name, inviter_id, invite_code, source, joined_at, left_at
                )
                VALUES (?, ?, ?, ?, NULL, 'manual', ?, NULL)
                ON CONFLICT (guild_id, member_id) DO UPDATE SET
                    inviter_id = excluded.inviter_id,
                    member_name = excluded.member_name,
                    source = 'manual'
                """,
                (
                    str(interaction.guild.id),
                    str(member.id),
                    str(member),
                    str(inviter.id),
                    to_db_time(member.joined_at or utcnow()),
                ),
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ {member.mention} is now credited to {inviter.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="referral-remove", description="Mods: take away the referral credit for a member.")
    @app_commands.describe(member="The member whose referral credit should be removed")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def referral_remove(self, interaction: discord.Interaction, member: discord.Member):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE referrals SET inviter_id = NULL, source = 'removed'
                WHERE guild_id = ? AND member_id = ? AND inviter_id IS NOT NULL
                """,
                (str(interaction.guild.id), str(member.id)),
            )
            await db.commit()
            changed = cursor.rowcount

        if changed:
            await interaction.response.send_message(f"✅ Removed the referral credit for {member.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"{member.mention} has no referral credit to remove.", ephemeral=True)

    @app_commands.command(name="referral-winners", description="Mods: post the referral contest podium in this channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def referral_winners(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.channel:
            await interaction.response.send_message("This command only works in a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        message = await self.post_winners(interaction.channel, interaction.guild)

        if contest_over():
            # Counts as the official announcement so the automatic one doesn't double-post.
            await self.mark_announced(interaction.guild.id, message)

        await interaction.followup.send("Posted.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("Only mods can do that.", ephemeral=True)
            return

        raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(ReferralCog(bot))
