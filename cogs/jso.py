"""
warrants.py — FHP Ghost Unit cross-server warrant system.

Two separate bots run this same cog. They share a single SQLite database file
(WARRANTS_DB_PATH) on the same machine. When either bot issues or closes a
warrant, it updates the DB and mirrors the embed into the other server's
channel via the other bot's guild/channel lookup.

Commands (require personnel role in their own server):
  /issue_warrant  — issue a warrant; posts to both servers simultaneously
  /void_warrant   — manually void/cancel an active warrant by DB ID

"Mark as Executed" button — usable by any personnel-role member in either server.

Setup checklist:
  1. Set WARRANTS_DB_PATH to an absolute path both bots can read/write.
  2. Fill in the SERVER_A / SERVER_B config blocks below.
  3. Load this cog in both bots: await bot.load_extension("warrants")
  4. Both bots must share the same WARRANTS_DB_PATH on disk.

The cog uses aiosqlite for async DB access; install with:
  pip install aiosqlite
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

WARRANTS_DB_PATH = "/shared/ghost_unit/warrants.db"  # ← absolute path on disk

# ─────────────────────────── SERVER A CONFIG ──────────────────────────────────
# Fill these in for the first server / first bot.

SERVER_A_GUILD_ID         = 1317959054177599559   # ← Server A guild ID
SERVER_A_WARRANT_CHANNEL  = 1498041223166955620   # ← #warrants channel in Server A
SERVER_A_PERSONNEL_ROLE   = 1400862387619500144    # ← Personnel role ID in Server A

# ─────────────────────────── SERVER B CONFIG ──────────────────────────────────
# Fill these in for the second server / second bot.

SERVER_B_GUILD_ID         = 1317959054177599559   # ← Server B guild ID
SERVER_B_WARRANT_CHANNEL  = 1498041539933507784   # ← #warrants channel in Server B
SERVER_B_PERSONNEL_ROLE   = 1426729477362159670   # ← Personnel role ID in Server B

# ─────────────────────────── SHARED ASSETS ────────────────────────────────────

FHP_LOGO     = "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Florida_Highway_Patrol_logo.svg/1200px-Florida_Highway_Patrol_logo.svg.png"
BOTTOM_IMAGE = "https://media.discordapp.net/attachments/1403360987096027268/1408449383925809262/image.png?ex=69b6ba34&is=69b568b4&hm=1333e32082220cc64cd189b22e521c1f6b1d05bb0643587e0d3258817737244a&=&format=webp&quality=lossless&width=1867&height=70"
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
                timeout=aiohttp.ClientTimeout(total=10),
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
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return FALLBACK_AVATAR
                d = await r.json()
                if d.get("data") and "imageUrl" in d["data"][0]:
                    return d["data"][0]["imageUrl"]
    except Exception as e:
        print(f"[warrants] Roblox headshot error for {username}: {e}")
    return FALLBACK_AVATAR

def _server_config(guild_id: int) -> tuple[int, int] | None:
    """Return (warrant_channel_id, personnel_role_id) for a guild, or None."""
    if guild_id == SERVER_A_GUILD_ID:
        return SERVER_A_WARRANT_CHANNEL, SERVER_A_PERSONNEL_ROLE
    if guild_id == SERVER_B_GUILD_ID:
        return SERVER_B_WARRANT_CHANNEL, SERVER_B_PERSONNEL_ROLE
    return None

def _other_guild_id(guild_id: int) -> int | None:
    """Return the other server's guild ID."""
    if guild_id == SERVER_A_GUILD_ID:
        return SERVER_B_GUILD_ID
    if guild_id == SERVER_B_GUILD_ID:
        return SERVER_A_GUILD_ID
    return None

# ─────────────────────────── DATABASE ─────────────────────────────────────────

