"""
callsign.py — FHP Ghost Unit callsign management cog.

Entry points
------------
  !cs              — opens the full panel (ephemeral embed + buttons)
  /callsign        — same panel as slash command

Panel buttons (all members with personnel role):
  • My Callsign       — show your own callsign
  • Request Callsign  — modal + "Assign Lowest" button
  • Browse / List     — all callsigns grouped by section
  • Find by Callsign  — type a number, see who holds it
  • [Admin Menu]      — shown only to ADMIN_ID

Admin menu buttons:
  • Assign Callsign   — modal: user ID + number
  • Remove Callsign   — modal: user ID
  • View All          — same as Browse but includes unmatched
  • Refresh DB        — reads display names, no new assignments

Automatic actions:
  • on_message in promotions channel → remove callsign if section changed, DM member
  • on_member_update → remove callsign if personnel role lost, DM member

Callsign ranges:
  High Command      GU-001 – GU-006
  Senior High Rank  GU-010 – GU-019
  High Rank         GU-020 – GU-035
  Sergeants Program GU-036 – GU-060
  Low Rank + Cadet  GU-061 – GU-250

Storage:
  data/callsigns.json          {str(user_id): "GU-XXX"}
  data/callsign_sections.json  {str(user_id): section_label}
"""

from __future__ import annotations
import json, os, re, asyncio
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

# ─────────────────────────── CONFIG ───────────────────────────────────────────

ADMIN_ID              = 840949634071658507
ROLE_PERSONNEL        = 1317963289518542959
PROMOTIONS_CHANNEL_ID = 1317963343524270192
LOG_CHANNEL_ID        = 1398812728541577247
PANEL_IMAGE_URL       = "https://media.discordapp.net/attachments/1403360987096027268/1408449383925809262/image.png?ex=69b6ba34&is=69b568b4&hm=1333e32082220cc64cd189b22e521c1f6b1d05bb0643587e0d3258817737244a&=&format=webp&quality=lossless&width=1867&height=70"

SECTION_ROLES: dict[int, tuple[str, int, int]] = {
    1318181592719687681: ("High Command",      1,   6),
    1317963237920215111: ("Senior High Rank",  10,  19),
    1317963242819293295: ("High Rank",         20,  35),
    1317963244685758576: ("Sergeants Program", 36,  60),
    1317963249509208115: ("Low Rank",          61, 250),
    1400570836510838835: ("Cadet",             61, 250),
}
SECTION_ROLE_ORDER = [
    1318181592719687681, 1317963237920215111, 1317963242819293295,
    1317963244685758576, 1317963249509208115, 1400570836510838835,
]
SKIP_ROLE_IDS = {1317963293767241808, 1318198109725134930}

DATA_DIR      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
CALLSIGN_FILE = os.path.join(DATA_DIR, "callsigns.json")
SECTIONS_FILE = os.path.join(DATA_DIR, "callsign_sections.json")

# ─────────────────────────── PERSISTENCE ──────────────────────────────────────

def _load() -> dict[str, str]:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CALLSIGN_FILE): return {}
    with open(CALLSIGN_FILE, "r", encoding="utf-8") as f: return json.load(f)

def _save(data: dict[str, str]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CALLSIGN_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)

def _load_secs() -> dict[str, str]:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SECTIONS_FILE): return {}
    with open(SECTIONS_FILE, "r", encoding="utf-8") as f: return json.load(f)

def _save_secs(data: dict[str, str]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SECTIONS_FILE, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)

# ─────────────────────────── PURE HELPERS ─────────────────────────────────────

_CS_RE     = re.compile(r"(?:GU|\U0001D4A2\U0001D4B0)-(\d{3})")
_LOA_RE    = re.compile(r"(?i)^loa\s*\|\s*")
_CS_SEG_RE = re.compile(r"^(?:GU|\U0001D4A2\U0001D4B0)-\d{3}\s*\|\s*")

def _parse_num(cs: str) -> Optional[int]:
    m = _CS_RE.fullmatch(cs.strip())
    return int(m.group(1)) if m else None

