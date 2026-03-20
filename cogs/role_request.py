"""
training_apps.py — FHP Ghost Unit training application handler.

Watches channel 1339307421427826730 for training application messages.

Format required:
    Username:
    Role: Awaiting Training.
    Proof:
    (+ at least one image attachment)

Behaviour:
- Valid format + image  → react ✅ yes + ❌ no
- Invalid format        → reply listing missing fields, react 🚨
- Approver (SHR/HICOM) reacts yes
    → assign roles, remove all reactions, react ✔ check, DM applicant
- Approver reacts no
    → remove all reactions, react 🚨, DM applicant explaining rejection reasons
- Every 2 application messages → post format reminder embed
"""

from __future__ import annotations

import re
import asyncio
import json
import os
from typing import Optional

import discord
from discord.ext import commands

DATA_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PENDING_FILE = os.path.join(DATA_DIR, "training_pending.json")

# ─────────────────────────── CONFIG ───────────────────────────────────────────

APP_CHANNEL_ID = 1339307421427826730

# Roles that can approve (react yes)
APPROVER_ROLE_IDS = {
    1317963237920215111,  # Senior High Rank
    1318181592719687681,  # High Command
}

# Roles assigned on approval
ASSIGN_ROLE_IDS = [
    1400570836510838835,
    1398698664930836482,
    1317963289518542959,
    1317963259072221286,
    1434643638578843698,
]

# Custom emoji IDs
EMOJI_YES    = "<:yes:1482070633784414282>"
EMOJI_NO     = "<:no:1482070542797377779>"
EMOJI_CHECK  = "<:check:1482070474962763899>"
EMOJI_RAID   = "<:Report_Raid:1482070611080773734>"

# Raw emoji strings for add_reaction (name:id format)
REACT_YES   = "yes:1482070633784414282"
REACT_NO    = "no:1482070542797377779"
REACT_CHECK = "check:1482070474962763899"
REACT_RAID  = "Report_Raid:1482070611080773734"

# Format reminder sent every N valid application messages
REMINDER_INTERVAL = 2

# ─────────────────────────── HELPERS ──────────────────────────────────────────

def _parse_app(content: str) -> tuple[bool, list[str]]:
    """
    Check if content matches the application format.
    Returns (is_valid, missing_fields).
    All three fields must be present; Role must equal "Awaiting Training."
    """
    missing: list[str] = []

    if not re.search(r"(?i)^username\s*:", content, re.MULTILINE):
        missing.append("`Username:`")

    role_m = re.search(r"(?i)^role\s*:\s*(.+)", content, re.MULTILINE)
    if not role_m:
        missing.append("`Role:`")
    elif role_m.group(1).strip().rstrip(".") != "Awaiting Training":
        missing.append("`Role:` must be exactly `Awaiting Training.`")

    if not re.search(r"(?i)^proof\s*:", content, re.MULTILINE):
        missing.append("`Proof:`")

    return len(missing) == 0, missing


def _format_reminder_embed() -> discord.Embed:
    emb = discord.Embed(
        title="Application Format",
        description="**Format**\n```Username:\nRole: Awaiting Training.\nProof:```",
        colour=discord.Colour.blurple(),
    )
    return emb


async def _get_reaction_emoji(guild: discord.Guild, emoji_str: str) -> Optional[discord.Emoji]:
    """Fetch a custom emoji from the guild by 'name:id' string."""
    try:
        eid = int(emoji_str.split(":")[1])
        return discord.utils.get(guild.emojis, id=eid)
    except Exception:
        return None


async def _clear_reactions(message: discord.Message):
    try:
        await message.clear_reactions()
    except discord.Forbidden:
        # Fall back to removing one by one
        for reaction in message.reactions:
            try:
                await message.clear_reaction(reaction.emoji)
            except Exception:
                pass
    except Exception:
        pass


async def _safe_react(message: discord.Message, emoji_str: str):
    """Add a reaction using 'name:id' format, resolving via guild emojis."""
    guild = message.guild
    if not guild:
        return
    try:
        eid  = int(emoji_str.split(":")[1])
        emoj = discord.utils.get(guild.emojis, id=eid)
        if emoj:
            await message.add_reaction(emoj)
    except Exception as e:
        print(f"[training_apps] react error ({emoji_str}): {e}")


async def _dm(user: discord.User | discord.Member, embed: discord.Embed):
    try:
        await user.send(embed=embed)
    except Exception:
        pass

def _load_pending() -> dict[int, int]:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(PENDING_FILE): return {}
    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        return {int(k): int(v) for k, v in json.load(f).items()}

def _save_pending(data: dict[int, int]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f, indent=2)

# ─────────────────────────── COG ──────────────────────────────────────────────

class TrainingAppsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Tracks message IDs of valid applications so we can verify on reaction
        # {message_id: applicant_user_id}
        self._pending: dict[int, int] = _load_pending()
        # Count of valid application messages since last reminder
        self._app_count: int = 0
        self._lock = asyncio.Lock()

    # ── on_message ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.channel.id != APP_CHANNEL_ID:
            return

        valid, missing = _parse_app(message.content)
        has_image = any(
            a.content_type and a.content_type.startswith("image/")
            for a in message.attachments
        )

        # Check username field matches display name (case-insensitive contains)
        username_mismatch = False
        if valid:
            username_m = re.search(r"(?i)^username\s*:\s*(.+)", message.content, re.MULTILINE)
            if username_m:
                submitted = username_m.group(1).strip()
                display   = message.author.display_name
                if submitted.lower() not in display.lower():
                    username_mismatch = True
                    missing.append(
                        f"`Username:` — `{submitted}` was not found in your server display name. "
                        f"Make sure you enter your Roblox username exactly as it appears in your nickname."
                    )
                    valid = False

        if not valid or not has_image:
            # Build helpful reply
            issues: list[str] = list(missing)
            if not has_image:
                issues.append("an image attachment (screenshot of your pass in FS:RP.)")

            reply_emb = discord.Embed(
                title="Invalid Request",
                description=(
                    "Your request is missing the following:\n"
                    + "\n".join(f"• {i}" for i in issues)
                    + "\n\nPlease resubmit with all required fields and a proof image."
                ),
                colour=discord.Colour.red(),
            )
            try:
                await message.reply(embed=reply_emb, mention_author=True)
            except Exception:
                pass
            await _safe_react(message, REACT_RAID)
            return

        # Valid application
        async with self._lock:
            self._pending[message.id] = message.author.id
            _save_pending(self._pending)
            self._app_count += 1
            count = self._app_count

        await _safe_react(message, REACT_YES)
        await _safe_react(message, REACT_NO)

        # Send format reminder every REMINDER_INTERVAL valid apps
        if count % REMINDER_INTERVAL == 0:
            try:
                await message.channel.send(embed=_format_reminder_embed())
            except Exception:
                pass

    # ── on_raw_reaction_add ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.channel_id != APP_CHANNEL_ID:
            return
        if payload.user_id == self.bot.user.id:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member:
            try:
                member = await guild.fetch_member(payload.user_id)
            except Exception:
                return

        # Check if reactor is an approver
        member_role_ids = {r.id for r in member.roles}
        is_approver = bool(member_role_ids & APPROVER_ROLE_IDS)
        if not is_approver:
            # Remove the non-approver's reaction silently
            try:
                channel = guild.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                await message.remove_reaction(payload.emoji, member)
            except Exception:
                pass
            return

        # Only act on yes/no emojis
        emoji = payload.emoji
        emoji_id = emoji.id

        yes_id  = int(REACT_YES.split(":")[1])
        no_id   = int(REACT_NO.split(":")[1])

        if emoji_id not in (yes_id, no_id):
            return

        # Check this is a tracked application
        async with self._lock:
            applicant_id = self._pending.get(payload.message_id)

        if applicant_id is None:
            return

        channel = guild.get_channel(payload.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return

        applicant = guild.get_member(applicant_id)
        if not applicant:
            try:
                applicant = await guild.fetch_member(applicant_id)
            except Exception:
                applicant = None

        # ── APPROVED ──────────────────────────────────────────────────────────
        if emoji_id == yes_id:
            # Assign roles
            roles_to_add: list[discord.Role] = []
            for rid in ASSIGN_ROLE_IDS:
                role = guild.get_role(rid)
                if role:
                    roles_to_add.append(role)

            if applicant:
                try:
                    await applicant.add_roles(*roles_to_add, reason=f"Role request approved by {member.display_name}")
                except discord.Forbidden:
                    pass
                except Exception as e:
                    print(f"[training_apps] role assign error: {e}")

            # Clear reactions, add check
            await _clear_reactions(message)
            await _safe_react(message, REACT_CHECK)

            # Remove from pending
            async with self._lock:
                self._pending.pop(payload.message_id, None)
                _save_pending(self._pending)

            # DM applicant
            if applicant:
                emb = discord.Embed(
                    title="Request Approved ✅",
                    description=(
                        "Congratulations! Your role request has been **approved**.\n\n"
                        "You have been assigned the required roles. Welcome to the team!\n\n"
                        "Please request a callsign using !cs or /callsign in any command channel."
                    ),
                    colour=discord.Colour.brand_green(),
                )
                await _dm(applicant, emb)

        # ── DENIED ────────────────────────────────────────────────────────────
        elif emoji_id == no_id:
            # Clear reactions, add raid emoji
            await _clear_reactions(message)
            await _safe_react(message, REACT_RAID)

            # Remove from pending
            async with self._lock:
                self._pending.pop(payload.message_id, None)
                _save_pending(self._pending)

            # DM applicant
            if applicant:
                emb = discord.Embed(
                    title="Request Denied ❌",
                    description=(
                        "Unfortunately, your role request was **not approved**\n\n"
                        "This may be because:\n"
                        "• The proof provided is invalid\n"
                        "• The proof is from a previous wave and is no longer valid\n\n"
                        "Please check your proof and resubmit when ready."
                    ),
                    colour=discord.Colour.red(),
                )
                await _dm(applicant, emb)


async def setup(bot: commands.Bot):
    await bot.add_cog(TrainingAppsCog(bot))