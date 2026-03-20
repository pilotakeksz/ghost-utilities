"""
roster.py — FHP Ghost Unit roster cog.

Generates troopers.html from Discord role members, downloads Roblox avatars,
and pushes the result to GitHub.

Sections are determined by Discord role IDs (SECTION_ROLES / SECTION_ROLE_ORDER).
HICOM is identified by callsign number 1–6 (matches generate_roster.py logic).
HICOM avatars are cached and never re-downloaded or pushed to GitHub.
Regular avatars are re-used if already on disk; pass reload_all=True to force refresh.

Config constants at the top — fill in GITHUB_REPO, GITHUB_TOKEN, and
PROJECT_ROOT before deploying.
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import re
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

# ─────────────────────────── CONFIG ───────────────────────────────────────────

# GitHub
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO   = os.getenv("GITHUB_REPO",  "YOUR_ORG/YOUR_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

# Where the website repo lives on disk (parent of assets/, troopers.html, etc.)
PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "website")
AVATARS_DIR  = os.path.join(PROJECT_ROOT, "assets", "avatars")

# Who can run !roster manually
OWNER_ID = 840949634071658507

# Personnel role — everyone on the roster must have this
ROLE_PERSONNEL = 1317963289518542959

# Section roles → (display label, section key)
SECTION_ROLES = {
    1318181592719687681: ("High Command",      "hicom"),
    1317963237920215111: ("Senior High Rank",  "shr"),
    1317963242819293295: ("High Rank",         "hr"),
    1317963244685758576: ("Sergeants Program", "sp"),
    1317963249509208115: ("Low Rank",          "lr"),
    1400570836510838835: ("Cadet",             "cadet"),
}

# Priority order — first match wins when a member has multiple section roles
SECTION_ROLE_ORDER = [
    1318181592719687681,  # HICOM
    1317963237920215111,  # SHR
    1317963242819293295,  # HR
    1317963244685758576,  # SP
    1317963249509208115,  # LR
    1400570836510838835,  # CADET
]

# Specialty roles
ROLE_SRT  = 1426729477362159670
ROLE_HSPU = 1400862387619500144

FALLBACK_AVATAR = "https://tr.rbxcdn.com/6c6b8e6b7b7e7b7b7b7b7b7b7b7b7b/420/420/AvatarHeadshot/Png"

# Callsign numbers 1–6 are treated as HICOM (mirrors generate_roster.py logic)
HICOM_CALLSIGN_MAX = 6

# Discord user IDs whose avatars are fully static — never pulled from Roblox,
# never overwritten, never pushed to GitHub. File must exist at assets/avatars/<discord_id>.png
STATIC_AVATAR_DISCORD_IDS = {
    1278294632496889935,
    840949634071658507,
    756539004299771976,
    807631247886123008,
}

# ─────────────────────────── HELPERS ──────────────────────────────────────────

def _clean_role_name(name: str) -> str:
    """Strip '𝐅𝐇𝐏 𝐆𝐡𝐨𝐬𝐭 | ' or any '… | ' prefix from a role name."""
    if "|" in name:
        return name.split("|", 1)[1].strip()
    return name.strip()


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", str(name)) or "unknown"


def _parse_callsign_and_name(display_name: str) -> tuple[str, str]:
    """
    Formats handled:
      LOA | GU-123 | Name   → callsign=GU-123, name=Name
      GU-123 | Name          → callsign=GU-123, name=Name
      GU-123                 → callsign=GU-123, name=GU-123
    Returns (callsign, roblox_username).
    """
    dn = re.sub(r"(?i)^loa\s*\|\s*", "", display_name.strip())
    parts = [p.strip() for p in dn.split("|")]
    for i, part in enumerate(parts):
        if re.match(r"(?i)gu-?\d+", part):
            callsign = part
            name = parts[i + 1] if i + 1 < len(parts) else part
            return callsign, name
    if len(parts) >= 2:
        return parts[0], parts[1]
    return parts[0], parts[0]


def _callsign_num(cs: str) -> int:
    m = re.search(r"(\d+)", cs)
    return int(m.group(1)) if m else 9999


def _is_hicom(member: discord.Member, callsign: str) -> bool:
    """HICOM requires BOTH the HICOM role AND a callsign number of 1–6.
    Callsign-only check is insufficient — low numbers can appear in other names."""
    has_hicom_role = any(r.id == HICOM_ROLE_ID for r in member.roles)
    return has_hicom_role and _callsign_num(callsign) <= HICOM_CALLSIGN_MAX


HICOM_ROLE_ID = 1318181592719687681  # Never used as sectionKey — HICOM is decided by callsign

# Status roles (On Duty, LOA) — sit above rank roles in hierarchy, must be ignored
STATUS_ROLE_IDS = {
    1317963293767241808,  # On Duty
    1318198109725134930,  # Leave of Absence
}

# All role IDs to skip when walking the section hierarchy
_SKIP_ROLE_IDS = STATUS_ROLE_IDS | {HICOM_ROLE_ID}


def _get_section(member: discord.Member) -> tuple[str, str]:
    """Return (section_label, section_key) for the member's highest real section role.
    Skips the HICOM role (decided by callsign) and status roles (On Duty / LOA)."""
    role_ids = {r.id for r in member.roles}
    for rid in SECTION_ROLE_ORDER:
        if rid in _SKIP_ROLE_IDS:
            continue
        if rid in role_ids:
            label, key = SECTION_ROLES[rid]
            return label, key
    return "Low Rank", "lr"


def _get_rank_name(member: discord.Member) -> str:
    """
    Return the member's rank: the highest-position role that contains '|'
    but is NOT one of the section roles.
    Falls back to the highest section role name.
    """
    skip_ids = set(SECTION_ROLES.keys()) | _SKIP_ROLE_IDS
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.id in skip_ids:
            continue
        if "|" in role.name:
            return _clean_role_name(role.name)
    # Fallback: highest real section role name
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.id in set(SECTION_ROLES.keys()) and role.id not in _SKIP_ROLE_IDS:
            return _clean_role_name(role.name)
    return ""


def _get_specialties(member: discord.Member) -> tuple[str, Optional[str]]:
    role_ids = {r.id for r in member.roles}
    h = ROLE_HSPU in role_ids
    s = ROLE_SRT  in role_ids
    if h and s:
        return "HSPU • SRT", "both"
    if h:
        return "HSPU", "hspu"
    if s:
        return "SRT", "srt"
    return "", None


def _escape(s: str) -> str:
    if not s:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

# ─────────────────────────── ROBLOX API ───────────────────────────────────────

async def _get_roblox_user_id(session: aiohttp.ClientSession, username: str) -> Optional[int]:
    try:
        async with session.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                return None
            data = await r.json()
            if data.get("data"):
                return data["data"][0]["id"]
    except Exception as e:
        print(f"  Roblox user lookup error ({username}): {e}")
    return None


async def _get_avatar_url(session: aiohttp.ClientSession, user_id: int) -> str:
    try:
        url = (
            f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
            f"?userIds={user_id}&size=420x420&format=Png&isCircular=false"
        )
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            r.raise_for_status()
            d = await r.json()
            if d.get("data") and "imageUrl" in d["data"][0]:
                return d["data"][0]["imageUrl"]
    except Exception as e:
        print(f"  Avatar URL error ({user_id}): {e}")
    return FALLBACK_AVATAR


async def _download_avatar(session: aiohttp.ClientSession, url: str, path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(8192):
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"  Avatar download error ({path}): {e}")
        return False

# ─────────────────────────── HTML BUILDER ─────────────────────────────────────

def _roster_card(t: dict, is_hicom: bool = False) -> str:
    name       = _escape(t.get("roblox") or t.get("name", "unknown"))
    rank       = _escape(t.get("rank", ""))
    callsign   = _escape(t.get("callsign", ""))
    avatar     = _escape(t.get("avatarPath") or FALLBACK_AVATAR)
    spec_label = t.get("specialties", "")
    spec_kind  = t.get("specialtiesKind")

    spec_html = ""
    if spec_label:
        if spec_kind == "both":
            spec_html = f'<p class="specialties specialties--both">{_escape(spec_label)}</p>'
        elif spec_kind == "hspu":
            spec_html = f'<p class="specialties specialties--hspu">{_escape(spec_label)}</p>'
        elif spec_kind == "srt":
            spec_html = f'<p class="specialties specialties--srt">{_escape(spec_label)}</p>'

    card_class = "leadership-card" if is_hicom else "roster-card"
    return f"""            <div class="{card_class}">
              <img src="{avatar}" alt="{name}" class="avatar" />
              <p class="name">{name}</p>
              <p class="rank">{rank}</p>
              <p class="callsign">{callsign}</p>
              {spec_html}
            </div>"""


# Section order for the rendered page (HICOM is handled separately above)
SECTION_ORDER = [
    ("shr",   "Senior High Rank"),
    ("hr",    "High Rank"),
    ("sp",    "Sergeants Program"),
    ("lr",    "Low Rank"),
    ("cadet", "Cadet"),
]


def build_html(hicom: list, regulars: list) -> str:
    cards_hicom = "\n".join(_roster_card(t, is_hicom=True) for t in hicom)

    sections_html = []
    for suffix, title in SECTION_ORDER:
        tier = [t for t in regulars if t.get("sectionKey") == suffix]
        if not tier:
            continue
        cards = "\n".join(_roster_card(t) for t in tier)
        sections_html.append(
            f"""        <div class="rank-section roster-tier--{suffix}">
          <h3 class="rank-title">{_escape(title)}</h3>
          <div class="roster-grid">
{cards}
          </div>
        </div>"""
        )

    sections_body = "\n".join(sections_html)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>FHP Ghost Unit Troopers</title>
  <link rel="stylesheet" href="css/main.css" />
  <link rel="stylesheet" href="css/roster.css" />
  <style>
    .specialties {{
      padding: 2px 6px; border-radius: 4px; display: inline-block;
      font-size: 0.9em; font-weight: bold; color: #fff; text-align: center;
    }}
    .specialties--hspu {{ background-color: rgba(111,148,187,1); }}
    .specialties--srt  {{ background-color: rgba(186,101,115,1); }}
    @keyframes fadeBlueRed {{
      0%   {{ background-color: rgba(111,148,187,1); }}
      100% {{ background-color: rgba(186,101,115,1); }}
    }}
    .specialties--both {{ animation: fadeBlueRed 3s infinite alternate; }}
  </style>
</head>
<body>
  <div id="particles-js"></div>
  <div class="page-wrap">
    <header>
      <div class="nav-wrap">
        <div class="brand">
          <img src="assets/logo.png" alt="FHP Ghost Unit logo" class="logo" />
          <span class="eyebrow">FSRP • Ghost Unit</span>
          <h1>Trooper Roster</h1>
        </div>
        <nav>
          <a href="index.html">Home</a>
          <a href="handbook.html">Handbook</a>
          <a href="chain-of-command.html">Chain of Command</a>
          <a href="vehicle-guidelines.html">Vehicle Guidelines</a>
          <a class="active" href="troopers.html">Troopers</a>
          <a href="official_media.html">Official Media</a>
        </nav>
      </div>
    </header>
    <main class="wrap">
      <section class="intro">
        <span class="tag">Active Roster</span>
      </section>
      <section class="section">
        <div class="hicom-section">
          <h3 class="rank-title">High Command</h3>
          <div class="leadership-row">
{cards_hicom}
          </div>
        </div>
{sections_body}
      </section>
    </main>
    <footer>
      <span id="y"></span> FSRP • Florida Highway Patrol Ghost Unit
    </footer>
  </div>
  <script src="https://cdn.jsdelivr.net/particles.js/2.0.0/particles.min.js"></script>
  <script src="js/app.js"></script>
</body>
</html>
"""