def _fmt(num: int) -> str:
    return f"GU-{num:03d}"

def _get_section(member: discord.Member) -> Optional[tuple[str, int, int]]:
    ids = {r.id for r in member.roles}
    for rid in SECTION_ROLE_ORDER:
        if rid in SKIP_ROLE_IDS: continue
        if rid in ids and rid in SECTION_ROLES: return SECTION_ROLES[rid]
    return None

def _in_range(num: int, sec: tuple[str, int, int]) -> bool:
    return sec[1] <= num <= sec[2]

def _used(data: dict[str, str]) -> set[int]:
    out: set[int] = set()
    for cs in data.values():
        n = _parse_num(cs)
        if n: out.add(n)
    return out

def _lowest_free(lo: int, hi: int, used: set[int]) -> Optional[int]:
    for n in range(lo, hi + 1):
        if n not in used: return n
    return None

def _normalise_sec(label: str) -> str:
    return "Low Rank" if label == "Cadet" else label

def _section_for_num(num: int) -> Optional[str]:
    """Return section label for a given callsign number, deduplicating LR/Cadet."""
    seen: set[str] = set()
    for rid in SECTION_ROLE_ORDER:
        if rid not in SECTION_ROLES: continue
        lbl, lo, hi = SECTION_ROLES[rid]
        if lbl in seen: continue
        seen.add(lbl)
        if lo <= num <= hi: return lbl
    return None

# ── Display name helpers ───────────────────────────────────────────────────────

def _decompose(dn: str) -> tuple[str, str, str]:
    dn = dn.strip()
    loa_m = _LOA_RE.match(dn)
    loa   = loa_m.group(0) if loa_m else ""
    rest  = dn[len(loa):]
    cs_m  = _CS_SEG_RE.match(rest)
    cs_s  = cs_m.group(0) if cs_m else ""
    base  = rest[len(cs_s):].strip()
    return loa, cs_s, base

def _extract_cs(dn: str) -> Optional[str]:
    _, cs_s, _ = _decompose(dn)
    if not cs_s: return None
    m = _CS_RE.search(cs_s)
    return _fmt(int(m.group(1))) if m else None

def _build_nick(dn: str, new_cs: Optional[str]) -> str:
    loa, _, base = _decompose(dn)
    loa_str = "LOA | " if loa else ""
    full    = f"{loa_str}{new_cs} | {base}" if new_cs else f"{loa_str}{base}"
    if len(full) > 32:
        overhead = len(full) - len(base)
        base     = base[:max(0, 32 - overhead)]
        full     = f"{loa_str}{new_cs} | {base}" if new_cs else f"{loa_str}{base}"
    return full

async def _update_nick(member: discord.Member, new_cs: Optional[str]):
    try:
        new_nick = _build_nick(member.display_name, new_cs)
        if member.nick != new_nick:
            await member.edit(nick=new_nick, reason="Callsign updated")
    except discord.Forbidden:
        pass
    except Exception as e:
        print(f"[callsign] nick error {member}: {e}")

# ── Shared embed builder for the list ─────────────────────────────────────────

def _build_list_embed(data: dict[str, str]) -> discord.Embed:
    """Build a sectioned callsign list embed."""
    if not data:
        return _emb(title="Callsign List", description="No callsigns assigned.")

    items = sorted(data.items(), key=lambda x: _parse_num(x[1]) or 9999)
    groups: dict[str, list[str]] = {}
    for uid, cs in items:
        num = _parse_num(cs)
        grp = _section_for_num(num) if num else "Unknown"
        groups.setdefault(grp or "Unknown", []).append(f"`{cs}` — <@{uid}>")

    lines: list[str] = []
    seen: set[str] = set()
    for rid in SECTION_ROLE_ORDER:
        if rid not in SECTION_ROLES: continue
        lbl = SECTION_ROLES[rid][0]
        if lbl in seen: continue
        seen.add(lbl)
        if lbl not in groups: continue
        lines += [f"**{lbl}**"] + groups[lbl] + [""]

    desc = "\n".join(lines).strip()
    if len(desc) > 4000: desc = desc[:3997] + "…"
    return _emb(title=f"Callsign List — {len(data)} assigned", description=desc)

