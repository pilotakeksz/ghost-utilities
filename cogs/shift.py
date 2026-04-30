from __future__ import annotations
import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import uuid
import os
import datetime as dt
import asyncio
from typing import Dict, Any, Optional, List, Tuple
import glob

IMAGE_URL = "https://cdn.discordapp.com/attachments/1403360987096027268/1408449383925809262/image.png?ex=69b41734&is=69b2c5b4&hm=c4f6e557a9d3583555a610f7ffd9a3874719ad17df17f93bc67fbce1b0efc3f5&"

ROLE_MANAGE_REQUIRED = 1317963289518542959
ROLE_SHIFT_ON        = 1318198109725134930
ROLE_BREAK           = 1385724780845727774
ROLE_ADMIN           = 1318181592719687681
ROLE_ON_DUTY         = 1318198109725134930
ROLE_SRT             = 1426729477362159670
ROLE_HSPU            = 1400862387619500144

TRAINEE_ROLES        = {1400570836510838835, 1480298283200024606}
ROLE_PROBATION       = 1317963256484069387

LOG_CHANNEL_ID             = 1398812728541577247
MSG_COUNT_CHANNEL_ID       = 1318199799085928458
PROMOTIONS_CHANNEL_ID      = 1317963343524270192
INFRACTIONS_CHANNEL_ID     = 1317963346326323250   # pings here = consecutive miss events
ALLOWED_SHIFT_CHANNEL_ID   = 1318174456744775703
ALLOWED_SHIFT_CATEGORIES   = [
    1398675655771816187
]

GU_QUOTA_MINUTES      = 90
GU_PROMO_MINUTES      = 180

SRT_QUOTA_SHIFTS  = 1
HSPU_QUOTA_MINUTES = 90
GU_MIN_FOR_SUB    = 45

QUOTA_ROLE_0         = 1317963293767241808
QUOTA_ROLE_ADMIN_0   = ROLE_ADMIN

PROMO_COOLDOWN_SUPERINTENDENT  = 1365262290236084264
PROMO_COOLDOWN_COLONEL         = 1317963238838632448
PROMO_COOLDOWN_LT_COLONEL      = 1317963239308525692
PROMO_COOLDOWN_MAJOR           = 1317963240374009977
PROMO_COOLDOWN_CAPTAIN_2ND     = 1458852963094233119
PROMO_COOLDOWN_CAPTAIN_1ST     = 1317963241720250368
PROMO_COOLDOWN_2ND_LT          = 1459727193377865850
PROMO_COOLDOWN_1ST_LT          = 1317963243360223253
PROMO_COOLDOWN_DEFAULT_DAYS    = 6

WARN_THRESHOLD       = 45
STRIKE_THRESHOLD     = 30
DEMOTION_THRESHOLD   = 15

SHIFT_TYPE_NORMAL = "GU"
SHIFT_TYPE_SRT    = "SRT"
SHIFT_TYPE_HSPU   = "HSPU"
SHIFT_TYPES       = [SHIFT_TYPE_NORMAL, SHIFT_TYPE_SRT, SHIFT_TYPE_HSPU]

DATA_DIR    = "data"
LOGS_DIR    = os.path.join(DATA_DIR, "logs")
STATE_FILE  = os.path.join(DATA_DIR, "shift_state.json")
RECORDS_FILE = os.path.join(DATA_DIR, "shift_records.json")
META_FILE   = os.path.join(DATA_DIR, "meta.json")
MISSES_FILE  = os.path.join(DATA_DIR, "shift_misses.json")
ARCHIVE_FILE = os.path.join(DATA_DIR, "shift_archive.json")  # previous wave records