# ─────────────────────────── GITHUB PUSH ──────────────────────────────────────

async def _get_file_sha(session: aiohttp.ClientSession, api_url: str, headers: dict) -> Optional[str]:
    try:
        async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                d = await r.json()
                return d.get("sha")
    except Exception:
        pass
    return None


async def _github_push(session: aiohttp.ClientSession, path_in_repo: str, content_bytes: bytes, message: str) -> bool:
    """Create or update a single file in the GitHub repo via the Contents API.
    Retries once on 409 (SHA conflict) with a freshly fetched SHA."""
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path_in_repo}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    encoded = base64.b64encode(content_bytes).decode()

    for attempt in range(2):
        sha = await _get_file_sha(session, api_url, headers)
        payload: dict = {
            "message": message,
            "content": encoded,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        try:
            async with session.put(
                api_url, headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status in (200, 201):
                    return True
                if r.status == 409 and attempt == 0:
                    continue  # re-fetch SHA and retry
                text = await r.text()
                print(f"  GitHub push failed ({r.status}): {text[:200]}")
                return False
        except Exception as e:
            print(f"  GitHub push error: {e}")
            return False

    return False


async def _push_all_files(
    session: aiohttp.ClientSession,
    troopers_html: str,
    avatar_pairs: list[tuple[str, str]],
) -> bool:
    """Push troopers.html then all regular avatars. Returns True if all succeeded."""
    stamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    ok = True

    if not await _github_push(
        session,
        "troopers.html",
        troopers_html.encode("utf-8"),
        f"roster: auto-update {stamp}",
    ):
        ok = False

    for repo_path, local_path in avatar_pairs:
        if not os.path.isfile(local_path):
            continue
        with open(local_path, "rb") as f:
            data = f.read()
        if not await _github_push(
            session, repo_path, data,
            f"roster: avatar {os.path.basename(local_path)} {stamp}",
        ):
            ok = False

    return ok

# ─────────────────────────── CORE GENERATOR ───────────────────────────────────

async def generate_roster(guild: discord.Guild, reload_all: bool = False) -> tuple[bool, str]:
    """
    Build troopers.html from Discord roles, push to GitHub.

    - Section (shr/hr/sp/lr/cadet/hicom) comes from Discord role IDs.
    - HICOM is additionally confirmed by callsign number 1–6.
    - HICOM avatars: cached by roblox username, never re-downloaded or pushed.
    - Regular avatars: cached by Roblox user ID; re-downloaded if reload_all=True.
    - Members whose Roblox lookup fails still appear with the fallback avatar.

    Returns (success, message).
    """
    personnel_role = guild.get_role(ROLE_PERSONNEL)
    if not personnel_role:
        return False, "Personnel role not found in guild."

    os.makedirs(AVATARS_DIR, exist_ok=True)

    members = personnel_role.members
    print(f"[roster] Processing {len(members)} members...")

    troopers: list[dict] = []

    async with aiohttp.ClientSession() as session:
        for member in members:
            callsign, roblox_username = _parse_callsign_and_name(member.display_name)
            section_label, section_key = _get_section(member)
            rank       = _get_rank_name(member)
            spec_label, spec_kind = _get_specialties(member)

            # HICOM requires the HICOM role AND callsign number 1–6
            is_hicom = _is_hicom(member, callsign)

            avatar_path_rel   = None
            avatar_path_local = None

            if member.id in STATIC_AVATAR_DISCORD_IDS:
                # ── Static: pre-placed image, never touched ─────────────────
                fname             = f"{member.id}.png"
                avatar_path_local = os.path.join(AVATARS_DIR, fname)
                avatar_path_rel   = f"assets/avatars/{fname}"
                if not os.path.isfile(avatar_path_local):
                    print(f"  [static] WARNING: {member.display_name!r} — missing assets/avatars/{fname}")
                    avatar_path_rel = FALLBACK_AVATAR

            elif is_hicom:
                # ── HICOM: use stored file by username; never re-download or push
                fname             = f"{_sanitize_filename(roblox_username)}.png"
                avatar_path_local = os.path.join(AVATARS_DIR, fname)
                avatar_path_rel   = f"assets/avatars/{fname}"

                if not os.path.isfile(avatar_path_local):
                    # File genuinely missing — fetch once, then stays cached forever
                    user_id = await _get_roblox_user_id(session, roblox_username)
                    if user_id:
                        url = await _get_avatar_url(session, user_id)
                        if await _download_avatar(session, url, avatar_path_local):
                            print(f"  [HICOM] Cached avatar for {roblox_username}")
                        else:
                            avatar_path_rel = FALLBACK_AVATAR
                    else:
                        print(f"  [HICOM] {member.display_name!r} — Roblox lookup failed, using fallback")
                        avatar_path_rel = FALLBACK_AVATAR

            else:
                # ── Regular: download by Roblox user ID ────────────────────
                user_id = await _get_roblox_user_id(session, roblox_username)
                if user_id:
                    fname             = f"{user_id}.png"
                    avatar_path_local = os.path.join(AVATARS_DIR, fname)
                    avatar_path_rel   = f"assets/avatars/{fname}"

                    if not os.path.isfile(avatar_path_local) or reload_all:
                        url = await _get_avatar_url(session, user_id)
                        if not await _download_avatar(session, url, avatar_path_local):
                            avatar_path_rel = FALLBACK_AVATAR
                else:
                    print(f"  [roster] {member.display_name!r} — Roblox lookup failed for {roblox_username!r}, using fallback")

            troopers.append({
                "callsign":        callsign,
                "name":            roblox_username,
                "roblox":          roblox_username,
                "rank":            rank,
                "sectionLabel":    section_label,
                "sectionKey":      section_key,
                "specialties":     spec_label,
                "specialtiesKind": spec_kind,
                "avatarPath":      avatar_path_rel or FALLBACK_AVATAR,
                "_avatarLocal":    avatar_path_local,
                "_isHicom":        is_hicom,
                "_isStatic":       member.id in STATIC_AVATAR_DISCORD_IDS,
            })

        # Sort by callsign number within each section
        troopers.sort(key=lambda t: _callsign_num(t["callsign"]))

        hicom    = [t for t in troopers if t["_isHicom"]]
        regulars = [t for t in troopers if not t["_isHicom"]]

        html = build_html(hicom, regulars)

        # Write locally
        out_path = os.path.join(PROJECT_ROOT, "troopers.html")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        # Collect avatar pairs — HICOM and static users excluded (stored, not generated)
        avatar_pairs: list[tuple[str, str]] = []
        for t in troopers:
            if t["_isHicom"] or t["_isStatic"]:
                continue
            local = t.get("_avatarLocal")
            if local and os.path.isfile(local):
                avatar_pairs.append((t["avatarPath"], local))

        print(f"[roster] Pushing {1 + len(avatar_pairs)} files to GitHub...")
        success = await _push_all_files(session, html, avatar_pairs)

    msg = f"✅ Roster updated — {len(troopers)} members, {len(avatar_pairs)} avatars pushed."
    if not success:
        msg = "⚠️ Roster generated but one or more GitHub pushes failed. Check logs."
    return success, msg

# ─────────────────────────── COG ──────────────────────────────────────────────

class RosterCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.daily_refresh.start()

    def cog_unload(self):
        self.daily_refresh.cancel()

    @tasks.loop(time=dt.time(hour=0, minute=0, tzinfo=dt.timezone.utc))
    async def daily_refresh(self):
        for guild in self.bot.guilds:
            role = guild.get_role(ROLE_PERSONNEL)
            if role:
                print("[roster] Running daily refresh...")
                ok, msg = await generate_roster(guild)
                print(f"[roster] {msg}")
                return  # Only process the first matching guild

    @daily_refresh.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    @commands.command(name="roster")
    async def roster_cmd(self, ctx: commands.Context, *, flags: str = ""):
        """
        Manually regenerate and push the roster. Owner only.
        Pass --reload-all to force re-download of all regular avatars.
        """
        if ctx.author.id != OWNER_ID:
            await ctx.reply("You don't have permission to use this command.", mention_author=False)
            return

        reload_all = "--reload-all" in flags.lower()
        note = " (forcing avatar reload)" if reload_all else ""
        msg = await ctx.reply(f"⏳ Generating roster{note}...", mention_author=False)
        try:
            ok, result = await generate_roster(ctx.guild, reload_all=reload_all)
            await msg.edit(content=result)
        except Exception as e:
            await msg.edit(content=f"❌ Roster generation failed: {e}")
            raise


async def setup(bot: commands.Bot):
    await bot.add_cog(RosterCog(bot))