def _emb(title: str = "", description: str = "", colour: discord.Colour = discord.Colour.blurple()) -> discord.Embed:
    """Create a standard embed with the panel image set."""
    e = discord.Embed(title=title, description=description, colour=colour)
    e.set_image(url=PANEL_IMAGE_URL)
    return e

# ─────────────────────────── COG ──────────────────────────────────────────────

class CallsignCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self._lock = asyncio.Lock()

    # ── Logging ───────────────────────────────────────────────────────────────

    async def _log(self, guild: Optional[discord.Guild], msg: str):
        print(f"[callsign] {msg}")
        if not guild: return
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            try: await ch.send(embed=_emb(description=msg))
            except Exception: pass

    # ── Core write ops ────────────────────────────────────────────────────────

    async def _assign(self, guild: discord.Guild, target: discord.Member, num: int,
                      actor: discord.Member, *, update_nick: bool = True) -> tuple[bool, str]:
        async with self._lock:
            sec = _get_section(target)
            if not sec: return False, f"{target.mention} has no section role."
            if not _in_range(num, sec):
                _, lo, hi = sec
                return False, f"`{_fmt(num)}` is not in {target.mention}'s range (`GU-{lo:03d}`–`GU-{hi:03d}`)."
            data = _load(); u = _used(data); old = data.get(str(target.id))
            if num in u and old != _fmt(num): return False, f"`{_fmt(num)}` is already taken."
            data[str(target.id)] = _fmt(num); _save(data)
            s = _load_secs(); s[str(target.id)] = sec[0]; _save_secs(s)
        cs = _fmt(num)
        if update_nick: await _update_nick(target, cs)
        await self._log(guild, f"✏️ {actor.mention} assigned `{cs}` to {target.mention}" + (f" (was `{old}`)" if old else "") + ".")
        return True, f"Assigned `{cs}` to {target.mention}."

    async def _remove(self, guild: discord.Guild, target: discord.Member, actor: discord.Member,
                      *, dm: Optional[str] = None, update_nick: bool = True) -> tuple[bool, str]:
        async with self._lock:
            data = _load(); old = data.pop(str(target.id), None)
            if not old: return False, f"{target.mention} has no callsign."
            _save(data); s = _load_secs(); s.pop(str(target.id), None); _save_secs(s)
        if update_nick: await _update_nick(target, None)
        if dm:
            try: await target.send(embed=_emb(title="Callsign Removed", description=dm, colour=discord.Colour.orange()))
            except Exception: pass
        await self._log(guild, f"🗑️ {actor.mention} removed `{old}` from {target.mention}.")
        return True, f"Removed `{old}` from {target.mention}."

    async def _self_assign(self, interaction: discord.Interaction, num: int,
                           sec: tuple[str, int, int]) -> tuple[bool, str]:
        member = interaction.user; guild = interaction.guild
        _, lo, hi = sec
        if not _in_range(num, sec):
            return False, f"`{_fmt(num)}` is not in your range (`GU-{lo:03d}`–`GU-{hi:03d}`)."
        async with self._lock:
            data = _load(); u = _used(data); old = data.get(str(member.id))
            if old == _fmt(num): return False, f"You already have callsign `{old}`."
            if num in u: return False, f"`{_fmt(num)}` is already taken. Use **Find by Callsign** to check who has it."
            data[str(member.id)] = _fmt(num); _save(data)
            s = _load_secs(); s[str(member.id)] = sec[0]; _save_secs(s)
        cs = _fmt(num)
        await _update_nick(member, cs)
        await self._log(guild, f"📋 {member.mention} self-requested `{cs}`" + (f" (was `{old}`)" if old else "") + ".")
        return True, cs

    # ── Shared panel builder ──────────────────────────────────────────────────

    def _panel_embed(self, member: discord.Member) -> discord.Embed:
        data    = _load()
        cs      = data.get(str(member.id))
        sec     = _get_section(member)
        is_admin = member.id == ADMIN_ID

        emb = _emb(title="GU Callsign Panel")
        emb.add_field(name="Your Callsign", value=f"`{cs}`" if cs else "None", inline=True)
        if sec:
            label, lo, hi = sec
            u    = _used(data)
            free = sum(1 for n in range(lo, hi + 1) if n not in u)
            emb.add_field(name="Your Section", value=label, inline=True)
            emb.add_field(name="Free Numbers", value=str(free), inline=True)
        emb.set_footer(text=f"{member.display_name}")
        return emb

    async def _send_panel(self, ctx_or_interaction, member: discord.Member):
        emb  = self._panel_embed(member)
        view = CallsignPanelView(self, member)
        if isinstance(ctx_or_interaction, discord.Interaction):
            await ctx_or_interaction.response.send_message(embed=emb, view=view, ephemeral=True)
        else:
            await ctx_or_interaction.reply(embed=emb, view=view, ephemeral=True, mention_author=False)

    # ── !cs ───────────────────────────────────────────────────────────────────

    @commands.command(name="cs", aliases=["callsign"])
    async def cs_cmd(self, ctx: commands.Context):
        """Open the callsign panel."""
        if not ctx.guild:
            await ctx.reply("Guild only.", mention_author=False); return
        member = ctx.author
        if not any(r.id == ROLE_PERSONNEL for r in member.roles) and member.id != ADMIN_ID:
            await ctx.reply("You don't have the required role.", mention_author=False); return
        await self._send_panel(ctx, member)

    # ── /callsign ─────────────────────────────────────────────────────────────

    @app_commands.command(name="callsign", description="Open the callsign management panel.")
    async def callsign_slash(self, interaction: discord.Interaction):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Guild only.", ephemeral=True); return
        if not any(r.id == ROLE_PERSONNEL for r in member.roles) and member.id != ADMIN_ID:
            await interaction.response.send_message("You don't have the required role.", ephemeral=True); return
        await self._send_panel(interaction, member)

    # ── !callsign_refresh (admin only, prefix only) ───────────────────────────

    @commands.command(name="callsign_refresh")
    async def callsign_refresh(self, ctx: commands.Context):
        """Admin only: rebuild DB from display names. Does NOT assign new callsigns."""
        if ctx.author.id != ADMIN_ID:
            await ctx.reply("You don't have permission.", mention_author=False); return
        if not ctx.guild:
            await ctx.reply("Guild only.", mention_author=False); return

        msg = await ctx.reply("⏳ Scanning display names...", mention_author=False)
        async with self._lock:
            pr = ctx.guild.get_role(ROLE_PERSONNEL)
            if not pr:
                await msg.edit(content="❌ Personnel role not found."); return
            new_data: dict[str, str] = {}
            new_secs: dict[str, str] = {}
            found: list[tuple[discord.Member, str]] = []
            no_cs: list[discord.Member]             = []
            conflicts: list[tuple[discord.Member, str, str]] = []
            claimed: dict[int, str] = {}

            for member in pr.members:
                cs = _extract_cs(member.display_name)
                if not cs: no_cs.append(member); continue
                num = _parse_num(cs)
                if num is None: no_cs.append(member); continue
                if num in claimed: conflicts.append((member, cs, claimed[num])); continue
                new_data[str(member.id)] = cs; claimed[num] = str(member.id)
                found.append((member, cs))
                sec = _get_section(member)
                if sec: new_secs[str(member.id)] = sec[0]

            _save(new_data); _save_secs(new_secs)

        lines = ["✅ **Callsign DB refreshed from display names.**",
                 f"• **{len(found)}** callsigns read",
                 f"• **{len(no_cs)}** members have no callsign in their name"]
        if conflicts:
            lines.append(f"• ⚠️ **{len(conflicts)}** conflicts (first keeper wins):")
            for m, cs, other in conflicts[:10]:
                lines.append(f"  > {m.mention} `{cs}` conflicts with <@{other}>")
        await msg.edit(content="\n".join(lines))
        await self._log(ctx.guild, f"🔄 {ctx.author.mention} ran callsign_refresh. {len(found)} read, {len(no_cs)} no callsign, {len(conflicts)} conflicts.")

    # ── Promotions channel listener ───────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        if message.channel.id != PROMOTIONS_CHANNEL_ID: return
        if not message.mentions: return
        await asyncio.sleep(5)
        data = _load(); secs = _load_secs()
        for user in message.mentions:
            try:
                member = message.guild.get_member(user.id) or await message.guild.fetch_member(user.id)
            except Exception: continue
            cs = data.get(str(member.id))
            if not cs: continue
            old_lbl = secs.get(str(member.id))
            new_sec = _get_section(member)
            if not new_sec: continue
            if old_lbl and _normalise_sec(old_lbl) != _normalise_sec(new_sec[0]):
                await self._remove(message.guild, member, message.guild.me,
                    dm=(f"Your callsign **{cs}** has been removed because you were promoted to "
                        f"**{new_sec[0]}**.\n\nUse `/callsign` or `!cs` to request a new one in your section's range."))

    # ── Personnel role removed ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if ROLE_PERSONNEL in {r.id for r in before.roles} and ROLE_PERSONNEL not in {r.id for r in after.roles}:
            data = _load(); cs = data.get(str(after.id))
            if cs:
                await self._remove(after.guild, after, after.guild.me,
                    dm=(f"Your callsign **{cs}** has been removed because you no longer hold "
                        f"the personnel role in FHP Ghost Unit.\n\nIf this is an error, contact an administrator."))


