"""
logs.py — FHP Ghost Unit traffic stop, BOLO, and arrest log cog.

Commands (require role 1317963289518542959):
  /traffic_stop  — log a traffic stop; auto-issues BOLO if outcome is fled/fleeing
  /arrest_log    — log an arrest; fetches Roblox headshot for the suspect

Channels:
  LOG_CHANNEL_ID  = 1317963340336861194  — arrest logs
  BOLO_CHANNEL_ID = 1433452698564300810  — BOLOs

BOLO "Mark as Complete" button usable by anyone with the personnel role.
Arrest log "Issued by" is shown as a disabled button below the embed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────── CONFIG ───────────────────────────────────────────

PERSONNEL_ROLE_ID = 1317963289518542959
LOG_CHANNEL_ID    = 1317963340336861194  # arrest logs
TS_CHANNEL_ID     = 1317963341272186963  # traffic stops
BOLO_CHANNEL_ID   = 1433452698564300810

FHP_LOGO     = "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6a/Florida_Highway_Patrol_logo.svg/1200px-Florida_Highway_Patrol_logo.svg.png"
BOTTOM_IMAGE = "https://media.discordapp.net/attachments/1403360987096027268/1408449383925809262/image.png?ex=69b6ba34&is=69b568b4&hm=1333e32082220cc64cd189b22e521c1f6b1d05bb0643587e0d3258817737244a&=&format=webp&quality=lossless&width=1867&height=70"

FLED_KEYWORDS    = {"fled", "flee", "fleeing", "ran", "escaped", "escape", "evaded", "evading", "pursuit"}
FALLBACK_AVATAR  = "https://tr.rbxcdn.com/30DAY-AvatarHeadshot-placeholder/150/150/AvatarHeadshot/Png"

OUTCOME_CHOICES = [
    app_commands.Choice(name="Citation",       value="Citation"),
    app_commands.Choice(name="Warning",        value="Warning"),
    app_commands.Choice(name="Arrest",         value="Arrest"),
    app_commands.Choice(name="Fled / Pursuit", value="Fled / Pursuit"),
    app_commands.Choice(name="Released",       value="Released"),
    app_commands.Choice(name="Vehicle Search", value="Vehicle Search"),
]

# ─────────────────────────── HELPERS ──────────────────────────────────────────

def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M")

def _is_fled(outcome: str) -> bool:
    return any(kw in outcome.lower() for kw in FLED_KEYWORDS)

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
        print(f"[logs] Roblox headshot error for {username}: {e}")
    return FALLBACK_AVATAR

# ─────────────────────────── VIEWS ────────────────────────────────────────────

class BOLOView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Mark as Complete", style=discord.ButtonStyle.success, custom_id="bolo_complete")
    async def complete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member) or not any(r.id == PERSONNEL_ROLE_ID for r in member.roles):
            await interaction.response.send_message("You don't have permission to do this.", ephemeral=True)
            return
        msg = interaction.message
        if not msg or not msg.embeds:
            await interaction.response.send_message("Could not find the BOLO embed.", ephemeral=True)
            return
        emb = msg.embeds[0].copy()
        emb.title = "✅ BOLO – Completed"
        emb.colour = discord.Colour.brand_green()
        emb.set_footer(text=f"{emb.footer.text or 'Ghost Unit Utilities'} • Completed by {member.display_name}")
        button.disabled = True
        button.label = "Completed"
        await interaction.response.edit_message(embed=emb, view=self)


class IssuedByView(discord.ui.View):
    """Persistent view showing a disabled 'Issued by' button below the embed."""
    def __init__(self, label: str, custom_id: str):
        super().__init__(timeout=None)
        btn = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.secondary,
            disabled=True,
            custom_id=custom_id,
        )
        self.add_item(btn)


# ─────────────────────────── AUTOCOMPLETE ─────────────────────────────────────

# ─────────────────────────── COG ──────────────────────────────────────────────

class LogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(BOLOView())

    def _has_personnel(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        return any(r.id == PERSONNEL_ROLE_ID for r in interaction.user.roles)

    # ── /traffic_stop ──────────────────────────────────────────────────────────

    @app_commands.command(name="traffic_stop", description="Log a traffic stop.")
    @app_commands.describe(
        driver          = "Roblox username of the driver",
        troopers_ghost  = "Ghost Unit troopers involved (comma-separated @mentions)",
        troopers_other  = "Non-Ghost troopers involved (free text, or leave blank)",
        vehicle_model   = "Vehicle model",
        plate           = "Vehicle plate",
        reason          = "Reason for the stop",
        location        = "Location",
        outcome         = "Outcome",
    )
    @app_commands.choices(outcome=OUTCOME_CHOICES)
    async def traffic_stop(
        self,
        interaction:    discord.Interaction,
        driver:         str,
        troopers_ghost: str,
        vehicle_model:  str,
        plate:          str,
        reason:         str,
        location:       str,
        outcome:        app_commands.Choice[str],
        troopers_other: Optional[str] = None,
    ):
        if not self._has_personnel(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild   = interaction.guild
        channel = guild.get_channel(TS_CHANNEL_ID) if guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Log channel not found.", ephemeral=True)
            return

        issuer = interaction.user

        emb = _base_embed(discord.Colour.from_str("#E67E22"))
        emb.title = "🚔 Traffic Stop"
        emb.description = "Traffic stop details below."
        emb.add_field(name="Driver",            value=driver,         inline=False)
        emb.add_field(name="Troopers Involved", value=troopers_ghost, inline=False)
        if troopers_other:
            emb.add_field(name="Troopers Involved (Non-Ghost)", value=troopers_other, inline=False)
        emb.add_field(name="Vehicle Model", value=vehicle_model, inline=True)
        emb.add_field(name="Plate",         value=plate,         inline=True)
        emb.add_field(name="Reason",        value=reason,        inline=False)
        emb.add_field(name="Location",      value=location,      inline=True)
        emb.add_field(name="Outcome",       value=outcome.value, inline=True)

        import uuid
        issued_view = IssuedByView(
            label=f"Issued by {issuer.display_name}",
            custom_id=f"ts_issued_{uuid.uuid4().hex[:12]}",
        )
        await channel.send(embed=emb, view=issued_view)

        if _is_fled(outcome.value):
            bolo_channel = guild.get_channel(BOLO_CHANNEL_ID) if guild else None
            if isinstance(bolo_channel, discord.TextChannel):
                bolo_emb = _base_embed(discord.Colour.red())
                bolo_emb.title = "🚨 BOLO – Active"
                bolo_emb.description = (
                    "A BOLO has been automatically issued after a driver has fled from a traffic stop. "
                    "Below details will be attached, including;"
                )
                bolo_emb.add_field(name="Driver",          value=driver,         inline=False)
                bolo_emb.add_field(name="Vehicle",         value=vehicle_model,  inline=True)
                bolo_emb.add_field(name="Plate",           value=plate,          inline=True)
                bolo_emb.add_field(name="Last Location",   value=location,       inline=False)
                bolo_emb.add_field(name="Reason for Stop", value=reason,         inline=False)
                bolo_emb.add_field(name="Issued By",       value=troopers_ghost, inline=False)
                bolo_emb.set_footer(text=f"Ghost Unit Utilities • Auto BOLO • {_utcnow_str()}")
                await bolo_channel.send(embed=bolo_emb, view=BOLOView())

        await interaction.followup.send("✅ Traffic stop logged.", ephemeral=True)

    # ── /arrest_log ────────────────────────────────────────────────────────────

    @app_commands.command(name="arrest_log", description="Log an arrest.")
    @app_commands.describe(
        suspect            = "Roblox username of the suspect",
        troopers_ghost     = "Ghost Unit troopers involved (comma-separated @mentions)",
        objects_possession = "Objects found on suspect (required)",
        charges            = "Charges — pick a preset or type your own",
        troopers_other     = "Non-Ghost troopers involved (free text, or leave blank)",
        objects_car        = "Objects found in vehicle (leave blank for None)",
    )
    async def arrest_log(
        self,
        interaction:        discord.Interaction,
        suspect:            str,
        troopers_ghost:     str,
        objects_possession: str,
        charges:            str,
        troopers_other:     Optional[str] = None,
        objects_car:        Optional[str] = None,
    ):
        if not self._has_personnel(interaction):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild   = interaction.guild
        channel = guild.get_channel(LOG_CHANNEL_ID) if guild else None
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send("Log channel not found.", ephemeral=True)
            return

        issuer       = interaction.user
        headshot_url = await _get_roblox_headshot(suspect)

        emb = discord.Embed(colour=discord.Colour.red())
        emb.title = "🚔 Arrest Log"
        emb.description = "An arrest has been logged, below you will find details such as; suspect, charges, troopers involved, and more."
        emb.set_thumbnail(url=headshot_url)
        emb.set_image(url=BOTTOM_IMAGE)

        # Row 1: Suspect | Troopers (FHP Ghost)
        emb.add_field(name="Suspect:",                       value=suspect,         inline=True)
        emb.add_field(name="Troopers Involved (FHP Ghost):", value=troopers_ghost,  inline=True)
        # Spacer row
        emb.add_field(name="\u200b", value="\u200b", inline=False)
        # Row 2: Troopers (Non-Ghost) | Objects in Possession
        emb.add_field(name="Troopers Involved (Non-Ghost):", value=troopers_other or "None",   inline=True)
        emb.add_field(name="Objects in Possession:",         value=objects_possession,          inline=True)
        # Spacer row
        emb.add_field(name="\u200b", value="\u200b", inline=False)
        # Row 3: Objects in Car | Charges
        emb.add_field(name="Objects in Car:", value=objects_car or "None", inline=True)
        emb.add_field(name="Charges:",        value=charges,               inline=True)

        emb.set_footer(text=f"Ghost Unit Utilities • {_utcnow_str()}")

        import uuid
        issued_view = IssuedByView(
            label=f"Issued by: {issuer.display_name}",
            custom_id=f"al_issued_{uuid.uuid4().hex[:12]}",
        )
        await channel.send(embed=emb, view=issued_view)

        await interaction.followup.send("✅ Arrest logged.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(LogsCog(bot))