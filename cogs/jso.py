"""
warrants.py — FHP Ghost Unit cross-server warrant system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────── SHARED DB ────────────────────────────────────────

WARRANTS_DB_PATH = "/opt/ghost-bot/warrants.db"

# ─────────────────────────── GU CONFIG ────────────────────────────────────────

SERVER_A_GUILD_ID        = 1317959054177599559
SERVER_A_WARRANT_CHANNEL = 1498041223166955620
SERVER_A_PERSONNEL_ROLE  = 1400862387619500144
SERVER_A_PING_ROLE       = 1318198109725134930

# ─────────────────────────── SWAT CONFIG ──────────────────────────────────────

SERVER_B_GUILD_ID        = 1310032085183893566
SERVER_B_WARRANT_CHANNEL = 1492253558773518458
SERVER_B_PERSONNEL_ROLE  = 1310376351470977148
SERVER_B_PING_ROLE       = 1315403773304242178

# ─────────────────────────── SHARED ASSETS ────────────────────────────────────

FHP_LOGO = "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Florida_Highway_Patrol_logo.svg/1200px-Florida_Highway_Patrol_logo.svg.png"
BOTTOM_IMAGE = "https://media.discordapp.net/attachments/1403360987096027268/1408449383925809262/image.png"
FOOTER_ICON = FHP_LOGO
FALLBACK_AVATAR = "https://tr.rbxcdn.com/30DAY-AvatarHeadshot-placeholder/150/150/AvatarHeadshot/Png"

# ─────────────────────────── HELPERS ──────────────────────────────────────────

def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


def _base_embed(colour: discord.Colour) -> discord.Embed:
    e = discord.Embed(colour=colour)
    e.set_image(url=BOTTOM_IMAGE)
    e.set_footer(text=f"Ghost Unit Utilities • {_utcnow_str()}", icon_url=FOOTER_ICON)
    return e


async def _get_roblox_headshot(username: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://users.roblox.com/v1/usernames/users",
                json={"usernames": [username], "excludeBannedUsers": False},
            ) as r:
                if r.status != 200:
                    return FALLBACK_AVATAR
                data = await r.json()
                if not data.get("data"):
                    return FALLBACK_AVATAR
                user_id = data["data"][0]["id"]

            async with session.get(
                f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
                f"?userIds={user_id}&size=420x420&format=Png&isCircular=false",
            ) as r:
                d = await r.json()
                return d["data"][0]["imageUrl"]
    except Exception as e:
        print(f"[warrants] Roblox error: {e}")
        return FALLBACK_AVATAR


# ─────────────────────────── SERVER CONFIG ────────────────────────────────────

def _server_config(guild_id: int) -> tuple[int, int, int] | None:
    if guild_id == SERVER_A_GUILD_ID:
        return SERVER_A_WARRANT_CHANNEL, SERVER_A_PERSONNEL_ROLE, SERVER_A_PING_ROLE
    if guild_id == SERVER_B_GUILD_ID:
        return SERVER_B_WARRANT_CHANNEL, SERVER_B_PERSONNEL_ROLE, SERVER_B_PING_ROLE
    return None


# ─────────────────────────── DATABASE ─────────────────────────────────────────

async def _init_db():
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS warrants (
            warrant_id TEXT PRIMARY KEY,
            suspect TEXT,
            charges TEXT,
            vehicle_info TEXT,
            last_location TEXT,
            issued_by TEXT,
            issued_at TEXT,
            headshot_url TEXT,
            status TEXT DEFAULT 'active',
            closed_by TEXT,
            closed_at TEXT,
            msg_id_a TEXT,
            msg_id_b TEXT
        )
        """)
        await db.commit()


async def _insert_warrant(warrant_id, suspect, charges, vehicle_info, last_location, issued_by, headshot_url):
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            INSERT INTO warrants VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, NULL, NULL)
        """, (
            warrant_id,
            suspect,
            charges,
            vehicle_info,
            last_location,
            issued_by,
            _utcnow_str(),
            headshot_url
        ))
        await db.commit()


async def _get_warrant(warrant_id: str):
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warrants WHERE warrant_id = ?", (warrant_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _close_warrant(warrant_id: str, user: str, status: str):
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            UPDATE warrants
            SET status=?, closed_by=?, closed_at=?
            WHERE warrant_id=?
        """, (status, user, _utcnow_str(), warrant_id))
        await db.commit()