# ─────────────────────────── MAIN PANEL VIEW ──────────────────────────────────

class CallsignPanelView(discord.ui.View):
    def __init__(self, cog: CallsignCog, member: discord.Member):
        super().__init__(timeout=180)
        self.cog    = cog
        self.member = member
        self.owner_id = member.id
        if member.id == ADMIN_ID:
            self.add_item(AdminMenuButton(cog))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="My Callsign", style=discord.ButtonStyle.primary, row=0)
    async def my_cs_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = _load()
        cs   = data.get(str(interaction.user.id))
        if cs:
            emb = _emb(title="Your Callsign", description=f"**{cs}**")
            num = _parse_num(cs)
            if num:
                lbl = _section_for_num(num)
                if lbl: emb.add_field(name="Section", value=lbl, inline=True)
        else:
            emb = _emb(title="No Callsign", description="You don't have a callsign assigned yet. Use **Request Callsign** to get one.")
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="Request Callsign", style=discord.ButtonStyle.success, row=0)
    async def request_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not any(r.id == ROLE_PERSONNEL for r in member.roles):
            await interaction.response.send_message("You don't have the required role.", ephemeral=True); return
        sec = _get_section(member)
        if not sec:
            await interaction.response.send_message("You don't have a section role. Contact an admin.", ephemeral=True); return
        label, lo, hi = sec
        data = _load(); u = _used(data)
        free = len([n for n in range(lo, hi + 1) if n not in u])
        current = data.get(str(member.id))
        emb = _emb(title="Request a Callsign")
        emb.add_field(name="Section", value=label, inline=True)
        emb.add_field(name="Range",   value=f"`GU-{lo:03d}` – `GU-{hi:03d}`", inline=True)
        emb.add_field(name="Current", value=f"`{current}`" if current else "None", inline=True)
        emb.add_field(name="Free",    value=str(free), inline=True)
        await interaction.response.send_message(embed=emb, view=CallsignRequestView(self.cog, sec, member.id), ephemeral=True)

    @discord.ui.button(label="Browse / List", style=discord.ButtonStyle.secondary, row=0)
    async def browse_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        emb = _build_list_embed(_load())
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(label="Find by Callsign", style=discord.ButtonStyle.secondary, row=0)
    async def find_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FindByCallsignModal(self.cog))


