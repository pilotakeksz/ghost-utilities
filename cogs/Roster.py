from __future__ import annotations

import base64
import datetime as dt
import os
import re
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO   = os.getenv("GITHUB_REPO",  "YOUR_ORG/YOUR_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

PROJECT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "website")
AVATARS_DIR  = os.path.join(PROJECT_ROOT, "assets", "avatars")

OWNER_ID = 840949634071658507

ROLE_PERSONNEL = 1317963289518542959

SECTION_ROLES = {
    1318181592719687681: ("High Command",      "hicom"),
    1317963237920215111: ("Senior High Rank",  "shr"),
    1317963242819293295: ("High Rank",         "hr"),
    1317963244685758576: ("Sergeants Program", "sp"),
    1317963249509208115: ("Low Rank",          "lr"),
    1400570836510838835: ("Cadet",             "cadet"),
}

SECTION_ROLE_ORDER = [
    1318181592719687681,
    1317963237920215111,
    1317963242819293295,
    1317963244685758576,
    1317963249509208115,
    1400570836510838835,
]

ROLE_SRT  = 1426729477362159670
ROLE_HSPU = 1400862387619500144

FALLBACK_AVATAR = "https://tr.rbxcdn.com/6c6b8e6b7b7e7b7b7b7b7b7b7b7b7b/420/420/AvatarHeadshot/Png"

HICOM_CALLSIGN_MAX = 6

STATIC_AVATAR_DISCORD_IDS = {
    1278294632496889935,
    840949634071658507,
    756539004299771976,
    807631247886123008,
}

HICOM_ROLE_ID = 1318181592719687681

STATUS_ROLE_IDS = {
    1317963293767241808,
    1318198109725134930,
}

_SKIP_ROLE_IDS = STATUS_ROLE_IDS | {HICOM_ROLE_ID}


def _clean_role_name(name: str) -> str:
    if "|" in name:
        return name.split("|", 1)[1].strip()
    return name.strip()


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^\w\-.]", "_", str(name)) or "unknown"


def _parse_callsign_and_name(display_name: str) -> tuple[str, str]:
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
    has_hicom_role = any(r.id == HICOM_ROLE_ID for r in member.roles)
    return has_hicom_role and _callsign_num(callsign) <= HICOM_CALLSIGN_MAX


def _get_section(member: discord.Member) -> tuple[str, str]:
    role_ids = {r.id for r in member.roles}
    for rid in SECTION_ROLE_ORDER:
        if rid in _SKIP_ROLE_IDS:
            continue
        if rid in role_ids:
            label, key = SECTION_ROLES[rid]
            return label, key
    return "Low Rank", "lr"


def _get_rank_name(member: discord.Member) -> str:
    skip_ids = set(SECTION_ROLES.keys()) | _SKIP_ROLE_IDS
    for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
        if role.id in skip_ids:
            continue
        if "|" in role.name:
            return _clean_role_name(role.name)
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


async def _get_file_sha(session: aiohttp.ClientSession, api_url: str, headers: dict) -> Optional[str]:
    try:
        async with session.get(api_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                d = await r.json()
                return d.get("sha")
    except Exception:
        pass
    return None


async def _github_batch_push(
    session: aiohttp.ClientSession,
    files: list[tuple[str, bytes]],
    message: str,
) -> bool:
    """Push multiple files in a single commit using the Git Trees API."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"https://api.github.com/repos/{GITHUB_REPO}"

    try:
        async with session.get(
            f"{base}/git/ref/heads/{GITHUB_BRANCH}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            r.raise_for_status()
            ref_data = await r.json()
        latest_commit_sha = ref_data["object"]["sha"]

        async with session.get(
            f"{base}/git/commits/{latest_commit_sha}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            r.raise_for_status()
            commit_data = await r.json()
        base_tree_sha = commit_data["tree"]["sha"]

        tree_items = []
        for repo_path, content_bytes in files:
            async with session.post(
                f"{base}/git/blobs",
                headers=headers,
                json={"content": base64.b64encode(content_bytes).decode(), "encoding": "base64"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                r.raise_for_status()
                blob = await r.json()
            tree_items.append({
                "path": repo_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            })

        async with session.post(
            f"{base}/git/trees",
            headers=headers,
            json={"base_tree": base_tree_sha, "tree": tree_items},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as r:
            r.raise_for_status()
            new_tree = await r.json()

        async with session.post(
            f"{base}/git/commits",
            headers=headers,
            json={
                "message": message,
                "tree": new_tree["sha"],
                "parents": [latest_commit_sha],
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as r:
            r.raise_for_status()
            new_commit = await r.json()

        async with session.patch(
            f"{base}/git/refs/heads/{GITHUB_BRANCH}",
            headers=headers,
            json={"sha": new_commit["sha"]},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            r.raise_for_status()

        return True

    except Exception as e:
        print(f"  GitHub batch push error: {e}")
        return False


async def generate_roster(guild: discord.Guild, reload_all: bool = False) -> tuple[bool, str]:
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
            rank = _get_rank_name(member)
            spec_label, spec_kind = _get_specialties(member)
            is_hicom = _is_hicom(member, callsign)

            avatar_path_rel   = None
            avatar_path_local = None

            if member.id in STATIC_AVATAR_DISCORD_IDS:
                fname             = f"{member.id}.png"
                avatar_path_local = os.path.join(AVATARS_DIR, fname)
                avatar_path_rel   = f"assets/avatars/{fname}"
                if not os.path.isfile(avatar_path_local):
                    print(f"  [static] WARNING: {member.display_name!r} — missing assets/avatars/{fname}")
                    avatar_path_rel = FALLBACK_AVATAR

            elif is_hicom:
                fname             = f"{_sanitize_filename(roblox_username)}.png"
                avatar_path_local = os.path.join(AVATARS_DIR, fname)
                avatar_path_rel   = f"assets/avatars/{fname}"

                if not os.path.isfile(avatar_path_local):
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

        troopers.sort(key=lambda t: _callsign_num(t["callsign"]))

        hicom    = [t for t in troopers if t["_isHicom"]]
        regulars = [t for t in troopers if not t["_isHicom"]]

        html = build_html(hicom, regulars)

        out_path = os.path.join(PROJECT_ROOT, "troopers.html")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        files_to_push: list[tuple[str, bytes]] = [
            ("troopers.html", html.encode("utf-8"))
        ]

        for t in troopers:
            if t["_isHicom"] or t["_isStatic"]:
                continue
            local = t.get("_avatarLocal")
            if local and os.path.isfile(local):
                with open(local, "rb") as f:
                    files_to_push.append((t["avatarPath"], f.read()))

        stamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        print(f"[roster] Pushing {len(files_to_push)} files in one commit...")
        success = await _github_batch_push(
            session,
            files_to_push,
            f"roster: auto-update {stamp}",
        )

    msg = f"✅ Roster updated — {len(troopers)} members, {len(files_to_push) - 1} avatars pushed."
    if not success:
        msg = "⚠️ Roster generated but GitHub push failed. Check logs."
    return success, msg


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
                return

    @daily_refresh.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    @commands.command(name="roster")
    async def roster_cmd(self, ctx: commands.Context, *, flags: str = ""):
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