async def _set_message_ids(warrant_id: str, a: int | None, b: int | None):
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            UPDATE warrants SET msg_id_a=?, msg_id_b=? WHERE warrant_id=?
        """, (str(a) if a else None, str(b) if b else None, warrant_id))
        await db.commit()


# ─────────────────────────── EMBED ────────────────────────────────────────────

def _build_warrant_embed(warrant, status=None, closed_by=None, closed_at=None):

    colour = discord.Colour.red() if warrant["status"] == "active" else discord.Colour.green()

    e = _base_embed(colour)

    title = {
        "active": "🚨 WARRANT – ACTIVE",
        "executed": "🟢 WARRANT – EXECUTED",
        "voided": "⚠️ WARRANT – VOIDED"
    }.get(status or warrant["status"], "WARRANT")

    e.title = title
    e.set_thumbnail(url=warrant["headshot_url"])

    e.add_field(name="Warrant ID", value=warrant["warrant_id"], inline=False)
    e.add_field(name="Suspect", value=warrant["suspect"], inline=True)
    e.add_field(name="Issued By", value=warrant["issued_by"], inline=True)
    e.add_field(name="Charges", value=warrant["charges"], inline=False)
    e.add_field(name="Vehicle", value=warrant["vehicle_info"] or "Unknown", inline=True)
    e.add_field(name="Location", value=warrant["last_location"] or "Unknown", inline=True)

    if closed_by:
        e.add_field(name="Executed By", value=closed_by, inline=False)

        # Convert stored string to Discord timestamp
        try:
            dt = datetime.strptime(closed_at, "%d/%m/%Y %H:%M")
            unix = int(dt.replace(tzinfo=timezone.utc).timestamp())
            ts = f"<t:{unix}:F>"
        except:
            ts = closed_at

        e.add_field(name="Executed At", value=ts, inline=False)

    return e


# ─────────────────────────── VIEW ─────────────────────────────────────────────

class WarrantView(discord.ui.View):
    def __init__(self, warrant_id: str, disabled=False):
        super().__init__(timeout=None)
        self.warrant_id = warrant_id

        self.exec_btn = discord.ui.Button(
            label="Mark as Executed",
            style=discord.ButtonStyle.success,
            custom_id=f"exec:{warrant_id}",
            disabled=disabled
        )

        self.void_btn = discord.ui.Button(
            label="Void Warrant",
            emoji="⚠️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"void:{warrant_id}",
            disabled=disabled
        )

        self.exec_btn.callback = self.execute
        self.void_btn.callback = self.void

        self.add_item(self.exec_btn)
        self.add_item(self.void_btn)

    async def execute(self, interaction: discord.Interaction):
        await self._close(interaction, "executed")

    async def void(self, interaction: discord.Interaction):
        await self._close(interaction, "voided")

    async def _close(self, interaction, status):
        await interaction.response.defer(ephemeral=True)

        warrant = await _get_warrant(self.warrant_id)
        if not warrant:
            return await interaction.followup.send("Not found", ephemeral=True)

        await _close_warrant(self.warrant_id, interaction.user.display_name, status)

        updated = await _get_warrant(self.warrant_id)

        embed = _build_warrant_embed(
            updated,
            status=status,
            closed_by=interaction.user.display_name,
            closed_at=_utcnow_str()
        )

        disabled_view = WarrantView(self.warrant_id, disabled=True)

        await _mirror_edit(interaction.client, updated, embed, disabled_view)

        await interaction.followup.send(f"{status.title()} complete.", ephemeral=True)


# ─────────────────────────── POSTING ──────────────────────────────────────────

async def _post_to_channel(bot, guild_id, channel_id, embed, view, ping_role_id):
    guild = bot.get_guild(guild_id)
    if not guild:
        return None

    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return None

    content = f"<@&{ping_role_id}>" if ping_role_id else None

    return await channel.send(
        content=content,
        embed=embed,
        view=view,
        allowed_mentions=discord.AllowedMentions(roles=True),
    )


async def _mirror_edit(bot, warrant, embed, view):
    for gid, msg_key, ch in [
        (SERVER_A_GUILD_ID, "msg_id_a", SERVER_A_WARRANT_CHANNEL),
        (SERVER_B_GUILD_ID, "msg_id_b", SERVER_B_WARRANT_CHANNEL),
    ]:
        msg_id = warrant.get(msg_key)
        if not msg_id:
            continue

        guild = bot.get_guild(gid)
        channel = guild.get_channel(ch)
        if not channel:
            continue

        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
        except:
            pass


# ─────────────────────────── COG ──────────────────────────────────────────────

class WarrantsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await _init_db()

    @app_commands.command(name="issue_warrant")
    async def issue_warrant(self, interaction, suspect: str, charges: str,
                            vehicle_info: Optional[str] = None,
                            last_location: Optional[str] = None):

        cfg = _server_config(interaction.guild.id)
        if not cfg:
            return await interaction.response.send_message("No permission", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        warrant_id = uuid.uuid4().hex[:10].upper()
        headshot = await _get_roblox_headshot(suspect)

        await _insert_warrant(
            warrant_id, suspect, charges,
            vehicle_info, last_location,
            interaction.user.display_name,
            headshot
        )

        warrant = await _get_warrant(warrant_id)
        embed = _build_warrant_embed(warrant)

        view = WarrantView(warrant_id)
        self.bot.add_view(view)

        cfg_a = _server_config(SERVER_A_GUILD_ID)
        cfg_b = _server_config(SERVER_B_GUILD_ID)

        msg_a = await _post_to_channel(self.bot, SERVER_A_GUILD_ID,
                                       SERVER_A_WARRANT_CHANNEL,
                                       embed, view, cfg_a[2])

        msg_b = await _post_to_channel(self.bot, SERVER_B_GUILD_ID,
                                       SERVER_B_WARRANT_CHANNEL,
                                       embed, view, cfg_b[2])

        await _set_message_ids(
            warrant_id,
            msg_a.id if msg_a else None,
            msg_b.id if msg_b else None
        )

        await interaction.followup.send(f"Issued `{warrant_id}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WarrantsCog(bot))