# ─────────────────────────── REQUEST VIEW ─────────────────────────────────────

class CallsignRequestView(discord.ui.View):
    def __init__(self, cog: CallsignCog, section: tuple[str, int, int], owner_id: int):
        super().__init__(timeout=120)
        self.cog = cog; self.section = section; self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This panel isn't for you.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Enter a Number", style=discord.ButtonStyle.primary)
    async def enter_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CallsignNumberModal(self.cog, self.section))

    @discord.ui.button(label="Assign Lowest Free", style=discord.ButtonStyle.success)
    async def lowest_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        label, lo, hi = self.section
        num = _lowest_free(lo, hi, _used(_load()))
        if num is None:
            await interaction.response.send_message(f"No callsigns available in your range (`GU-{lo:03d}`–`GU-{hi:03d}`).", ephemeral=True); return
        ok, result = await self.cog._self_assign(interaction, num, self.section)
        if not ok:
            await interaction.response.send_message(result, ephemeral=True); return
        await interaction.response.send_message(
            embed=_emb(title="Callsign Assigned", description=f"✅ You have been assigned **{result}** (lowest free in {label}).", colour=discord.Colour.brand_green()),
            ephemeral=True)


# ─────────────────────────── ADMIN MENU ───────────────────────────────────────

class AdminMenuButton(discord.ui.Button):
    def __init__(self, cog: CallsignCog):
        super().__init__(label="Admin Menu", style=discord.ButtonStyle.danger, row=1)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("Admin only.", ephemeral=True); return
        emb = _emb(title="Callsign Admin Menu", colour=discord.Colour.red())
        emb.description = "Assign or remove callsigns for any member, view the full list, or refresh the database from display names."
        await interaction.response.send_message(embed=emb, view=CallsignAdminView(self.cog), ephemeral=True)