ACTIVE_LOAS_FILE = os.path.join(DATA_DIR, "active_loas.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def get_active_loa(user_id: int) -> Optional[dt.datetime]:
    try:
        with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        end_str = data.get(str(user_id))
        if not end_str:
            return None
        d = dt.datetime.fromisoformat(end_str)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        else:
            d = d.astimezone(dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        return d if d > now else None
    except Exception:
        return None

def is_on_loa(user_id: int) -> bool:
    return get_active_loa(user_id) is not None

def is_trainee(member: discord.Member) -> bool:
    return any(r.id in TRAINEE_ROLES for r in member.roles)

def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)

def ts_to_int(ts: dt.datetime) -> int:
    return int(ts.timestamp())

def int_to_ts(t: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(t, tz=dt.timezone.utc)

def human_td(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s or not parts: parts.append(f"{s}s")
    return " ".join(parts)

def colour_ok()   -> discord.Colour: return discord.Colour.brand_green()
def colour_warn() -> discord.Colour: return discord.Colour.orange()
def colour_err()  -> discord.Colour: return discord.Colour.red()
def colour_info() -> discord.Colour: return discord.Colour.blurple()

def _rank_cooldown_days(roles: List[discord.Role]) -> int:
    role_ids = {r.id for r in roles}
    rank_map = [
        (PROMO_COOLDOWN_SUPERINTENDENT, 41),
        (PROMO_COOLDOWN_COLONEL,        34),
        (PROMO_COOLDOWN_LT_COLONEL,     34),
        (PROMO_COOLDOWN_MAJOR,          20),
        (PROMO_COOLDOWN_CAPTAIN_2ND,    13),
        (PROMO_COOLDOWN_CAPTAIN_1ST,    13),
        (PROMO_COOLDOWN_2ND_LT,         13),
        (PROMO_COOLDOWN_1ST_LT,         13),
    ]
    for role_id, days in rank_map:
        if role_id and role_id in role_ids:
            return days
    return PROMO_COOLDOWN_DEFAULT_DAYS


class Store:
    def __init__(self):
        self.state: Dict[str, Any]   = {}
        self.records: List[Dict[str, Any]] = []
        self.meta: Dict[str, Any]    = {}
        self.misses: Dict[str, int]  = {}
        self.miss_wave_ts: Dict[str, int] = {}
        # archive: list of {"wave_reset_ts": int, "records": [...], "label": str}
        self.archive: List[Dict[str, Any]] = []
        self.load()

    def load(self):
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                self.state = json.load(f)
        if os.path.exists(RECORDS_FILE):
            with open(RECORDS_FILE, "r", encoding="utf-8") as f:
                self.records = json.load(f)
        if os.path.exists(META_FILE):
            with open(META_FILE, "r", encoding="utf-8") as f:
                self.meta = json.load(f)
        if os.path.exists(MISSES_FILE):
            with open(MISSES_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict) and "misses" in raw:
                    self.misses = raw["misses"]
                    self.miss_wave_ts = raw.get("miss_wave_ts", {})
                else:
                    self.misses = raw
                    self.miss_wave_ts = {}
        if os.path.exists(ARCHIVE_FILE):
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                self.archive = json.load(f)
        self.meta.setdefault("logging_enabled", True)
        self.meta.setdefault("last_reset_ts", ts_to_int(utcnow()))
        self.meta.setdefault("last_promotions", {})
        self.meta.setdefault("infractions", {})
        self.meta.setdefault("cooldown_extensions", {})
        self.meta.setdefault("admin_cooldowns", {})
        self.meta.setdefault("excuses", {})
        self.meta.setdefault("last_friday_quota_reminder", "")
        # infraction_ping_ts: {user_id_str: last_unix_ts when pinged in INFRACTIONS_CHANNEL_ID}
        # Used to deduplicate: only one miss per calendar week per user.
        self.meta.setdefault("infraction_ping_ts", {})

    def save(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
        with open(RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.records, f, indent=2)
        with open(META_FILE, "w", encoding="utf-8") as f:
            json.dump(self.meta, f, indent=2)
        with open(MISSES_FILE, "w", encoding="utf-8") as f:
            json.dump({"misses": self.misses, "miss_wave_ts": self.miss_wave_ts}, f, indent=2)
        with open(ARCHIVE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.archive, f, indent=2)

    def is_on_shift(self, user_id: int) -> bool:
        return str(user_id) in self.state

    def get_user_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.state.get(str(user_id))

    def start_shift(self, user_id: int, shift_type: str = SHIFT_TYPE_NORMAL):
        now = ts_to_int(utcnow())
        self.state[str(user_id)] = {
            "start_ts": now,
            "accum": 0,
            "on_break": False,
            "last_ts": now,
            "breaks": 0,
            "shift_type": shift_type,
        }
        self.save()

    def toggle_break(self, user_id: int) -> bool:
        now = ts_to_int(utcnow())
        st = self.state[str(user_id)]
        if st["on_break"]:
            st["on_break"] = False
            st["last_ts"] = now
            self.save()
            return False
        else:
            st["accum"] += max(0, now - st["last_ts"])
            st["on_break"] = True
            st["breaks"] += 1
            self.save()
            return True

    def stop_shift(self, user_id: int) -> Optional[Dict[str, Any]]:
        st = self.state.get(str(user_id))
        if not st:
            return None
        now = ts_to_int(utcnow())
        if not st["on_break"]:
            st["accum"] += max(0, now - st["last_ts"])
        record = {
            "id": uuid.uuid4().hex[:12],
            "user_id": user_id,
            "start_ts": st["start_ts"],
            "end_ts": now,
            "duration": st["accum"],
            "breaks": st.get("breaks", 0),
            "shift_type": st.get("shift_type", SHIFT_TYPE_NORMAL),
        }
        del self.state[str(user_id)]
        self.records.append(record)
        self.save()
        return record

    def void_shift(self, user_id: int) -> bool:
        if str(user_id) in self.state:
            del self.state[str(user_id)]
            self.save()
            return True
        return False

    def void_record_by_id(self, rec_id: str) -> bool:
        for i, r in enumerate(self.records):
            if r["id"] == rec_id:
                del self.records[i]
                self.save()
                return True
        return False

    def _records_for_wave(self, wave_index: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get records for current wave (None) or archive index (0=most recent past wave)."""
        if wave_index is None:
            return self.records
        if not self.archive or wave_index >= len(self.archive):
            return []
        return self.archive[wave_index]["records"]

    def total_for_user(self, user_id: int, shift_type: Optional[str] = None,
                       wave_index: Optional[int] = None) -> int:
        records = self._records_for_wave(wave_index)
        total = sum(
            r["duration"] for r in records
            if r["user_id"] == user_id and (shift_type is None or r.get("shift_type") == shift_type)
        )
        if wave_index is None:
            st = self.state.get(str(user_id))
            if st and (shift_type is None or st.get("shift_type") == shift_type):
                if not st["on_break"]:
                    now = ts_to_int(utcnow())
                    total += st["accum"] + max(0, now - st["last_ts"])
                else:
                    total += st["accum"]
        return total

    def total_gu_equiv(self, user_id: int, wave_index: Optional[int] = None) -> int:
        """All shift types combined (GU+SRT+HSPU). Used for GU quota checks."""
        return (
            self.total_for_user(user_id, SHIFT_TYPE_NORMAL, wave_index) +
            self.total_for_user(user_id, SHIFT_TYPE_SRT,    wave_index) +
            self.total_for_user(user_id, SHIFT_TYPE_HSPU,   wave_index)
        )

    def shift_count_for_user(self, user_id: int, shift_type: Optional[str] = None,
                              min_duration_seconds: int = 0,
                              wave_index: Optional[int] = None) -> int:
        records = self._records_for_wave(wave_index)
        count = sum(
            1 for r in records
            if r["user_id"] == user_id
            and (shift_type is None or r.get("shift_type") == shift_type)
            and r["duration"] >= min_duration_seconds
        )
        if wave_index is None:
            st = self.state.get(str(user_id))
            if st and (shift_type is None or st.get("shift_type") == shift_type):
                elapsed = st["accum"]
                if not st["on_break"]:
                    elapsed += max(0, ts_to_int(utcnow()) - st["last_ts"])
                if elapsed >= min_duration_seconds:
                    count += 1
        return count

    def get_statistics(self) -> Tuple[int, int]:
        return len(self.records), sum(r["duration"] for r in self.records)

    def can_be_promoted(self, user_id: int, member_roles: List[discord.Role]) -> bool:
        """Return True if member is off cooldown (or was never promoted)."""
        last_promo = self.meta["last_promotions"].get(str(user_id), 0)
        if last_promo == 0:
            return True
        admin_days = self.meta.get("admin_cooldowns", {}).get(str(user_id))
        if admin_days is not None:
            cooldown_days = admin_days
        else:
            cooldown_days = _rank_cooldown_days(member_roles)
        days_since = (ts_to_int(utcnow()) - last_promo) / (24 * 60 * 60)
        return days_since >= cooldown_days

    def get_infractions(self, user_id: int) -> Dict[str, int]:
        return self.meta["infractions"].get(str(user_id), {"demotions": 0, "strikes": 0, "warns": 0})

    def add_infraction(self, user_id: int, infraction_type: str):
        if str(user_id) not in self.meta["infractions"]:
            self.meta["infractions"][str(user_id)] = {"demotions": 0, "strikes": 0, "warns": 0}
        self.meta["infractions"][str(user_id)][infraction_type] += 1
        self.save()

    def is_excused(self, user_id: int) -> bool:
        current_reset_ts = self.meta.get("last_reset_ts", ts_to_int(utcnow()))
        return self.meta.get("excuses", {}).get(str(user_id)) == current_reset_ts

    def add_excuse(self, user_id: int):
        current_reset_ts = self.meta.get("last_reset_ts", ts_to_int(utcnow()))
        self.meta["excuses"][str(user_id)] = current_reset_ts
        self.save()

    def remove_excuse(self, user_id: int) -> bool:
        if str(user_id) in self.meta.get("excuses", {}):
            del self.meta["excuses"][str(user_id)]
            self.save()
            return True
        return False

    def get_misses(self, user_id: int) -> int:
        return self.misses.get(str(user_id), 0)

    def record_infraction_ping(self, user_id: int) -> bool:
        """
        Called when a user is pinged in INFRACTIONS_CHANNEL_ID.
        Increments consecutive miss counter, deduplicated to once per ISO calendar week.
        Returns True if a new miss was recorded, False if already recorded this week.
        All data is persisted to disk immediately.
        """
        now = utcnow()
        current_week = now.isocalendar()[:2]  # (year, week_number)

        last_ping_ts = self.meta["infraction_ping_ts"].get(str(user_id))
        if last_ping_ts is not None:
            last_dt = int_to_ts(last_ping_ts)
            last_week = last_dt.isocalendar()[:2]
            if last_week == current_week:
                # Already recorded a miss for this week; skip.
                return False

        # New miss for this week.
        self.misses[str(user_id)] = self.get_misses(user_id) + 1
        self.miss_wave_ts[str(user_id)] = self.meta.get("last_reset_ts", ts_to_int(now))
        self.meta["infraction_ping_ts"][str(user_id)] = ts_to_int(now)
        self.save()
        return True

    def increment_miss(self, user_id: int):
        """Legacy: direct increment without dedup. Used during void_all for members who
        were not pinged in the infractions channel but still missed quota.
        Prefer record_infraction_ping for channel-driven misses."""
        self.misses[str(user_id)] = self.get_misses(user_id) + 1
        current_reset_ts = self.meta.get("last_reset_ts", 0)
        self.miss_wave_ts[str(user_id)] = current_reset_ts
        self.save()

    def clear_misses(self, user_id: int):
        changed = False
        if str(user_id) in self.misses:
            del self.misses[str(user_id)]
            changed = True
        if str(user_id) in self.miss_wave_ts:
            del self.miss_wave_ts[str(user_id)]
            changed = True
        # Also clear the per-week dedup timestamp so they start fresh.
        if str(user_id) in self.meta.get("infraction_ping_ts", {}):
            del self.meta["infraction_ping_ts"][str(user_id)]
            changed = True
        if changed:
            self.save()

    def archive_wave(self, label: str = ""):
        """Save current records to archive before reset. Call before void_all."""
        entry = {
            "wave_reset_ts": self.meta.get("last_reset_ts", ts_to_int(utcnow())),
            "label": label or int_to_ts(self.meta.get("last_reset_ts", ts_to_int(utcnow()))).strftime("%Y-%m-%d"),
            "records": list(self.records),
        }
        self.archive.insert(0, entry)  # newest first
        self.archive = self.archive[:12]
        self.save()

    def get_archive_labels(self) -> List[Tuple[int, str]]:
        return [(i, w["label"]) for i, w in enumerate(self.archive)]


class ShiftTypeView(discord.ui.View):
    def __init__(self, cog: "ShiftCog", manage_view: "ShiftManageView"):
        super().__init__(timeout=60)
        self.cog = cog
        self.manage_view = manage_view

    async def _start(self, interaction: discord.Interaction, shift_type: str):
        cog   = self.cog
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            return
        if not cog.store.meta.get("logging_enabled", True) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_info("Shift logging is currently disabled."), view=self.manage_view)
            return
        if cog.store.is_on_shift(user.id):
            await interaction.response.edit_message(
                embed=cog.embed_warn("You're already on a shift."), view=self.manage_view)
            return

        loa_end = get_active_loa(user.id)
        if loa_end is not None:
            await cog.log_event(
                guild,
                f"⚠️ **LOA VIOLATION** — {user.mention} attempted to start a **{shift_type}** shift "
                f"while on active LOA (ends <t:{int(loa_end.timestamp())}:F>). Shift was **not started**.",
                actor=user
            )
            embed = cog.embed_warn(
                f"⚠️ **You are currently on Leave of Absence** (ends <t:{int(loa_end.timestamp())}:R>).\n\n"
                "Personnel on LOA may not participate in shifts, events, or trainings. "
                "This attempt has been logged. If you believe this is an error, contact an admin."
            )
            await interaction.response.edit_message(embed=embed, view=self.manage_view)
            return

        cog.store.start_shift(user.id, shift_type)
        role_on    = guild.get_role(ROLE_SHIFT_ON)
        role_break = guild.get_role(ROLE_BREAK)
        try:
            if role_break and role_break in user.roles:
                await user.remove_roles(role_break, reason="Shift start")
            if role_on:
                await user.add_roles(role_on, reason="Shift start")
        except discord.Forbidden:
            pass
        await cog.log_event(guild, f"🟢 {user.mention} started a **{shift_type}** shift.", actor=user)
        embed = await cog.build_manage_embed(user)
        await interaction.response.edit_message(embed=embed, view=self.manage_view)
        try:
            await cog.update_on_duty_message()
        except Exception:
            pass

    @discord.ui.button(label="🔵 GU Shift", style=discord.ButtonStyle.primary)
    async def gu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, SHIFT_TYPE_NORMAL)

    @discord.ui.button(label="🔴 SRT Shift", style=discord.ButtonStyle.danger)
    async def srt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, SHIFT_TYPE_SRT)

    @discord.ui.button(label="🟠 HSPU Shift", style=discord.ButtonStyle.secondary)
    async def hspu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, SHIFT_TYPE_HSPU)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.cog.build_manage_embed(interaction.user)
        await interaction.response.edit_message(embed=embed, view=self.manage_view)


class ShiftManageView(discord.ui.View):
    def __init__(self, bot: commands.Bot, owner_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.bot      = bot
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None:
            return True
        if interaction.user.id != self.owner_id:
            try:
                await interaction.response.send_message(
                    "Only the user who opened this panel can use these buttons.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    @discord.ui.button(label="Start Shift", style=discord.ButtonStyle.success, custom_id="shift_start")
    async def start_shift_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: ShiftCog = interaction.client.get_cog("ShiftCog")  # type: ignore
        assert cog is not None
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            return
        if not cog.store.meta.get("logging_enabled", True) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_info("Shift logging is currently disabled."), view=self)
            return
        if not any(r.id == ROLE_MANAGE_REQUIRED for r in user.roles) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_error("You do not have permission to manage shifts."), view=self)
            return
        st = cog.store.get_user_state(user.id)
        if st:
            if st.get("on_break"):
                cog.store.toggle_break(user.id)
                role_on    = guild.get_role(ROLE_SHIFT_ON)
                role_break = guild.get_role(ROLE_BREAK)
                try:
                    if role_break and role_break in user.roles:
                        await user.remove_roles(role_break, reason="Resumed shift")
                    if role_on and role_on not in user.roles:
                        await user.add_roles(role_on, reason="Resumed shift")
                except discord.Forbidden:
                    pass
                await cog.log_event(guild, f"⏯️ {user.mention} resumed their shift (returned from break).", actor=user)
                embed = await cog.build_manage_embed(user)
                await interaction.response.edit_message(embed=embed, view=self)
                try:
                    await cog.update_on_duty_message()
                except Exception:
                    pass
                return
            await interaction.response.edit_message(
                embed=cog.embed_warn("You're already on shift."), view=self)
            return

        type_view = ShiftTypeView(cog, self)
        embed = cog.embed_info("Select your shift type:")
        embed.add_field(name="🔵 GU Shift",   value="Regular Ghost Unit shift. 2h/week quota.", inline=False)
        embed.add_field(name="🔴 SRT Shift",  value="Special Response Team shift. 1 shift (≥15 min)/week quota.", inline=False)
        embed.add_field(name="🟠 HSPU Shift", value=f"HSPU shift. {HSPU_QUOTA_MINUTES}min/week quota.", inline=False)
        await interaction.response.edit_message(embed=embed, view=type_view)

    @discord.ui.button(label="Toggle Break", style=discord.ButtonStyle.secondary, custom_id="shift_break")
    async def break_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: ShiftCog = interaction.client.get_cog("ShiftCog")  # type: ignore
        assert cog is not None
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            return
        if not cog.store.meta.get("logging_enabled", True) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_info("Shift logging is currently disabled."), view=self)
            return
        if not any(r.id == ROLE_MANAGE_REQUIRED for r in user.roles) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_error("You do not have permission to manage shifts."), view=self)
            return
        st = cog.store.get_user_state(user.id)
        if not st:
            await interaction.response.edit_message(
                embed=cog.embed_warn("You are not on a shift."), view=self)
            return
        now_on_break = cog.store.toggle_break(user.id)
        role_on    = guild.get_role(ROLE_SHIFT_ON)
        role_break = guild.get_role(ROLE_BREAK)
        try:
            if now_on_break:
                if role_on and role_on in user.roles:
                    await user.remove_roles(role_on, reason="Shift break")
                if role_break:
                    await user.add_roles(role_break, reason="Shift break")
                await cog.log_event(guild, f"⏸️ {user.mention} started a break.", actor=user)
            else:
                if role_break and role_break in user.roles:
                    await user.remove_roles(role_break, reason="Shift resume")
                if role_on:
                    await user.add_roles(role_on, reason="Shift resume")
                await cog.log_event(guild, f"▶️ {user.mention} ended their break.", actor=user)
        except discord.Forbidden:
            pass
        embed = await cog.build_manage_embed(user)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stop Shift", style=discord.ButtonStyle.danger, custom_id="shift_stop")
    async def stop_shift_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: ShiftCog = interaction.client.get_cog("ShiftCog")  # type: ignore
        assert cog is not None
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            return
        if not cog.store.meta.get("logging_enabled", True) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_info("Shift logging is currently disabled."), view=self)
            return
        if not any(r.id == ROLE_MANAGE_REQUIRED for r in user.roles) and not is_trainee(user):
            await interaction.response.edit_message(
                embed=cog.embed_error("You do not have permission to manage shifts."), view=self)
            return
        st = cog.store.get_user_state(user.id)
        if not st:
            await interaction.response.edit_message(
                embed=cog.embed_warn("You are not on a shift."), view=self)
            return
        record     = cog.store.stop_shift(user.id)
        role_on    = guild.get_role(ROLE_SHIFT_ON)
        role_break = guild.get_role(ROLE_BREAK)
        try:
            if role_on and role_on in user.roles:
                await user.remove_roles(role_on, reason="Shift stop")
            if role_break and role_break in user.roles:
                await user.remove_roles(role_break, reason="Shift stop")
        except discord.Forbidden:
            pass
        shift_type = record.get("shift_type", SHIFT_TYPE_NORMAL)
        await cog.log_event(
            guild,
            f"🔴 {user.mention} stopped a **{shift_type}** shift. "
            f"ID: `{record['id']}` Duration: **{human_td(record['duration'])}**",
            actor=user
        )
        embed = await cog.build_manage_embed(user)
        await interaction.response.edit_message(embed=embed, view=self)
        try:
            await cog.update_on_duty_message()
        except Exception:
            pass


class ShiftLeaderboardView(discord.ui.View):
    def __init__(self, cog, guild, wave_index: Optional[int] = None):
        super().__init__(timeout=120)
        self.cog        = cog
        self.guild      = guild
        self.wave_index = wave_index

    async def _send(self, interaction: discord.Interaction, mode: str, title: str, colour: discord.Colour):
        wave_label = ""
        if self.wave_index is not None:
            labels = self.cog.store.get_archive_labels()
            if self.wave_index < len(labels):
                wave_label = f" — Wave {labels[self.wave_index][1]}"
        lines = await self.cog._build_leaderboard_lines(self.guild, filter_mode=mode, wave_index=self.wave_index)
        emb = self.cog.base_embed(f"{title}{wave_label}", colour)
        emb.description = "\n".join(lines)
        await interaction.response.edit_message(embed=emb, view=self)

    @discord.ui.button(label="All (GU+SRT+HSPU)", style=discord.ButtonStyle.primary, row=0)
    async def all_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "all", "Leaderboard — Total Time", colour_info())

    @discord.ui.button(label="GU Only", style=discord.ButtonStyle.primary, row=0)
    async def gu_only_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "gu_only", "Leaderboard — GU Only", colour_info())

    @discord.ui.button(label="✅ Met", style=discord.ButtonStyle.success, row=0)
    async def met_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "leaderboard_met", "Leaderboard — Met Quota", colour_ok())

    @discord.ui.button(label="❌ Not Met", style=discord.ButtonStyle.danger, row=0)
    async def notmet_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "leaderboard_notmet", "Leaderboard — Not Met", colour_err())

    @discord.ui.button(label="⬜ Exempt", style=discord.ButtonStyle.secondary, row=1)
    async def exempt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "exempt", "Leaderboard — Exempt", discord.Colour.light_grey())

    @discord.ui.button(label="🔴 SRT", style=discord.ButtonStyle.danger, row=1)
    async def srt_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "srt", "SRT Leaderboard", colour_err())

    @discord.ui.button(label="🟠 HSPU", style=discord.ButtonStyle.secondary, row=1)
    async def hspu_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "hspu", "HSPU Leaderboard", colour_warn())


class ShiftListsView(discord.ui.View):
    def __init__(self, cog, guild, infractions):
        super().__init__(timeout=180)
        self.cog         = cog
        self.guild       = guild
        self.infractions = infractions
        self.show_time   = False

    async def _refresh(self, interaction: discord.Interaction):
        if self.show_time:
            embed = await self.cog._build_time_embed(self.guild)
        else:
            embed = await self.cog._build_infractions_embed(self.infractions)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📊 Show Shift Time", style=discord.ButtonStyle.secondary)
    async def toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.show_time = not self.show_time
        button.label = "⚠️ Show Infractions" if self.show_time else "📊 Show Shift Time"
        await self._refresh(interaction)

    @discord.ui.button(label="Get Copy-Pastable Text", style=discord.ButtonStyle.primary)
    async def copy_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        text = self._generate_infractions_text()
        await interaction.response.send_message(f"```\n{text}\n```", ephemeral=True)

    @discord.ui.button(label="Remove from List", style=discord.ButtonStyle.danger)
    async def remove_infraction(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Type entries to remove, e.g. `I1 I3 P2`.\n"
            "`I<n>` removes infraction entry n, `P<n>` removes promotion entry n.",
            ephemeral=True)
        def check(m):
            return m.author.id == interaction.user.id and m.channel == interaction.channel
        try:
            msg = await self.cog.bot.wait_for("message", check=check, timeout=60)
        except Exception:
            await interaction.channel.send("Timed out.")
            return

        tokens = msg.content.upper().split()
        infraction_indices = []
        promotion_indices  = []
        for tok in tokens:
            if tok.startswith("I") and tok[1:].isdigit():
                infraction_indices.append(int(tok[1:]))
            elif tok.startswith("P") and tok[1:].isdigit():
                promotion_indices.append(int(tok[1:]))

        all_infractions = (
            self.infractions.get("demotions", []) +
            self.infractions.get("strikes", [])   +
            self.infractions.get("warns", [])
        )

        removed = []

        for idx in sorted(set(infraction_indices), reverse=True):
            if 1 <= idx <= len(all_infractions):
                member = all_infractions[idx - 1][0]
                for cat in ["demotions", "strikes", "warns"]:
                    before = len(self.infractions.get(cat, []))
                    self.infractions[cat] = [
                        e for e in self.infractions.get(cat, []) if e[0].id != member.id
                    ]
                    if len(self.infractions.get(cat, [])) < before:
                        removed.append(f"I{idx} ({member.mention})")
                        break

        promotions = self.infractions.get("promotions", [])
        for idx in sorted(set(promotion_indices), reverse=True):
            if 1 <= idx <= len(promotions):
                member = promotions[idx - 1][0]
                self.infractions["promotions"] = [
                    e for e in promotions if e[0].id != member.id
                ]
                promotions = self.infractions["promotions"]
                removed.append(f"P{idx} ({member.mention})")

        if removed:
            await interaction.channel.send(f"Removed: {', '.join(removed)}")
        else:
            await interaction.channel.send("No valid entries found to remove.")

    def _generate_infractions_text(self) -> str:
        lines = [f"## FHP Ghost Unit — Wave Review {utcnow().strftime('%Y-%m-%d')}"]
        lines.append("")
        for cat, label in [("demotions", "Terminations"), ("strikes", "Strikes"), ("warns", "Warns")]:
            if self.infractions.get(cat):
                lines.append(f"***__{label}__***")
                for i, (member, misses) in enumerate(self.infractions[cat], 1):
                    lines.append(f"> `{i}.` <@{member.id}> • {misses} consecutive miss{'es' if misses != 1 else ''}")
                lines.append("")
        if self.infractions.get("promotions"):
            lines.append("***__Eligible for Promotion__***")
            for i, (member, secs) in enumerate(self.infractions["promotions"], 1):
                lines.append(f"> `{i}.` <@{member.id}> • {self.cog._format_duration(secs)} this wave")
            lines.append("")
        if self.infractions.get("probation_risk"):
            lines.append("***__⚠️ At Risk — Probation Failure__***")
            for i, (member, secs) in enumerate(self.infractions["probation_risk"], 1):
                lines.append(f"> `{i}.` <@{member.id}> • {self.cog._format_duration(secs)} logged")
            lines.append("")
        if not any(self.infractions.values()):
            lines.append("No infractions. All quota met.")
        return "\n".join(lines)


class ShiftReminderView(discord.ui.View):
    def __init__(self, cog, user_id: int):
        super().__init__(timeout=None)
        self.cog     = cog
        self.user_id = user_id

    @discord.ui.button(label="End Shift", style=discord.ButtonStyle.danger, custom_id="shift_reminder_end")
    async def end_shift_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Only the person on shift can end it.", ephemeral=True)
            return
        st = self.cog.store.get_user_state(self.user_id)
        if not st:
            await interaction.response.send_message("You are not on a shift.", ephemeral=True)
            return
        record = self.cog.store.stop_shift(self.user_id)
        guild  = interaction.guild
        if guild:
            role_on    = guild.get_role(ROLE_SHIFT_ON)
            role_break = guild.get_role(ROLE_BREAK)
            try:
                if role_on and role_on in interaction.user.roles:
                    await interaction.user.remove_roles(role_on)
                if role_break and role_break in interaction.user.roles:
                    await interaction.user.remove_roles(role_break)
            except discord.Forbidden:
                pass
            await self.cog.log_event(
                guild,
                f"🔴 {interaction.user.mention} ended their shift via reminder. "
                f"ID: `{record['id']}` Duration: **{human_td(record['duration'])}**",
                actor=interaction.user
            )
        await interaction.response.send_message(
            f"✅ Your shift has been ended. Duration: **{human_td(record['duration'])}**", ephemeral=True)


class ChannelEndShiftView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="End My Shift", style=discord.ButtonStyle.danger, custom_id="channel_end_shift")
    async def end_my_shift(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        st   = self.cog.store.get_user_state(user.id)
        if not st:
            await interaction.response.send_message("You are not currently on a shift.", ephemeral=True)
            return
        record = self.cog.store.stop_shift(user.id)
        guild  = interaction.guild
        if guild:
            role_on    = guild.get_role(ROLE_SHIFT_ON)
            role_break = guild.get_role(ROLE_BREAK)
            try:
                if role_on and role_on in user.roles:
                    await user.remove_roles(role_on)
                if role_break and role_break in user.roles:
                    await user.remove_roles(role_break)
            except discord.Forbidden:
                pass
            await self.cog.log_event(
                guild,
                f"🔴 {user.mention} ended their shift via channel reminder. "
                f"ID: `{record['id']}` Duration: **{human_td(record['duration'])}**",
                actor=user
            )
        await interaction.response.send_message(
            f"✅ Your shift has been ended. Duration: **{human_td(record['duration'])}**", ephemeral=True)


class ShiftCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self.store = Store()
        self.bot.add_view(ShiftManageView(bot))

    async def cog_load(self) -> None:
        self.friday_quota_reminder.start()

    async def cog_unload(self) -> None:
        self.friday_quota_reminder.cancel()

    @tasks.loop(time=dt.time(hour=14, minute=0, tzinfo=dt.timezone.utc))
    async def friday_quota_reminder(self) -> None:
        if utcnow().weekday() != 4:
            return
        today = utcnow().date().isoformat()
        if self.store.meta.get("last_friday_quota_reminder") == today:
            return
        total = 0
        for guild in self.bot.guilds:
            total += await self._send_quota_reminders_for_guild(guild)
        self.store.meta["last_friday_quota_reminder"] = today
        self.store.save()

    @friday_quota_reminder.before_loop
    async def before_friday_quota_reminder(self) -> None:
        await self.bot.wait_until_ready()

    async def _members_needing_quota_reminder(
        self, guild: discord.Guild
    ) -> List[Tuple[discord.Member, int, int]]:
        manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
        if not manage_role:
            return []
        out: List[Tuple[discord.Member, int, int]] = []
        for member in manage_role.members:
            mids = {r.id for r in member.roles}
            if any(r.id in TRAINEE_ROLES for r in member.roles):
                continue
            if QUOTA_ROLE_0 in mids or QUOTA_ROLE_ADMIN_0 in mids:
                continue
            if self.store.is_excused(member.id):
                continue
            if is_on_loa(member.id):
                continue
            quota_minutes = await self._get_quota(member)
            if quota_minutes == 0:
                continue
            gu_secs = self.store.total_gu_equiv(member.id)
            need_secs = quota_minutes * 60
            if gu_secs < need_secs:
                out.append((member, gu_secs, need_secs))
        return out

    async def _send_quota_reminders_for_guild(self, guild: discord.Guild) -> int:
        targets = await self._members_needing_quota_reminder(guild)
        sent = 0
        for member, gu_secs, need_secs in targets:
            short = need_secs - gu_secs
            embed = self.base_embed("Weekly GU quota reminder", colour_warn())
            embed.description = (
                "You have **not yet met** your weekly GU shift quota for this wave.\n\n"
                f"**Logged:** {human_td(gu_secs)}\n"
                f"**Required:** {human_td(need_secs)}\n"
                f"**Short by:** {human_td(short)}\n\n"
                "Please complete your shifts before the wave ends."
            )
            try:
                await member.send(embed=embed)
                sent += 1
            except Exception:
                pass
        if sent:
            try:
                ch = guild.get_channel(LOG_CHANNEL_ID)
                if isinstance(ch, discord.TextChannel):
                    emb = self.base_embed("Quota reminders (scheduled)", colour_info())
                    emb.description = (
                        f"Sent **{sent}** GU quota reminder DM(s) to members who have not met quota."
                    )
                    await ch.send(embed=emb)
            except Exception:
                pass
        return sent

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ------------------------------------------------------------------ #
        # 1. PROMOTIONS channel — track last promotion timestamp per user.    #
        # ------------------------------------------------------------------ #
        if message.channel.id == PROMOTIONS_CHANNEL_ID:
            if not message.author.bot and message.mentions:
                timestamp = ts_to_int(utcnow())
                guild     = message.guild
                if guild:
                    updated = False
                    for user in message.mentions:
                        member = guild.get_member(user.id)
                        if member and any(r.id == ROLE_MANAGE_REQUIRED for r in member.roles):
                            self.store.meta["last_promotions"][str(user.id)] = timestamp
                            updated = True
                            try:
                                cooldown_days = _rank_cooldown_days(member.roles)
                                admin_days    = self.store.meta.get("admin_cooldowns", {}).get(str(member.id))
                                if admin_days is not None:
                                    cooldown_days = admin_days
                                cooldown_secs = cooldown_days * 24 * 60 * 60
                                extension     = self.store.meta.get("cooldown_extensions", {}).get(str(member.id), 0)
                                total_secs    = cooldown_secs + extension
                                end_ts        = timestamp + total_secs
                                if cooldown_days > 0:
                                    try:
                                        embed = self.base_embed("Promotion Cooldown Started", colour_warn())
                                        embed.description = (
                                            f"You have been placed on a promotion cooldown for **{cooldown_days} day(s)**."
                                        )
                                        embed.add_field(
                                            name="Cooldown Ends",
                                            value=f"<t:{end_ts}:R>", inline=True)
                                        embed.add_field(
                                            name="Duration",
                                            value=human_td(total_secs), inline=True)
                                        embed.set_footer(text="You will be notified when your cooldown expires.")
                                        await member.send(embed=embed)
                                    except Exception:
                                        pass
                                    asyncio.create_task(
                                        self._schedule_cooldown_end_dm(member.id, end_ts))
                            except Exception as e:
                                print(f"Failed to DM cooldown info to {user.display_name}: {e}")
                    if updated:
                        self.store.save()
            return  # done with this channel

        # ------------------------------------------------------------------ #
        # 2. INFRACTIONS channel — each ping = one consecutive miss event.   #
        #    Deduplicated to once per ISO calendar week per user.             #
        #    Data is persisted to disk immediately via record_infraction_ping.#
        # ------------------------------------------------------------------ #
        if message.channel.id == INFRACTIONS_CHANNEL_ID:
            if message.author.bot or not message.mentions:
                return
            guild = message.guild
            if not guild:
                return
            for user in message.mentions:
                member = guild.get_member(user.id)
                if member is None:
                    continue
                if is_trainee(member):
                    continue
                if not any(r.id == ROLE_MANAGE_REQUIRED for r in member.roles):
                    continue
                recorded = self.store.record_infraction_ping(user.id)
                if recorded:
                    new_count = self.store.get_misses(user.id)
                    await self.log_event(
                        guild,
                        f"⚠️ Consecutive miss recorded for {member.mention} "
                        f"(pinged in <#{INFRACTIONS_CHANNEL_ID}>). "
                        f"Total consecutive misses: **{new_count}**."
                    )

    def base_embed(self, title: str, colour: discord.Colour) -> discord.Embed:
        e = discord.Embed(title=title, colour=colour, timestamp=utcnow())
        e.set_image(url=IMAGE_URL)
        return e

    def embed_info(self, desc: str)  -> discord.Embed:
        e = self.base_embed("FHP Ghost Unit", colour_info()); e.description = desc; return e

    def embed_warn(self, desc: str)  -> discord.Embed:
        e = self.base_embed("Warning", colour_warn()); e.description = desc; return e

    def embed_error(self, desc: str) -> discord.Embed:
        e = self.base_embed("Error", colour_err()); e.description = desc; return e

    async def log_event(self, guild: discord.Guild, message: str, actor: Optional[discord.Member] = None):
        if actor is not None and is_trainee(actor):
            return
        logline = f"[{utcnow().isoformat()}] {message}\n"
        with open(os.path.join(LOGS_DIR, f"{utcnow().date()}.log"), "a", encoding="utf-8") as f:
            f.write(logline)
        ch = guild.get_channel(LOG_CHANNEL_ID)
        if isinstance(ch, discord.TextChannel):
            emb = self.base_embed("Shift Log", colour_info())
            emb.description = message
            await ch.send(embed=emb)

    async def build_manage_embed(self, user: discord.Member) -> discord.Embed:
        st              = self.store.get_user_state(user.id)
        logging_enabled = self.store.meta.get("logging_enabled", True)

        if not logging_enabled:
            colour = colour_err()
            status = "Logging Disabled"
        elif not st:
            colour = colour_err()
            status = "Not on shift"
        elif st.get("on_break"):
            colour = colour_warn()
            status = "On Break"
        else:
            colour = colour_ok()
            status = "Active"

        if st:
            stype = st.get("shift_type", SHIFT_TYPE_NORMAL)
            type_badges = {SHIFT_TYPE_NORMAL: "🔵 GU", SHIFT_TYPE_SRT: "🔴 SRT", SHIFT_TYPE_HSPU: "🟠 HSPU"}
            status = f"{status} — {type_badges.get(stype, stype)}"

        e = self.base_embed("Shift Manager", colour)
        e.add_field(name="Logging", value="Enabled" if logging_enabled else "Disabled", inline=True)
        e.add_field(name="Status",  value=status, inline=True)

        total_all = self.store.total_gu_equiv(user.id)
        e.add_field(name="Total This Wave (GU+SRT+HSPU)", value=human_td(total_all), inline=True)

        guild = user.guild
        if guild:
            manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
            if manage_role:
                totals = {m.id: self.store.total_gu_equiv(m.id) for m in manage_role.members}
                sorted_users = sorted(totals.items(), key=lambda x: x[1], reverse=True)
                rank = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == user.id), None)
                if rank:
                    e.add_field(
                        name="Leaderboard Placement",
                        value=f"#{rank} / {len(sorted_users)}",
                        inline=True
                    )

        e.set_footer(text=f"User: {user.display_name}")
        return e

    async def _get_quota(self, member: Optional[discord.Member]) -> int:
        if member is None:
            return GU_QUOTA_MINUTES
        mids = {r.id for r in member.roles}
        if QUOTA_ROLE_0 in mids or QUOTA_ROLE_ADMIN_0 in mids:
            return 0
        return GU_QUOTA_MINUTES

    def _has_qualifying_gu_shift(self, user_id: int, wave_index: Optional[int] = None) -> bool:
        return self.store.shift_count_for_user(
            user_id, SHIFT_TYPE_NORMAL,
            min_duration_seconds=GU_MIN_FOR_SUB * 60,
            wave_index=wave_index
        ) >= 1

    async def _build_leaderboard_lines(self, guild: discord.Guild, filter_mode: str = "all",
                                       wave_index: Optional[int] = None) -> List[str]:
        manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
        if not manage_role:
            return ["No data."]

        if filter_mode == "srt":
            srt_role    = guild.get_role(ROLE_SRT)
            srt_members = srt_role.members if srt_role else []
            rows = []
            for member in srt_members:
                count    = self.store.shift_count_for_user(member.id, SHIFT_TYPE_SRT,
                                                           min_duration_seconds=15*60, wave_index=wave_index)
                srt_secs = self.store.total_for_user(member.id, SHIFT_TYPE_SRT, wave_index=wave_index)
                has_gu   = self._has_qualifying_gu_shift(member.id, wave_index)
                met      = count >= SRT_QUOTA_SHIFTS and has_gu
                rows.append((srt_secs, count, member.display_name, member.id, met, has_gu))
            rows.sort(key=lambda x: x[0], reverse=True)
            out  = []
            rank = 1
            for srt_secs, count, name, uid, met, has_gu in rows:
                if met:
                    status = "✅ Met"
                elif not has_gu:
                    status = "❌ No qualifying GU shift"
                else:
                    status = "❌ No valid SRT shift (≥15 min)"
                out.append(f"#{rank} <@{uid}> — {count} SRT shift{'s' if count != 1 else ''} ({human_td(srt_secs)}) — {status}")
                rank += 1
            return out or ["No SRT members found."]

        if filter_mode == "hspu":
            hspu_role    = guild.get_role(ROLE_HSPU)
            hspu_members = hspu_role.members if hspu_role else []
            rows = []
            for member in hspu_members:
                hspu_secs = self.store.total_for_user(member.id, SHIFT_TYPE_HSPU, wave_index=wave_index)
                has_gu    = self._has_qualifying_gu_shift(member.id, wave_index)
                met       = hspu_secs >= HSPU_QUOTA_MINUTES * 60 and has_gu
                rows.append((hspu_secs, member.display_name, member.id, met, has_gu))
            rows.sort(key=lambda x: x[0], reverse=True)
            out  = []
            rank = 1
            for hspu_secs, name, uid, met, has_gu in rows:
                if met:
                    status = "✅ Met"
                elif not has_gu:
                    status = "❌ No qualifying GU shift"
                else:
                    short_m = max(0, HSPU_QUOTA_MINUTES - int(hspu_secs / 60))
                    status = f"❌ {short_m}m short"
                out.append(f"#{rank} <@{uid}> — {human_td(hspu_secs)} / {HSPU_QUOTA_MINUTES}min — {status}")
                rank += 1
            return out or ["No HSPU members found."]

        if filter_mode == "gu_time":
            return await self._build_gu_time_lines(guild, wave_index=wave_index)

        if filter_mode == "gu_only":
            rows = []
            for member in manage_role.members:
                gu_secs = self.store.total_for_user(member.id, SHIFT_TYPE_NORMAL, wave_index=wave_index)
                rows.append((gu_secs, member.display_name, member.id))
            rows.sort(key=lambda x: x[0], reverse=True)
            out = []
            for rank, (secs, name, uid) in enumerate(rows, 1):
                out.append(f"#{rank} <@{uid}> — {human_td(secs)}")
            return out or ["No data."]

        rows: List[Tuple[int, str, int, bool, int]] = []
        for member in manage_role.members:
            gu_secs = self.store.total_gu_equiv(member.id, wave_index=wave_index)
            quota   = await self._get_quota(member)
            met     = gu_secs >= quota * 60
            rows.append((gu_secs, member.display_name, member.id, met, quota))
        rows.sort(key=lambda x: x[0], reverse=True)

        if filter_mode == "leaderboard_met":
            rows = [r for r in rows if r[3] and not (r[0] == 0 and r[4] == 0)]
        elif filter_mode == "leaderboard_notmet":
            rows = [r for r in rows if not r[3] and not (r[0] == 0 and r[4] == 0)]
        elif filter_mode == "exempt":
            rows = [r for r in rows if r[4] == 0]

        out  = []
        rank = 1
        for secs, name, uid, met, quota in rows:
            if quota == 0:
                status = "⬜ Exempt"
                quota_str = ""
            else:
                status    = "✅ Met" if met else "❌ Not met"
                quota_str = f" / {human_td(quota * 60)}"
            out.append(f"#{rank} <@{uid}> — {human_td(secs)}{quota_str} — {status}")
            rank += 1
        return out or ["No data."]

    async def _build_gu_time_lines(self, guild: discord.Guild,
                                   wave_index: Optional[int] = None) -> List[str]:
        manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
        if not manage_role:
            return ["No data."]
        rows: List[Tuple[int, discord.Member, bool, int]] = []
        for member in manage_role.members:
            if any(r.id in TRAINEE_ROLES for r in member.roles):
                continue
            gu_secs       = self.store.total_gu_equiv(member.id, wave_index=wave_index)
            quota_minutes = await self._get_quota(member)
            met           = quota_minutes == 0 or gu_secs >= quota_minutes * 60
            rows.append((gu_secs, member, met, quota_minutes))
        rows.sort(key=lambda x: x[0], reverse=True)
        lines = []
        for i, (secs, member, met, quota) in enumerate(rows, 1):
            status = "⬜" if quota == 0 else ("✅" if met else "❌")
            quota_str = f" / {human_td(quota * 60)}" if quota > 0 else ""
            lines.append(f"`{i}.` {status} <@{member.id}> — **{human_td(secs)}**{quota_str}")
        return lines or ["No data."]

    async def _build_lists(
        self, guild: discord.Guild
    ) -> Dict[str, List]:
        manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
        infractions: Dict[str, List] = {
            "demotions": [], "strikes": [], "warns": [], "promotions": [], "probation_risk": []
        }
        if not manage_role:
            return infractions

        for member in manage_role.members:
            mids          = {r.id for r in member.roles}
            if any(r.id in TRAINEE_ROLES for r in member.roles):
                continue
            gu_secs       = self.store.total_gu_equiv(member.id)
            quota_minutes = await self._get_quota(member)

            if QUOTA_ROLE_0 in mids or QUOTA_ROLE_ADMIN_0 in mids:
                continue
            if self.store.is_excused(member.id):
                continue
            if is_on_loa(member.id):
                continue

            if ROLE_PROBATION in mids and (quota_minutes == 0 or gu_secs < quota_minutes * 60):
                infractions["probation_risk"].append((member, gu_secs))

            misses = self.store.get_misses(member.id)

            if quota_minutes > 0 and gu_secs < quota_minutes * 60:
                # Missed quota — slot into infraction tier by consecutive miss count.
                if misses >= 3:
                    infractions["demotions"].append((member, misses))
                elif misses == 2:
                    infractions["strikes"].append((member, misses))
                elif misses >= 1:
                    infractions["warns"].append((member, misses))
                # misses == 0: quota missed but never pinged yet — not listed.
            else:
                # Quota met — check promotion eligibility:
                # must be off cooldown (last ping in PROMOTIONS_CHANNEL_ID) AND
                # have enough time logged.
                if not self.store.can_be_promoted(member.id, member.roles):
                    continue
                promo = False
                if gu_secs >= GU_PROMO_MINUTES * 60:
                    promo = True
                elif ROLE_PROBATION in mids and quota_minutes > 0 and gu_secs >= quota_minutes * 60:
                    promo = True
                if promo and not any(m.id == member.id for m, _ in infractions["promotions"]):
                    infractions["promotions"].append((member, gu_secs))

        for cat in ["demotions", "strikes", "warns"]:
            infractions[cat].sort(key=lambda x: x[1], reverse=True)
        infractions["promotions"].sort(key=lambda x: x[1], reverse=True)
        infractions["probation_risk"].sort(key=lambda x: x[1])
        return infractions

    async def _build_time_embed(self, guild: discord.Guild,
                                wave_index: Optional[int] = None) -> discord.Embed:
        manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
        label = ""
        if wave_index is not None:
            labels = self.store.get_archive_labels()
            if wave_index < len(labels):
                label = f" — Wave {labels[wave_index][1]}"
        embed = self.base_embed(
            f"FHP Ghost Unit — Shift Time {utcnow().strftime('%Y-%m-%d')}{label}", colour_info())
        if not manage_role:
            embed.description = "No data."
            return embed
        lines = await self._build_gu_time_lines(guild, wave_index=wave_index)
        embed.description = "\n".join(lines)
        return embed

    async def _build_infractions_embed(
        self, infractions: Dict[str, List]
    ) -> discord.Embed:
        embed = self.base_embed(
            f"FHP Ghost Unit — Wave Review {utcnow().strftime('%Y-%m-%d')}", colour_err())
        sections = []
        for cat, label in [("demotions", "Terminations"), ("strikes", "Strikes"), ("warns", "Warns")]:
            if infractions.get(cat):
                lines = [
                    f"> `{i}.` <@{m.id}> • {misses} consecutive miss{'es' if misses != 1 else ''}"
                    for i, (m, misses) in enumerate(infractions[cat], 1)
                ]
                sections.append(f"***__{label}__***\n" + "\n".join(lines))
        if infractions.get("promotions"):
            lines = [
                f"> `{i}.` <@{m.id}> • {self._format_duration(s)} this wave"
                for i, (m, s) in enumerate(infractions["promotions"], 1)
            ]
            sections.append("***__Eligible for Promotion__***\n" + "\n".join(lines))
        if infractions.get("probation_risk"):
            lines = [
                f"> `{i}.` <@{m.id}> • {self._format_duration(s)} logged"
                for i, (m, s) in enumerate(infractions["probation_risk"], 1)
            ]
            sections.append("***__⚠️ At Risk — Probation Failure__***\n" + "\n".join(lines))
        embed.description = "\n\n".join(sections) if sections else "No infractions. All quota met."
        return embed

    def _format_duration(self, seconds: int) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        parts = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        if s or not parts: parts.append(f"{s}s")
        return " ".join(parts)

    @app_commands.command(name="shift_manage", description="Open the shift management panel.")
    async def shift_manage(self, interaction: discord.Interaction):
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not any(r.id == ROLE_ADMIN for r in user.roles):
            ch     = interaction.channel or guild.get_channel(interaction.channel_id)
            cat_id = getattr(ch, "category_id", None)
            if not (ch and (ch.id == ALLOWED_SHIFT_CHANNEL_ID or cat_id in ALLOWED_SHIFT_CATEGORIES)):
                await interaction.response.send_message(
                    f"This command can only be used in <#{ALLOWED_SHIFT_CHANNEL_ID}> "
                    f"or channels inside the allowed categories.",
                    ephemeral=True)
                return
        if not any(r.id == ROLE_MANAGE_REQUIRED for r in user.roles) and not is_trainee(user):
            await interaction.response.send_message(
                "You do not have the required role to manage shifts.", ephemeral=True)
            return
        view  = ShiftManageView(self.bot, owner_id=user.id)
        embed = await self.build_manage_embed(user)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="shift_leaderboard", description="Show the shift leaderboard.")
    @app_commands.describe(wave="Previous wave index (0=last wave, 1=two waves ago, etc). Omit for current wave.")
    async def shift_leaderboard(self, interaction: discord.Interaction, wave: Optional[int] = None):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if wave is not None:
            labels = self.store.get_archive_labels()
            if not labels:
                await interaction.response.send_message("No archived waves available.", ephemeral=True)
                return
            if wave >= len(labels):
                await interaction.response.send_message(
                    f"Only {len(labels)} archived wave(s) available (0 to {len(labels)-1}).", ephemeral=True)
                return
        wave_label = ""
        if wave is not None:
            labels = self.store.get_archive_labels()
            wave_label = f" — Wave {labels[wave][1]}"
        lines = await self._build_leaderboard_lines(guild, filter_mode="all", wave_index=wave)
        emb   = self.base_embed(f"Shift Leaderboard — Total{wave_label}", colour_info())
        emb.description = "\n".join(lines)
        await interaction.response.send_message(embed=emb, view=ShiftLeaderboardView(self, guild, wave_index=wave))

    @app_commands.command(name="shift_online", description="Show who is currently on shift.")
    async def shift_online(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        rows = []
        for uid_str, st in self.store.state.items():
            uid    = int(uid_str)
            member = guild.get_member(uid)
            if not member:
                continue
            status  = "On Break" if st.get("on_break") else "Active"
            elapsed = st["accum"]
            if not st["on_break"]:
                elapsed += max(0, ts_to_int(utcnow()) - st["last_ts"])
            shift_type = st.get("shift_type", "GU")
            rows.append((elapsed, member, status, st["start_ts"], shift_type))
        rows.sort(key=lambda x: x[0], reverse=True)
        emb = self.base_embed("Currently Online", colour_ok())
        if not rows:
            emb.description = "Nobody is on shift."
        else:
            emb.description = "\n".join(
                f"• {m.mention} — **{status}** [{stype}] — {human_td(elapsed)} since <t:{start}:R>"
                for elapsed, m, status, start, stype in rows
            )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="shift_lists", description="Show the infractions list (admin only).")
    async def shift_lists(self, interaction: discord.Interaction):
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not any(r.id == ROLE_ADMIN for r in user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return
        infractions = await self._build_lists(guild)
        embed       = await self._build_infractions_embed(infractions)
        view        = ShiftListsView(self, guild, infractions)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="shift_quota_reminder",
        description="DM members who have not met weekly GU quota (HICOM / admin).",
    )
    async def shift_quota_reminder_cmd(self, interaction: discord.Interaction):
        if not any(r.id == ROLE_ADMIN for r in interaction.user.roles):
            await interaction.response.send_message("You lack permission.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        n = await self._send_quota_reminders_for_guild(guild)
        if utcnow().weekday() == 4 and n > 0:
            self.store.meta["last_friday_quota_reminder"] = utcnow().date().isoformat()
            self.store.save()
        await interaction.followup.send(
            f"Sent **{n}** quota reminder(s).", ephemeral=True
        )

    @app_commands.command(name="shift_logging", description="Enable or disable shift logging (admin only).")
    async def shift_logging(self, interaction: discord.Interaction, enabled: Optional[bool] = None):
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not any(r.id == ROLE_ADMIN for r in user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return
        if enabled is None:
            status = self.store.meta.get("logging_enabled", True)
            await interaction.response.send_message(
                embed=self.embed_info(f"Logging is **{'ENABLED' if status else 'DISABLED'}**."),
                ephemeral=True)
            return
        self.store.meta["logging_enabled"] = enabled
        self.store.save()
        if not enabled:
            ended = []
            for uid_str in list(self.store.state.keys()):
                rec = self.store.stop_shift(int(uid_str))
                if rec:
                    ended.append(rec)
            await self.log_event(guild, f"🚫 Logging disabled by {user.mention}. Ended {len(ended)} shifts.")
        else:
            await self.log_event(guild, f"✅ Logging enabled by {user.mention}.")
        await interaction.response.send_message(
            embed=self.embed_info(f"Set logging to **{enabled}**."), ephemeral=True)

    @app_commands.command(name="shift_excuse", description="Excuse a member for one shift wave (admin only).")
    async def shift_excuse(self, interaction: discord.Interaction, personnel: discord.Member):
        if not any(r.id == ROLE_ADMIN for r in interaction.user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if self.store.is_excused(personnel.id):
            await interaction.response.send_message(
                embed=self.embed_warn(f"{personnel.mention} is already excused for this wave."),
                ephemeral=True)
            return
        self.store.add_excuse(personnel.id)
        reset_ts = self.store.meta.get("last_reset_ts", ts_to_int(utcnow()))
        await self.log_event(guild, f"✅ {interaction.user.mention} excused {personnel.mention} for this wave.")
        embed = self.base_embed("Shift Excuse Added", colour_ok())
        embed.description = f"{personnel.mention} excused for this shift wave."
        embed.add_field(name="Last Reset", value=f"<t:{reset_ts}:F>", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        try:
            dm = self.base_embed("Shift Excuse", colour_ok())
            dm.description = "You have been excused for this shift wave."
            await personnel.send(embed=dm)
        except Exception:
            pass

    @app_commands.command(name="shift_excuse_revoke", description="Revoke a shift excuse (admin only).")
    async def shift_excuse_revoke(self, interaction: discord.Interaction, personnel: discord.Member):
        if not any(r.id == ROLE_ADMIN for r in interaction.user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not self.store.remove_excuse(personnel.id):
            await interaction.response.send_message(
                embed=self.embed_warn(f"{personnel.mention} has no active excuse."), ephemeral=True)
            return
        await self.log_event(guild, f"❌ {interaction.user.mention} revoked excuse for {personnel.mention}.")
        await interaction.response.send_message(
            embed=self.base_embed("Excuse Revoked", colour_warn()), ephemeral=True)
        try:
            dm = self.base_embed("Shift Excuse Revoked", colour_warn())
            dm.description = "Your shift excuse has been revoked."
            await personnel.send(embed=dm)
        except Exception:
            pass

    admin_group = app_commands.Group(name="shift_admin", description="Administrative shift controls.")

    @admin_group.command(name="user", description="Admin actions for a specific user.")
    @app_commands.describe(
        personnel="User to target",
        action="Action to perform",
        time_minutes="Minutes (for add/subtract)",
        record_id="Record ID (for void by ID)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Stop shift",            value="stop"),
        app_commands.Choice(name="Toggle break",          value="toggle_break"),
        app_commands.Choice(name="Void ongoing shift",    value="void"),
        app_commands.Choice(name="Show shift records",    value="records"),
        app_commands.Choice(name="Void shift by ID",      value="void_id"),
        app_commands.Choice(name="Add shift time",        value="add_time"),
        app_commands.Choice(name="Subtract shift time",   value="subtract_time"),
        app_commands.Choice(name="Clear consecutive misses", value="clear_misses"),
        app_commands.Choice(name="Show miss count",       value="show_misses"),
    ])
    async def shift_admin_user(
        self, interaction: discord.Interaction,
        action: app_commands.Choice[str],
        personnel: Optional[discord.Member] = None,
        record_id: Optional[str] = None,
        time_minutes: Optional[int] = None
    ):
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not any(r.id == ROLE_ADMIN for r in user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return
        target = personnel or user

        if action.value == "stop":
            rec = self.store.stop_shift(target.id)
            if rec:
                role_on    = guild.get_role(ROLE_SHIFT_ON)
                role_break = guild.get_role(ROLE_BREAK)
                try:
                    if role_on and role_on in target.roles:
                        await target.remove_roles(role_on, reason="Admin stop")
                    if role_break and role_break in target.roles:
                        await target.remove_roles(role_break, reason="Admin stop")
                except discord.Forbidden:
                    pass
                await self.log_event(
                    guild,
                    f"🛑 Admin {user.mention} stopped {target.mention}'s shift. "
                    f"ID `{rec['id']}` ({human_td(rec['duration'])})."
                )
                emb = self.base_embed("Admin", colour_ok())
                emb.description = (
                    f"Stopped {target.mention}'s shift. "
                    f"ID `{rec['id']}` Duration **{human_td(rec['duration'])}**."
                )
                await interaction.response.send_message(embed=emb, ephemeral=True)
            else:
                await interaction.response.send_message(
                    embed=self.embed_warn("Target not on a shift."), ephemeral=True)

        elif action.value == "toggle_break":
            st = self.store.get_user_state(target.id)
            if not st:
                await interaction.response.send_message(
                    embed=self.embed_warn("Target not on a shift."), ephemeral=True)
                return
            now_on_break = self.store.toggle_break(target.id)
            role_on    = guild.get_role(ROLE_SHIFT_ON)
            role_break = guild.get_role(ROLE_BREAK)
            try:
                if now_on_break:
                    if role_on and role_on in target.roles:
                        await target.remove_roles(role_on, reason="Admin break")
                    if role_break:
                        await target.add_roles(role_break, reason="Admin break")
                else:
                    if role_break and role_break in target.roles:
                        await target.remove_roles(role_break, reason="Admin resume")
                    if role_on:
                        await target.add_roles(role_on, reason="Admin resume")
            except discord.Forbidden:
                pass
            await self.log_event(
                guild,
                f"⏯️ Admin {user.mention} toggled break for {target.mention} "
                f"-> {'On Break' if now_on_break else 'Active'}."
            )
            emb = self.base_embed("Admin", colour_info())
            emb.description = (
                f"Toggled break for {target.mention}. "
                f"Now **{'On Break' if now_on_break else 'Active'}**."
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)

        elif action.value == "void":
            self.store.void_shift(target.id)
            await self.log_event(guild, f"♻️ Admin {user.mention} voided ongoing shift for {target.mention}.")
            await interaction.response.send_message(
                embed=self.embed_info(f"Voided ongoing shift for {target.mention}."), ephemeral=True)

        elif action.value == "records":
            recs = [r for r in self.store.records if r["user_id"] == target.id][-10:]
            emb  = self.base_embed("Shift Records", colour_info())
            emb.description = (
                "\n".join(
                    f"`{r['id']}` [{r.get('shift_type','GU')}] | {human_td(r['duration'])} | "
                    f"<t:{r['start_ts']}:F> → <t:{r['end_ts']}:F>"
                    for r in recs
                ) or "No records."
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)

        elif action.value == "void_id":
            if not record_id:
                await interaction.response.send_message("Provide `record_id`.", ephemeral=True)
                return
            self.store.void_record_by_id(record_id)
            await self.log_event(guild, f"🧹 Admin {user.mention} voided record `{record_id}` for {target.mention}.")
            await interaction.response.send_message(
                embed=self.embed_info(f"Voided record `{record_id}`."), ephemeral=True)

        elif action.value in ("add_time", "subtract_time"):
            if not time_minutes or time_minutes <= 0:
                await interaction.response.send_message("Provide a positive `time_minutes`.", ephemeral=True)
                return
            sign = 1 if action.value == "add_time" else -1
            fake = {
                "id":         f"admin_{action.value}_{uuid.uuid4().hex[:8]}",
                "user_id":    target.id,
                "start_ts":   ts_to_int(utcnow()),
                "end_ts":     ts_to_int(utcnow()),
                "duration":   sign * time_minutes * 60,
                "breaks":     0,
                "shift_type": SHIFT_TYPE_NORMAL,
            }
            self.store.records.append(fake)
            self.store.save()
            verb = "added to" if sign == 1 else "subtracted from"
            await self.log_event(
                guild,
                f"{'➕' if sign == 1 else '➖'} Admin {user.mention} {verb} {time_minutes}m "
                f"{'to' if sign == 1 else 'from'} {target.mention}'s total."
            )
            await interaction.response.send_message(
                embed=self.embed_info(
                    f"{'Added' if sign == 1 else 'Subtracted'} {time_minutes} minutes "
                    f"{'to' if sign == 1 else 'from'} {target.mention}."
                ), ephemeral=True)

        elif action.value == "clear_misses":
            self.store.clear_misses(target.id)
            await self.log_event(guild, f"🧹 Admin {user.mention} cleared consecutive misses for {target.mention}.")
            await interaction.response.send_message(
                embed=self.embed_info(f"Cleared consecutive miss count for {target.mention}."), ephemeral=True)

        elif action.value == "show_misses":
            misses = self.store.get_misses(target.id)
            last_ping_ts = self.store.meta.get("infraction_ping_ts", {}).get(str(target.id))
            ping_str = f"<t:{last_ping_ts}:F>" if last_ping_ts else "Never"
            emb = self.base_embed("Miss Info", colour_info())
            emb.description = (
                f"{target.mention}\n"
                f"**Consecutive misses:** {misses}\n"
                f"**Last infraction ping:** {ping_str}"
            )
            await interaction.response.send_message(embed=emb, ephemeral=True)

    @admin_group.command(name="global", description="Global admin actions.")
    @app_commands.describe(action="Choose an action", record_id="Record ID (for void by ID)")
    @app_commands.choices(action=[
        app_commands.Choice(name="Void shift by ID",                    value="void_id"),
        app_commands.Choice(name="Void ALL shifts (requires confirm)",  value="void_all"),
        app_commands.Choice(name="Get statistics",                      value="stats"),
        app_commands.Choice(name="Leaderboard: met quota",              value="leaderboard_met"),
        app_commands.Choice(name="Leaderboard: not met quota",          value="leaderboard_notmet"),
        app_commands.Choice(name="Infractions list",                    value="infractions_list"),
        app_commands.Choice(name="List archived waves",                 value="list_waves"),
    ])
    async def shift_admin_global(
        self, interaction: discord.Interaction,
        action: app_commands.Choice[str],
        record_id: Optional[str] = None
    ):
        user  = interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        if not any(r.id == ROLE_ADMIN for r in user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return

        if action.value == "void_id":
            if not record_id:
                await interaction.response.send_message("Provide `record_id`.", ephemeral=True)
                return
            self.store.void_record_by_id(record_id)
            await self.log_event(guild, f"🧹 Admin {user.mention} voided record `{record_id}`.")
            await interaction.response.send_message(
                embed=self.embed_info(f"Voided record `{record_id}`."), ephemeral=True)

        elif action.value == "void_all":
            token = uuid.uuid4().hex[:8]
            await interaction.response.send_message(
                f"To confirm voiding ALL shifts, type **{token}** in chat.", ephemeral=True)
            def check(m):
                return m.author.id == user.id and m.channel == interaction.channel
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=60)
            except asyncio.TimeoutError:
                await interaction.channel.send("Confirmation timed out. No shifts voided.")
                return
            if msg.content.strip() != token:
                await interaction.channel.send("Confirmation failed. No shifts voided.")
                return

            # Archive current wave before reset.
            self.store.archive_wave()

            ongoing = len(self.store.state)
            self.store.state   = {}
            self.store.records = []
            self.store.meta["last_reset_ts"]    = ts_to_int(utcnow())
            self.store.meta["infractions"]      = {}
            self.store.meta["last_promotions"]  = {}
            # Clear per-week ping dedup so next week's pings register fresh.
            self.store.meta["infraction_ping_ts"] = {}
            self.store.save()

            manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
            if manage_role:
                for member in manage_role.members:
                    mids = {r.id for r in member.roles}
                    if any(r.id in TRAINEE_ROLES for r in member.roles):
                        continue
                    # Use the just-archived wave (index 0) for quota check.
                    gu_secs       = self.store.total_gu_equiv(member.id, wave_index=0)
                    quota_minutes = await self._get_quota(member)
                    exempt = (
                        QUOTA_ROLE_0 in mids or QUOTA_ROLE_ADMIN_0 in mids
                        or self.store.is_excused(member.id)
                        or is_on_loa(member.id)
                    )
                    if exempt:
                        self.store.clear_misses(member.id)
                    elif quota_minutes > 0 and gu_secs < quota_minutes * 60:
                        # Only increment here if they weren't already pinged in the
                        # infractions channel this wave (avoid double-counting).
                        # Since we cleared infraction_ping_ts above, this is a fallback
                        # for members who missed quota but were never pinged.
                        self.store.increment_miss(member.id)
                    else:
                        self.store.clear_misses(member.id)

            for path in glob.glob(os.path.join(LOGS_DIR, "*.log")):
                try: os.remove(path)
                except Exception: pass

            await self.log_event(
                guild,
                f"⚠️ Admin {user.mention} voided all shifts ({ongoing} ongoing). All times reset to 0. Wave archived."
            )
            await interaction.channel.send(
                embed=self.embed_warn(
                    f"Voided all ongoing shifts ({ongoing}) and all records. All shift times reset to 0. Wave archived."))

        elif action.value == "stats":
            await interaction.response.defer()
            num_records, total_secs = self.store.get_statistics()
            manage_role = guild.get_role(ROLE_MANAGE_REQUIRED)
            role_count  = len(manage_role.members) if manage_role else 0
            last_reset  = int_to_ts(self.store.meta.get("last_reset_ts", ts_to_int(utcnow())))
            emb = self.base_embed("Shift Stats", colour_info())
            emb.add_field(name="Total shifts",         value=str(num_records),       inline=True)
            emb.add_field(name="Total time",           value=human_td(total_secs),   inline=True)
            emb.add_field(name="Since reset",          value=f"<t:{ts_to_int(last_reset)}:F>", inline=True)
            emb.add_field(name="Members with role",    value=str(role_count),        inline=True)
            emb.add_field(name="Archived waves",       value=str(len(self.store.archive)), inline=True)
            await interaction.followup.send(embed=emb)

        elif action.value in ("leaderboard_met", "leaderboard_notmet"):
            lines = await self._build_leaderboard_lines(guild, filter_mode=action.value)
            path  = os.path.join(DATA_DIR, f"leaderboard_{action.value}_{utcnow().date()}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            await interaction.response.send_message(file=discord.File(path), ephemeral=True)

        elif action.value == "infractions_list":
            infractions = await self._build_lists(guild)
            embed       = await self._build_infractions_embed(infractions)
            view        = ShiftListsView(self, guild, infractions)
            await interaction.response.send_message(embed=embed, view=view)

        elif action.value == "list_waves":
            labels = self.store.get_archive_labels()
            if not labels:
                await interaction.response.send_message("No archived waves.", ephemeral=True)
                return
            lines = [f"`{i}` — Wave **{label}**" for i, label in labels]
            emb = self.base_embed("Archived Waves", colour_info())
            emb.description = "\n".join(lines)
            emb.set_footer(text="Use /shift_leaderboard wave:<index> to view a past wave.")
            await interaction.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(name="cooldown", description="Show your promotion cooldown status.")
    async def cooldown_slash(self, interaction: discord.Interaction, user: Optional[discord.Member] = None):
        member         = user or interaction.user
        cooldown_days, remaining = self._calculate_member_cooldown(member)
        last_ts        = self.store.meta["last_promotions"].get(str(member.id), 0)
        embed = self.base_embed("Promotion Cooldown", colour_info() if remaining == 0 else colour_warn())
        embed.add_field(name="User",            value=member.mention,       inline=True)
        embed.add_field(name="Cooldown Period", value=f"{cooldown_days}d",  inline=True)
        if last_ts == 0:
            embed.add_field(name="Status", value="Never promoted — no cooldown", inline=False)
        else:
            embed.add_field(name="Last Promotion", value=f"<t:{last_ts}:F>", inline=True)
            if remaining == 0:
                embed.add_field(name="Status", value="✅ Not on cooldown", inline=True)
            else:
                embed.add_field(name="Status",    value="⏳ On cooldown",               inline=True)
                embed.add_field(name="Ends",      value=f"<t:{last_ts + remaining}:R>", inline=True)
                embed.add_field(name="Remaining", value=human_td(remaining),             inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="cooldown", aliases=["cd"])
    async def cooldown_prefix(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Show promotion cooldown status. Usage: !cooldown [@member]"""
        member = member or ctx.author
        cooldown_days, remaining = self._calculate_member_cooldown(member)
        last_ts = self.store.meta["last_promotions"].get(str(member.id), 0)
        embed = self.base_embed("Promotion Cooldown", colour_info() if remaining == 0 else colour_warn())
        embed.add_field(name="User",            value=member.mention,       inline=True)
        embed.add_field(name="Cooldown Period", value=f"{cooldown_days}d",  inline=True)
        if last_ts == 0:
            embed.add_field(name="Status", value="Never promoted — no cooldown", inline=False)
        else:
            embed.add_field(name="Last Promotion", value=f"<t:{last_ts}:F>", inline=True)
            if remaining == 0:
                embed.add_field(name="Status", value="✅ Not on cooldown", inline=True)
            else:
                embed.add_field(name="Status",    value="⏳ On cooldown",               inline=True)
                embed.add_field(name="Ends",      value=f"<t:{last_ts + remaining}:R>", inline=True)
                embed.add_field(name="Remaining", value=human_td(remaining),             inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    def _calculate_member_cooldown(self, member: discord.Member) -> Tuple[int, int]:
        last_ts = self.store.meta.get("last_promotions", {}).get(str(member.id), 0)
        admin_days = self.store.meta.get("admin_cooldowns", {}).get(str(member.id))
        if admin_days is not None:
            cooldown_days = admin_days
        else:
            cooldown_days = _rank_cooldown_days(member.roles)
        if last_ts == 0:
            return cooldown_days, 0
        cooldown_secs = cooldown_days * 24 * 60 * 60
        extension     = self.store.meta.get("cooldown_extensions", {}).get(str(member.id), 0)
        total_secs    = cooldown_secs + extension
        elapsed       = ts_to_int(utcnow()) - last_ts
        remaining     = max(0, total_secs - elapsed)
        return cooldown_days, remaining

    @app_commands.command(name="shift_promotions", description="Generate a formatted promotions post (admin only).")
    @app_commands.describe(
        host="Display name of the host",
        host_rank_emoji="Primary rank emoji string, e.g. <:Commissioner:123>",
        host_rank2_emoji="Optional secondary rank emoji string",
        hicom="Comma-separated list of user IDs promoted at HICOM tier",
        hicom_rank="Rank emoji for all HICOM promotees",
        high_rank="Comma-separated list of user IDs promoted at High Rank tier",
        high_rank_emoji="Rank emoji for all High Rank promotees",
        low_rank="Comma-separated list of user IDs promoted at Low Rank tier",
        low_rank_emoji="Rank emoji for all Low Rank promotees",
        probation="Comma-separated list of user IDs placed on probation",
    )
    async def shift_promotions(
        self,
        interaction: discord.Interaction,
        host:             str,
        host_rank_emoji:  str,
        host_rank2_emoji: Optional[str] = None,
        hicom:            Optional[str] = None,
        hicom_rank:       Optional[str] = None,
        high_rank:        Optional[str] = None,
        high_rank_emoji:  Optional[str] = None,
        low_rank:         Optional[str] = None,
        low_rank_emoji:   Optional[str] = None,
        probation:        Optional[str] = None,
    ):
        if not any(r.id == ROLE_ADMIN for r in interaction.user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return

        today = utcnow().strftime("%m/%d/%Y")

        host_line = f"{host} - {host_rank_emoji}"
        if host_rank2_emoji:
            host_line += f" / {host_rank2_emoji}"

        def _parse_ids(raw: Optional[str]) -> List[str]:
            if not raw:
                return []
            return [uid.strip() for uid in raw.split(",") if uid.strip()]

        def _section(title: str, ids: List[str], rank_emoji: Optional[str]) -> str:
            lines = [f"***{title}***"]
            for uid in ids:
                entry = f"> <@{uid}>"
                if rank_emoji:
                    entry += f" - {rank_emoji}"
                lines.append(entry)
            return "\n".join(lines)

        sections: List[str] = [
            f"# **Ghost Unit Promotions 🎉**",
            f"**<:Date:1429367593285976144> | {today}**",
            f"**{host_line}**",
            "",
        ]

        hicom_ids    = _parse_ids(hicom)
        highrank_ids = _parse_ids(high_rank)
        lowrank_ids  = _parse_ids(low_rank)
        probation_ids = _parse_ids(probation)

        if hicom_ids:
            sections.append(_section("HICOM", hicom_ids, hicom_rank))
            sections.append("")
        if highrank_ids:
            sections.append(_section("High Rank", highrank_ids, high_rank_emoji))
            sections.append("")
        if lowrank_ids:
            sections.append(_section("Low Rank", lowrank_ids, low_rank_emoji))
            sections.append("")
        if probation_ids:
            sections.append(_section("Probation", probation_ids, None))
            sections.append("")

        text = "\n".join(sections).rstrip()
        await interaction.response.send_message(
            f"```\n{text}\n```", ephemeral=True
        )

    async def _schedule_cooldown_end_dm(self, user_id: int, end_ts: int):
        try:
            await asyncio.sleep(max(0, end_ts - ts_to_int(utcnow())))
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            if user:
                embed = self.base_embed("Promotion Cooldown Expired", colour_ok())
                embed.description = "🎉 **You're eligible for a promotion again!**"
                await user.send(embed=embed)
        except Exception as e:
            print(f"Cooldown end DM error for {user_id}: {e}")

    async def update_on_duty_message(self):
        pass


async def setup(bot: commands.Bot):
    await bot.add_cog(ShiftCog(bot))