async def _init_db():
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warrants (
                warrant_id      TEXT PRIMARY KEY,
                suspect         TEXT NOT NULL,
                charges         TEXT NOT NULL,
                vehicle_info    TEXT,
                last_location   TEXT,
                issued_by       TEXT NOT NULL,
                issued_at       TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'active',
                closed_by       TEXT,
                closed_at       TEXT,
                msg_id_a        TEXT,
                msg_id_b        TEXT
            )
        """)
        await db.commit()

async def _insert_warrant(
    warrant_id: str,
    suspect: str,
    charges: str,
    vehicle_info: str | None,
    last_location: str | None,
    issued_by: str,
) -> None:
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            INSERT INTO warrants
                (warrant_id, suspect, charges, vehicle_info, last_location,
                 issued_by, issued_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """, (warrant_id, suspect, charges, vehicle_info, last_location,
              issued_by, _utcnow_str()))
        await db.commit()

async def _set_message_ids(warrant_id: str, msg_id_a: int | None, msg_id_b: int | None) -> None:
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            UPDATE warrants SET msg_id_a = ?, msg_id_b = ? WHERE warrant_id = ?
        """, (str(msg_id_a) if msg_id_a else None,
              str(msg_id_b) if msg_id_b else None,
              warrant_id))
        await db.commit()

async def _get_warrant(warrant_id: str) -> dict | None:
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM warrants WHERE warrant_id = ?", (warrant_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def _close_warrant(warrant_id: str, closed_by: str, status: str) -> None:
    async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
        await db.execute("""
            UPDATE warrants
            SET status = ?, closed_by = ?, closed_at = ?
            WHERE warrant_id = ?
        """, (status, closed_by, _utcnow_str(), warrant_id))
        await db.commit()

# ─────────────────────────── EMBED BUILDER ────────────────────────────────────

def _build_warrant_embed(
    warrant_id: str,
    suspect: str,
    charges: str,
    vehicle_info: str | None,
    last_location: str | None,
    issued_by: str,
    headshot_url: str,
    status: str = "active",
    closed_by: str | None = None,
    closed_at: str | None = None,
) -> discord.Embed:
    if status == "active":
        colour = discord.Colour.red()
        title  = "🚨 WARRANT – Active"
    elif status == "executed":
        colour = discord.Colour.brand_green()
        title  = "✅ WARRANT – Executed"
    else:
        colour = discord.Colour.greyple()
        title  = "🚫 WARRANT – Voided"

    emb = _base_embed(colour)
    emb.title = title
    emb.description = (
        "An arrest warrant has been issued. All units are authorised to detain "
        "the listed suspect on sight."
    )
    emb.set_thumbnail(url=headshot_url)

    emb.add_field(name="Warrant ID",     value=f"`{warrant_id}`",          inline=False)
    emb.add_field(name="Suspect",        value=suspect,                    inline=True)
    emb.add_field(name="Issued By",      value=issued_by,                  inline=True)
    emb.add_field(name="\u200b",         value="\u200b",                   inline=False)
    emb.add_field(name="Charges",        value=charges,                    inline=False)
    emb.add_field(name="Vehicle Info",   value=vehicle_info or "Unknown",  inline=True)
    emb.add_field(name="Last Location",  value=last_location or "Unknown", inline=True)

    if closed_by and closed_at:
        emb.add_field(name="\u200b", value="\u200b", inline=False)
        label = "Executed by" if status == "executed" else "Voided by"
        emb.add_field(name=label,         value=closed_by, inline=True)
        emb.add_field(name="Closed At",   value=closed_at, inline=True)

    return emb

# ─────────────────────────── VIEW ─────────────────────────────────────────────

class WarrantView(discord.ui.View):
    """
    Persistent view attached to every warrant embed.
    custom_id encodes the warrant_id so it survives bot restarts.
    Pattern: warrant_exec:<warrant_id>
    """

    def __init__(self, warrant_id: str, disabled: bool = False):
        super().__init__(timeout=None)
        self.warrant_id = warrant_id
        btn = discord.ui.Button(
            label="Mark as Executed",
            style=discord.ButtonStyle.success,
            custom_id=f"warrant_exec:{warrant_id}",
            disabled=disabled,
        )
        btn.callback = self._execute_callback
        self.add_item(btn)

    async def _execute_callback(self, interaction: discord.Interaction):
        member = interaction.user
        guild  = interaction.guild
        if not guild or not isinstance(member, discord.Member):
            await interaction.response.send_message("Cannot verify your server membership.", ephemeral=True)
            return

        cfg = _server_config(guild.id)
        if not cfg:
            await interaction.response.send_message("This server is not configured.", ephemeral=True)
            return
        _, personnel_role_id = cfg

        if not any(r.id == personnel_role_id for r in member.roles):
            await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
            return

        warrant = await _get_warrant(self.warrant_id)
        if not warrant:
            await interaction.response.send_message("Warrant not found in database.", ephemeral=True)
            return
        if warrant["status"] != "active":
            await interaction.response.send_message(
                f"This warrant is already `{warrant['status']}`.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        closed_by = member.display_name
        closed_at = _utcnow_str()
        await _close_warrant(self.warrant_id, closed_by, "executed")

        # Re-fetch to get full row for embed rebuild
        warrant = await _get_warrant(self.warrant_id)

        headshot_url = warrant.get("headshot_url") or FALLBACK_AVATAR  # see note below
        new_emb = _build_warrant_embed(
            warrant_id    = self.warrant_id,
            suspect       = warrant["suspect"],
            charges       = warrant["charges"],
            vehicle_info  = warrant["vehicle_info"],
            last_location = warrant["last_location"],
            issued_by     = warrant["issued_by"],
            headshot_url  = headshot_url,
            status        = "executed",
            closed_by     = closed_by,
            closed_at     = closed_at,
        )
        disabled_view = WarrantView(self.warrant_id, disabled=True)

        # Edit both server messages
        bot: commands.Bot = interaction.client
        await _mirror_edit(bot, warrant, new_emb, disabled_view)

        await interaction.followup.send("✅ Warrant marked as executed in both servers.", ephemeral=True)


# ─────────────────────────── MIRROR HELPERS ───────────────────────────────────

async def _post_to_channel(
    bot: commands.Bot,
    guild_id: int,
    channel_id: int,
    embed: discord.Embed,
    view: discord.ui.View,
) -> discord.Message | None:
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return None
    return await channel.send(embed=embed, view=view)

async def _mirror_edit(
    bot: commands.Bot,
    warrant: dict,
    embed: discord.Embed,
    view: discord.ui.View,
) -> None:
    """Edit the warrant message in both servers."""
    for guild_id, msg_key, ch_key in [
        (SERVER_A_GUILD_ID, "msg_id_a", SERVER_A_WARRANT_CHANNEL),
        (SERVER_B_GUILD_ID, "msg_id_b", SERVER_B_WARRANT_CHANNEL),
    ]:
        msg_id = warrant.get(msg_key)
        if not msg_id:
            continue
        guild = bot.get_guild(guild_id)
        if not guild:
            continue
        channel = guild.get_channel(ch_key)
        if not isinstance(channel, discord.TextChannel):
            continue
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=embed, view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"[warrants] Could not edit message in guild {guild_id}: {e}")

# ─────────────────────────── COG ──────────────────────────────────────────────

class WarrantsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await _init_db()
        # Re-register persistent views for any active warrants after restart
        async with aiosqlite.connect(WARRANTS_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT warrant_id FROM warrants WHERE status = 'active'"
            ) as cur:
                rows = await cur.fetchall()
        for row in rows:
            self.bot.add_view(WarrantView(row["warrant_id"]))

    def _has_personnel(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False
        cfg = _server_config(interaction.guild.id)
        if not cfg:
            return False
        _, role_id = cfg
        return any(r.id == role_id for r in interaction.user.roles)

    # ── /issue_warrant ─────────────────────────────────────────────────────────

    @app_commands.command(name="issue_warrant", description="Issue an arrest warrant (syncs to both servers).")
    @app_commands.describe(
        suspect       = "Roblox username of the suspect",
        charges       = "Charges against the suspect",
        vehicle_info  = "Vehicle make, model, colour, plate (optional)",
        last_location = "Last known location of the suspect (optional)",
    )
    async def issue_warrant(
        self,
        interaction: discord.Interaction,
        suspect:       str,
        charges:       str,
        vehicle_info:  Optional[str] = None,
        last_location: Optional[str] = None,
    ):
        if not self._has_personnel(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        warrant_id   = uuid.uuid4().hex[:10].upper()
        issued_by    = interaction.user.display_name
        headshot_url = await _get_roblox_headshot(suspect)

        await _insert_warrant(
            warrant_id    = warrant_id,
            suspect       = suspect,
            charges       = charges,
            vehicle_info  = vehicle_info,
            last_location = last_location,
            issued_by     = issued_by,
        )

        emb  = _build_warrant_embed(
            warrant_id    = warrant_id,
            suspect       = suspect,
            charges       = charges,
            vehicle_info  = vehicle_info,
            last_location = last_location,
            issued_by     = issued_by,
            headshot_url  = headshot_url,
        )
        view = WarrantView(warrant_id)
        self.bot.add_view(view)  # register persistent view

        # Post to Server A
        msg_a = await _post_to_channel(
            self.bot, SERVER_A_GUILD_ID, SERVER_A_WARRANT_CHANNEL, emb, view
        )
        # Post to Server B
        msg_b = await _post_to_channel(
            self.bot, SERVER_B_GUILD_ID, SERVER_B_WARRANT_CHANNEL, emb, view
        )

        await _set_message_ids(
            warrant_id,
            msg_a.id if msg_a else None,
            msg_b.id if msg_b else None,
        )

        posted = []
        if msg_a:
            posted.append("Server A")
        if msg_b:
            posted.append("Server B")
        dest = " and ".join(posted) if posted else "no servers (check channel config)"

        await interaction.followup.send(
            f"✅ Warrant `{warrant_id}` issued and posted to {dest}.", ephemeral=True
        )

    # ── /void_warrant ──────────────────────────────────────────────────────────

    @app_commands.command(name="void_warrant", description="Void/cancel an active warrant by ID.")
    @app_commands.describe(warrant_id="The 10-character warrant ID (shown in the embed)")
    async def void_warrant(
        self,
        interaction: discord.Interaction,
        warrant_id:  str,
    ):
        if not self._has_personnel(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        warrant = await _get_warrant(warrant_id.upper())
        if not warrant:
            await interaction.followup.send("Warrant not found.", ephemeral=True)
            return
        if warrant["status"] != "active":
            await interaction.followup.send(
                f"Warrant is already `{warrant['status']}`.", ephemeral=True
            )
            return

        closed_by = interaction.user.display_name
        closed_at = _utcnow_str()
        await _close_warrant(warrant_id.upper(), closed_by, "voided")
        warrant = await _get_warrant(warrant_id.upper())

        new_emb = _build_warrant_embed(
            warrant_id    = warrant_id.upper(),
            suspect       = warrant["suspect"],
            charges       = warrant["charges"],
            vehicle_info  = warrant["vehicle_info"],
            last_location = warrant["last_location"],
            issued_by     = warrant["issued_by"],
            headshot_url  = FALLBACK_AVATAR,
            status        = "voided",
            closed_by     = closed_by,
            closed_at     = closed_at,
        )
        disabled_view = WarrantView(warrant_id.upper(), disabled=True)
        await _mirror_edit(self.bot, warrant, new_emb, disabled_view)

        await interaction.followup.send(
            f"✅ Warrant `{warrant_id.upper()}` voided in both servers.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WarrantsCog(bot))