class CallsignAdminView(discord.ui.View):
    def __init__(self, cog: CallsignCog):
        super().__init__(timeout=120); self.cog = cog

    @discord.ui.button(label="Assign Callsign", style=discord.ButtonStyle.success, row=0)
    async def assign_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CallsignAssignModal(self.cog))

    @discord.ui.button(label="Remove Callsign", style=discord.ButtonStyle.danger, row=0)
    async def remove_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CallsignRemoveModal(self.cog))

    @discord.ui.button(label="View All", style=discord.ButtonStyle.primary, row=0)
    async def view_all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(embed=_build_list_embed(_load()), ephemeral=True)

    @discord.ui.button(label="Refresh DB from Names", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != ADMIN_ID:
            await interaction.response.send_message("Admin only.", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        async with self.cog._lock:
            pr = guild.get_role(ROLE_PERSONNEL) if guild else None
            if not pr:
                await interaction.followup.send("❌ Personnel role not found.", ephemeral=True); return
            new_data: dict[str, str] = {}
            new_secs: dict[str, str] = {}
            found: list[tuple[discord.Member, str]] = []
            no_cs: list[discord.Member]             = []
            conflicts: list[tuple[discord.Member, str, str]] = []
            claimed: dict[int, str] = {}
            for member in pr.members:
                cs = _extract_cs(member.display_name)
                if not cs: no_cs.append(member); continue
                num = _parse_num(cs)
                if num is None: no_cs.append(member); continue
                if num in claimed: conflicts.append((member, cs, claimed[num])); continue
                new_data[str(member.id)] = cs; claimed[num] = str(member.id)
                found.append((member, cs))
                sec = _get_section(member)
                if sec: new_secs[str(member.id)] = sec[0]
            _save(new_data); _save_secs(new_secs)

        lines = [f"✅ **Refreshed.** {len(found)} read, {len(no_cs)} without callsign" + (f", {len(conflicts)} conflicts." if conflicts else ".")]
        for m, cs, other in conflicts[:5]:
            lines.append(f"> {m.mention} `{cs}` conflicts with <@{other}>")
        await interaction.followup.send("\n".join(lines), ephemeral=True)
        await self.cog._log(guild, f"🔄 {interaction.user.mention} ran DB refresh via admin menu.")


# ─────────────────────────── MODALS ───────────────────────────────────────────

class FindByCallsignModal(discord.ui.Modal, title="Find Member by Callsign"):
    number = discord.ui.TextInput(
        label="Callsign number (e.g. 072)",
        placeholder="3-digit number",
        min_length=1, max_length=3, required=True
    )

    def __init__(self, cog: CallsignCog):
        super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.number.value.strip().lstrip("0") or "0"
        if not raw.isdigit():
            await interaction.response.send_message("Digits only.", ephemeral=True); return
        num = int(raw); cs = _fmt(num)
        data = _load()
        uid  = next((k for k, v in data.items() if _parse_num(v) == num), None)
        emb  = _emb(title=f"Callsign {cs}")
        if uid:
            sec_lbl = _section_for_num(num)
            emb.description = f"**{cs}** is held by <@{uid}>."
            if sec_lbl: emb.add_field(name="Section", value=sec_lbl, inline=True)
        else:
            emb.description = f"**{cs}** is not assigned to anyone."
            sec_lbl = _section_for_num(num)
            if sec_lbl: emb.add_field(name="Section", value=sec_lbl, inline=True)
            emb.add_field(name="Status", value="✅ Free", inline=True)
        await interaction.response.send_message(embed=emb, ephemeral=True)


class CallsignNumberModal(discord.ui.Modal, title="Request a Callsign"):
    number = discord.ui.TextInput(label="Callsign number", placeholder="3-digit number, e.g. 072", min_length=1, max_length=3, required=True)

    def __init__(self, cog: CallsignCog, section: tuple[str, int, int]):
        super().__init__(); self.cog = cog; self.section = section
        label, lo, hi = section
        self.number.label       = f"Number ({lo:03d}–{hi:03d} for {label})"
        self.number.placeholder = f"e.g. {lo:03d}"

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.number.value.strip()
        if not raw.isdigit():
            await interaction.response.send_message("Digits only, e.g. `072`.", ephemeral=True); return
        ok, result = await self.cog._self_assign(interaction, int(raw), self.section)
        if not ok:
            await interaction.response.send_message(result, ephemeral=True); return
        await interaction.response.send_message(
            embed=_emb(title="Callsign Assigned", description=f"✅ You have been assigned **{result}**.", colour=discord.Colour.brand_green()),
            ephemeral=True)


class CallsignAssignModal(discord.ui.Modal, title="Assign Callsign"):
    user_id = discord.ui.TextInput(label="User ID", placeholder="Discord user ID", required=True)
    number  = discord.ui.TextInput(label="Callsign number (e.g. 005)", placeholder="3-digit number", min_length=1, max_length=3, required=True)

    def __init__(self, cog: CallsignCog):
        super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        try:
            uid = int(self.user_id.value.strip())
            target = guild.get_member(uid) or await guild.fetch_member(uid)
        except Exception:
            await interaction.response.send_message("Invalid user ID or member not in server.", ephemeral=True); return
        raw = self.number.value.strip()
        if not raw.isdigit():
            await interaction.response.send_message("Digits only.", ephemeral=True); return
        ok, msg = await self.cog._assign(guild, target, int(raw), interaction.user)
        await interaction.response.send_message(
            embed=_emb(description=msg, colour=discord.Colour.brand_green() if ok else discord.Colour.red()),
            ephemeral=True)


class CallsignRemoveModal(discord.ui.Modal, title="Remove Callsign"):
    user_id = discord.ui.TextInput(label="User ID", placeholder="Discord user ID", required=True)

    def __init__(self, cog: CallsignCog):
        super().__init__(); self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        try:
            uid = int(self.user_id.value.strip())
            target = guild.get_member(uid) or await guild.fetch_member(uid)
        except Exception:
            await interaction.response.send_message("Invalid user ID or member not in server.", ephemeral=True); return
        ok, msg = await self.cog._remove(guild, target, interaction.user)
        await interaction.response.send_message(
            embed=_emb(description=msg, colour=discord.Colour.brand_green() if ok else discord.Colour.red()),
            ephemeral=True)


# ─────────────────────────── SETUP ────────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(CallsignCog(bot))