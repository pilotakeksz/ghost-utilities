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

# ─────────────────────────── GU CONFIG ──────────────────────────────────

SERVER_A_GUILD_ID        = 1317959054177599559
SERVER_A_WARRANT_CHANNEL = 1498041223166955620
SERVER_A_PERSONNEL_ROLE  = 1400862387619500144
SERVER_A_PING_ROLE       = 1318198109725134930  # NEW

# ─────────────────────────── SWAT CONFIG ──────────────────────────────────

SERVER_B_GUILD_ID        = 1310032085183893566
SERVER_B_WARRANT_CHANNEL = 1492253558773518458
SERVER_B_PERSONNEL_ROLE  = 1310376351470977148
SERVER_B_PING_ROLE       = 1315403773304242178  # NEW

# ─────────────────────────── SHARED ASSETS ────────────────────────────────────

FHP_LOGO = "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Florida_Highway_Patrol_logo.svg/1200px-Florida_Highway_Patrol_logo.svg.png"
BOTTOM_IMAGE = "https://media.discordapp.net/attachments/1403360987096027268/1408449383925809262/image.png"
FALLBACK_AVATAR = "https://tr.rbxcdn.com/30DAY-AvatarHeadshot-placeholder/150/150/AvatarHeadshot/Png"

# ─────────────────────────── HELPERS ──────────────────────────────────────────

def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")


def _base_embed(colour: discord.Colour) -> discord.Embed:
    e = discord.Embed(colour=colour)
    e.set_thumbnail(url=FHP_LOGO)
    e.set_image(url=BOTTOM_IMAGE)
    e.set_footer(text=f"Ghost Unit Utilities • {_utcnow_str()}")
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
                if r.status != 200:
                    return FALLBACK_AVATAR
                d = await r.json()
                return d["data"][0]["imageUrl"]
    except Exception as e:
        print(f"[warrants] Roblox error: {e}")
        return FALLBACK_AVATAR


# ─────────────────────────── SERVER CONFIG ────────────────────────────────────

def _server_config(guild_id: int) -> tuple[int, int, int] | None:
    # (channel_id, personnel_role_id, ping_role_id)

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
            status TEXT DEFAULT 'active',
            closed_by TEXT,
            closed_at TEXT,
            msg_id_a TEXT,
            msg_id_b TEXT
        )
        """)
        await db.commit()


async def _insert_warrant(warrant_id, suspect, charges, vehicle_info, last_location, issued_by):
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            INSERT INTO warrants VALUES (?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, NULL, NULL)
        """, (
            warrant_id, suspect, charges, vehicle_info, last_location,
            issued_by, _utcnow_str()
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

def _build_warrant_embed(warrant_id, suspect, charges, vehicle_info,
                         last_location, issued_by, headshot_url,
                         status="active", closed_by=None, closed_at=None):

    colour = discord.Colour.red() if status == "active" else discord.Colour.green()

    e = _base_embed(colour)
    e.title = f"🚨 WARRANT – {status.upper()}"

    e.set_thumbnail(url=headshot_url)

    e.add_field(name="Warrant ID", value=warrant_id, inline=False)
    e.add_field(name="Suspect", value=suspect, inline=True)
    e.add_field(name="Issued By", value=issued_by, inline=True)
    e.add_field(name="Charges", value=charges, inline=False)
    e.add_field(name="Vehicle", value=vehicle_info or "Unknown", inline=True)
    e.add_field(name="Location", value=last_location or "Unknown", inline=True)

    if closed_by:
        e.add_field(name="Closed By", value=closed_by, inline=True)
        e.add_field(name="Closed At", value=closed_at, inline=True)

    return e


# ─────────────────────────── VIEW ─────────────────────────────────────────────

class WarrantView(discord.ui.View):
    def __init__(self, warrant_id: str, disabled=False):
        super().__init__(timeout=None)
        self.warrant_id = warrant_id

        btn = discord.ui.Button(
            label="Mark as Executed",
            style=discord.ButtonStyle.success,
            custom_id=f"warrant_exec:{warrant_id}",
            disabled=disabled,
        )
        btn.callback = self.execute
        self.add_item(btn)

    async def execute(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        cfg = _server_config(guild.id)
        if not cfg:
            return await interaction.response.send_message("Not configured", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        warrant = await _get_warrant(self.warrant_id)
        if not warrant:
            return await interaction.followup.send("Not found", ephemeral=True)

        await _close_warrant(self.warrant_id, member.display_name, "executed")

        new_embed = _build_warrant_embed(
            self.warrant_id,
            warrant["suspect"],
            warrant["charges"],
            warrant["vehicle_info"],
            warrant["last_location"],
            warrant["issued_by"],
            FALLBACK_AVATAR,
            "executed",
            member.display_name,
            _utcnow_str()
        )

        await _mirror_edit(interaction.client, warrant, new_embed, WarrantView(self.warrant_id, True))
        await interaction.followup.send("Executed", ephemeral=True)


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

        await _insert_warrant(warrant_id, suspect, charges, vehicle_info,
                              last_location, interaction.user.display_name)

        embed = _build_warrant_embed(
            warrant_id, suspect, charges, vehicle_info,
            last_location, interaction.user.display_name, headshot
        )

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