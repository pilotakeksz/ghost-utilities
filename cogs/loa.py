import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta, timezone

LOA_REQUEST_ROLE = 1317963289518542959
LOA_REVIEW_CHANNEL = 1398982690421870632
LOA_REVIEWER_ROLE = 1318181592719687681
LOA_ACTIVE_ROLE = 1317963293767241808  # Role to add/remove for LOA
DATA_DIR = "data"
LOGS_DIR = "logs"
LOA_DATA_FILE = os.path.join(DATA_DIR, "loa_requests.json")
LOA_LOG_FILE = os.path.join(LOGS_DIR, "loa.log")
ACTIVE_LOAS_FILE = os.path.join(DATA_DIR, "active_loas.json")
GUILD_ID = 1317959054177599559  # <-- Replace with your actual guild/server ID

# Roles that are prohibited from filing LOAs (probationary ranks)
PROBATIONARY_ROLES = [
    # Add probationary role IDs here, e.g.:
    # 1234567890123456789,
]

MIN_REASON_LENGTH = 10  # Minimum characters for a reason to be considered "vague but conceivable"

def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)

def log_loa_action(msg):
    ensure_dirs()
    with open(LOA_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")

def get_last_request_date(user_id) -> datetime | None:
    """Return the requested_at datetime of the most recent non-denied LOA request for a user, or None.
    Denied requests are excluded so they do not trigger the 1-week cooldown."""
    try:
        with open(LOA_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    # Only Pending and Approved requests count toward the cooldown
    user_requests = [
        r for r in data
        if r.get("user_id") == user_id
        and "Denied" not in str(r.get("status", ""))
    ]
    if not user_requests:
        return None
    def _parse(r):
        try:
            d = datetime.fromisoformat(r.get("requested_at", ""))
            return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
    return max(_parse(r) for r in user_requests)

def is_after_friday_cutoff(dt: datetime) -> bool:
    """Return True if dt falls outside the Friday-by-23:59-UTC submission window.
    Submissions on Saturday or Sunday (or after Friday 23:59 UTC) do not grant
    shift-infraction immunity if quota is not met."""
    weekday = dt.weekday()  # Monday=0 … Friday=4, Saturday=5, Sunday=6
    if weekday < 4:
        return False  # Mon–Thu: within window
    if weekday == 4:
        # Friday: only after 23:59 (i.e. 00:00 would roll to Saturday, so check minute >= 59 at 23h)
        return dt.hour > 23 or (dt.hour == 23 and dt.minute >= 59)
    return True  # Saturday or Sunday: outside window

def save_loa_request(request):
    ensure_dirs()
    try:
        if os.path.exists(LOA_DATA_FILE):
            with open(LOA_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []
    data.append(request)
    with open(LOA_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def update_loa_status(user_id, status):
    ensure_dirs()
    try:
        with open(LOA_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = []
    for req in data:
        if req["user_id"] == user_id and req["status"] == "Pending":
            req["status"] = status
    with open(LOA_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def add_active_loa(user_id, end_date):
    ensure_dirs()
    try:
        if os.path.exists(ACTIVE_LOAS_FILE):
            with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
    except Exception:
        data = {}
    data[str(user_id)] = end_date
    with open(ACTIVE_LOAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def remove_active_loa(user_id):
    ensure_dirs()
    try:
        if os.path.exists(ACTIVE_LOAS_FILE):
            with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {}
    except Exception:
        data = {}
    if str(user_id) in data:
        del data[str(user_id)]
    with open(ACTIVE_LOAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

class LOARequestModal(discord.ui.Modal, title="LOA Request"):
    reason = discord.ui.TextInput(
        label="Reason for LOA",
        style=discord.TextStyle.paragraph,
        placeholder="Why do you need a leave of absence?",
        required=True,
        max_length=300
    )
    duration = discord.ui.TextInput(
        label="Duration (days, max 28)",
        placeholder="Enter number of days (e.g. 7)",
        required=True,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        # ── Rule: only members with the LOA request role may apply ──────────
        if not any(r.id == LOA_REQUEST_ROLE for r in interaction.user.roles):
            await interaction.response.send_message("You do not have permission to request an LOA.", ephemeral=True)
            return

        # ── Rule: probationary ranks may not file for LOAs ───────────────────
        if PROBATIONARY_ROLES and any(r.id in PROBATIONARY_ROLES for r in interaction.user.roles):
            await interaction.response.send_message(
                "Probationary personnel are not eligible to file a Leave of Absence.", ephemeral=True
            )
            return

        # ── Rule: duration must be 1–28 days (max 4 weeks) ──────────────────
        try:
            days = int(self.duration.value)
            if days < 1 or days > 28:
                raise ValueError
        except ValueError:
            await interaction.response.send_message(
                "Please enter a valid duration between 1 and 28 days (maximum 4 weeks).", ephemeral=True
            )
            return

        # ── Rule: reason must be at least vaguely conceivable ────────────────
        reason_stripped = self.reason.value.strip()
        if len(reason_stripped) < MIN_REASON_LENGTH:
            await interaction.response.send_message(
                f"Please provide a reason of at least {MIN_REASON_LENGTH} characters. "
                "It does not need to be detailed, but must be a conceivable reason.", ephemeral=True
            )
            return

        # ── Rule: may not submit within 1 week of a previous request ─────────
        now = datetime.now(timezone.utc)
        last_request = get_last_request_date(interaction.user.id)
        if last_request is not None and (now - last_request) < timedelta(weeks=1):
            next_eligible = last_request + timedelta(weeks=1)
            await interaction.response.send_message(
                f"You may not submit a new LOA request within 1 week of your previous request. "
                f"You will be eligible again <t:{int(next_eligible.timestamp())}:R>.", ephemeral=True
            )
            return

        # ── Rule: detect Friday 23:59 UTC cutoff for shift-infraction immunity ─
        submitted_after_cutoff = is_after_friday_cutoff(now)

        end_date = now + timedelta(days=days)
        request = {
            "user_id": interaction.user.id,
            "user_tag": str(interaction.user),
            "reason": reason_stripped,
            "duration": days,
            "requested_at": now.isoformat(),
            "end_date": end_date.isoformat(),
            "status": "Pending",
            "shift_immunity": not submitted_after_cutoff,  # False if submitted after Friday 23:59 UTC
        }
        save_loa_request(request)
        log_loa_action(
            f"REQUESTED: {interaction.user} ({interaction.user.id}) for {days} days. "
            f"Shift immunity: {not submitted_after_cutoff}. Reason: {reason_stripped}"
        )

        # Build review embed ──────────────────────────────────────────────────
        embed = discord.Embed(
            title="New LOA Request",
            description=(
                f"**User:** {interaction.user.mention}\n"
                f"**Duration:** {days} days\n"
                f"**End Date:** <t:{int(end_date.timestamp())}:D>\n"
                f"**Reason:** {reason_stripped}"
            ),
            color=discord.Color.orange()
        )
        if submitted_after_cutoff:
            embed.add_field(
                name="⚠️ Shift Infraction Immunity",
                value="This request was submitted **after Friday 23:59 UTC**. "
                      "If quota is not met, **shift infractions are not waived** for this LOA.",
                inline=False
            )
        embed.set_footer(text=f"LOA for {interaction.user.id}")

        review_channel = interaction.guild.get_channel(LOA_REVIEW_CHANNEL)
        if review_channel and isinstance(review_channel, discord.TextChannel):
            await review_channel.send(content=f"<@&{LOA_REVIEWER_ROLE}>", embed=embed, view=LOAReviewView(interaction.user.id))
            await interaction.response.send_message("Your LOA request has been submitted for review.", ephemeral=True)
        else:
            await interaction.response.send_message("Review channel not found. Please contact an admin.", ephemeral=True)

class LOAReviewView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=None)
        self.user_id = user_id

    async def update_embed(self, interaction, status, reviewer):
        # copy existing embed and preserve non-status fields
        embed = interaction.message.embeds[0].copy()
        # collect existing fields except Status/Reviewed by
        preserved = [(f.name, f.value, f.inline) for f in embed.fields if f.name not in ("Status", "Reviewed by")]
        embed.clear_fields()
        for name, value, inline in preserved:
            embed.add_field(name=name, value=value, inline=inline)

        # set color based on status
        if "Approved" in status or "✅" in status:
            embed.color = discord.Color.green()
        elif "Denied" in status or "❌" in status:
            embed.color = discord.Color.red()
        else:
            embed.color = discord.Color.orange()

        embed.add_field(name="Status", value=status, inline=False)
        embed.add_field(name="Reviewed by", value=reviewer.mention, inline=False)
        await interaction.message.edit(embed=embed, view=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="loa_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == LOA_REVIEWER_ROLE for r in interaction.user.roles):
            await interaction.response.send_message("You do not have permission to review LOA requests.", ephemeral=True)
            return
        member = interaction.guild.get_member(self.user_id)
        loa_role = interaction.guild.get_role(LOA_ACTIVE_ROLE)
        await interaction.response.send_message(f"✅ LOA approved for {member.mention if member else self.user_id}.", ephemeral=True)
        log_loa_action(f"APPROVED: {member} ({self.user_id}) by {interaction.user} ({interaction.user.id})")
        update_loa_status(self.user_id, "Approved")

        # Find end_date for this user (from requests). If not present, skip adding active LOA here;
        # update_loa_status sets Pending->Approved for any pending entries; try to capture end_date.
        # helper to parse stored ISO datetimes as UTC-aware
        def _parse_iso_utc(s):
            try:
                d = datetime.fromisoformat(s)
                if d.tzinfo is None:
                    return d.replace(tzinfo=timezone.utc)
                return d.astimezone(timezone.utc)
            except Exception:
                return None

        req_end_date = None
        try:
            with open(LOA_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # pick the most recent approved entry for this user
            for req in reversed(data):
                if req.get("user_id") == self.user_id and req.get("status") in ("Approved", "Approved "):
                    req_end_date = req.get("end_date")
                    break
        except Exception:
            req_end_date = None

        if req_end_date:
            # store ISO string (already saved) and ensure DB/display parsing uses UTC
            add_active_loa(self.user_id, req_end_date)

        try:
            if member and loa_role:
                await member.add_roles(loa_role, reason="LOA approved")
                # DM the user as embed
                try:
                    # Determine shift immunity status from stored request
                    shift_immunity = True
                    try:
                        with open(LOA_DATA_FILE, "r", encoding="utf-8") as f:
                            req_data = json.load(f)
                        for r in reversed(req_data):
                            if r.get("user_id") == self.user_id and r.get("status") in ("Approved", "Approved "):
                                shift_immunity = r.get("shift_immunity", True)
                                break
                    except Exception:
                        pass

                    dm_embed = discord.Embed(
                        title="✅ LOA Approved",
                        description=f"Your LOA request has been approved by {interaction.user.mention}.",
                        color=discord.Color.green()
                    )
                    if req_end_date:
                        parsed = _parse_iso_utc(req_end_date)
                        if parsed:
                            dm_embed.add_field(name="Ends", value=f"<t:{int(parsed.timestamp())}:F>", inline=False)
                    if not shift_immunity:
                        dm_embed.add_field(
                            name="⚠️ Shift Infraction Immunity",
                            value="Because your request was submitted after **Friday 23:59 UTC**, "
                                  "you are **not** exempt from shift infractions if quota is not met.",
                            inline=False
                        )
                    dm_embed.add_field(
                        name="📋 LOA Regulations",
                        value=(
                            "During your LOA you are **exempt from quota and duty requirements**.\n\n"
                            "However, you are **not permitted** to participate in any department-related "
                            "activities, including shifts, events, and trainings.\n"
                            "**Exception:** Game nights are permitted.\n\n"
                            "Failure to comply may result in infractions or removal from the department / sub-divisions."
                        ),
                        inline=False
                    )
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
        except Exception:
            pass
        await self.update_embed(interaction, "✅ Approved", interaction.user)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="loa_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == LOA_REVIEWER_ROLE for r in interaction.user.roles):
            await interaction.response.send_message("You do not have permission to review LOA requests.", ephemeral=True)
            return
        member = interaction.guild.get_member(self.user_id)
        update_loa_status(self.user_id, "Denied")
        remove_active_loa(self.user_id)
        await interaction.response.send_message(f"❌ LOA denied for {member.mention if member else self.user_id}.", ephemeral=True)
        log_loa_action(f"DENIED: {member} ({self.user_id}) by {interaction.user} ({interaction.user.id})")
        try:
            if member:
                # send denied DM as embed
                try:
                    dm_embed = discord.Embed(
                        title="❌ LOA Denied",
                        description=f"Your LOA request has been denied by {interaction.user.mention}.",
                        color=discord.Color.red()
                    )
                    await member.send(embed=dm_embed)
                except Exception:
                    pass
        except Exception:
            pass
        await self.update_embed(interaction, "❌ Denied", interaction.user)

class LOACog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        ensure_dirs()
        self.bot.add_view(LOAReviewView(user_id=0))  # Persistent view
        self.loa_expiry_check.start()

    @discord.app_commands.command(name="loa_request", description="Request a Leave of Absence (LOA).")
    async def loa_request(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LOARequestModal())

    @discord.app_commands.command(name="loa_active", description="Show currently active LOAs.")
    async def loa_active(self, interaction: discord.Interaction):
        """Show all currently active LOAs."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        
        try:
            with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
                active_loas = json.load(f)
        except Exception:
            active_loas = {}
        
        if not active_loas:
            embed = discord.Embed(
                title="Active LOAs",
                description="No active LOAs found.",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        # Get member info for each active LOA
        loa_entries = []
        # parse stored ISO datetimes as UTC-aware to compute remaining correctly
        def _parse_iso_utc(s):
            try:
                d = datetime.fromisoformat(s)
                if d.tzinfo is None:
                    return d.replace(tzinfo=timezone.utc)
                return d.astimezone(timezone.utc)
            except Exception:
                return None

        for user_id_str, end_date_str in active_loas.items():
            try:
                user_id = int(user_id_str)
                end_date = _parse_iso_utc(end_date_str)
                member = guild.get_member(user_id)
                if member and end_date:
                    remaining = end_date - datetime.now(timezone.utc)
                    if remaining.total_seconds() > 0:
                        loa_entries.append((member, end_date, remaining))
            except Exception:
                continue
        
        # Sort by remaining time (shortest first)
        loa_entries.sort(key=lambda x: x[2].total_seconds())
        
        embed = discord.Embed(
            title="Active LOAs",
            color=discord.Color.green()
        )
        
        if not loa_entries:
            embed.description = "No valid active LOAs found."
        else:
            lines = []
            for member, end_date, remaining in loa_entries:
                days = remaining.days
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                time_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m"
                lines.append(f"• {member.mention} — ends <t:{int(end_date.timestamp())}:R> ({time_str} remaining)")
            embed.description = "\n".join(lines)
        
        await interaction.response.send_message(embed=embed)

    @discord.app_commands.command(name="loa_history", description="View your LOA request history.")
    @discord.app_commands.describe(member="Member to view history for (admin only)")
    async def loa_history(self, interaction: discord.Interaction, member: discord.Member = None):
        """View LOA request history for a user."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        
        # Determine target user
        target_user = member if member else interaction.user
        
        # Check if viewing someone else's history (admin only)
        if member and member != interaction.user:
            admin_role_id = 1318181592719687681
            if not any(r.id == admin_role_id for r in interaction.user.roles):
                await interaction.response.send_message("You can only view your own LOA history.", ephemeral=True)
                return
        
        # Load LOA requests
        try:
            with open(LOA_DATA_FILE, "r", encoding="utf-8") as f:
                all_requests = json.load(f)
        except Exception:
            all_requests = []
        
        # Filter requests for target user
        user_requests = [
            req for req in all_requests
            if req.get("user_id") == target_user.id
        ]
        
        if not user_requests:
            embed = discord.Embed(
                title="LOA History",
                description=f"No LOA requests found for {target_user.mention}.",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Sort by requested_at (most recent first)
        def parse_date(req):
            try:
                dt = datetime.fromisoformat(req.get("requested_at", ""))
                if dt.tzinfo is None:
                    return dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                return datetime.min.replace(tzinfo=timezone.utc)
        
        user_requests.sort(key=parse_date, reverse=True)
        
        # Helper to parse ISO dates
        def _parse_iso_utc(s):
            try:
                d = datetime.fromisoformat(s)
                if d.tzinfo is None:
                    return d.replace(tzinfo=timezone.utc)
                return d.astimezone(timezone.utc)
            except Exception:
                return None
        
        # Create embed with pagination if needed
        embed = discord.Embed(
            title=f"LOA History - {target_user.display_name}",
            color=discord.Color.blue()
        )
        embed.set_author(name=str(target_user), icon_url=target_user.display_avatar.url)
        
        # Limit to 10 most recent for display
        display_requests = user_requests[:10]
        
        if len(user_requests) > 10:
            embed.set_footer(text=f"Showing 10 most recent of {len(user_requests)} total requests")
        
        # Build description with request details
        lines = []
        for i, req in enumerate(display_requests, 1):
            status = req.get("status", "Unknown")
            reason = req.get("reason", "N/A")
            duration = req.get("duration", 0)
            requested_at = _parse_iso_utc(req.get("requested_at", ""))
            end_date = _parse_iso_utc(req.get("end_date", ""))
            
            # Status emoji
            if "Approved" in status or "✅" in status:
                status_emoji = "✅"
            elif "Denied" in status or "❌" in status:
                status_emoji = "❌"
            else:
                status_emoji = "⏳"
            
            # Format date
            date_str = f"<t:{int(requested_at.timestamp())}:D>" if requested_at else "Unknown"
            
            # Build line
            line = f"**{i}. {status_emoji} {status}** - {duration} days\n"
            line += f"   Requested: {date_str}"
            if end_date:
                line += f" | Ends: <t:{int(end_date.timestamp())}:D>"
            line += f"\n   Reason: {reason[:100]}{'...' if len(reason) > 100 else ''}\n"
            lines.append(line)
        
        embed.description = "\n".join(lines) if lines else "No requests found."
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.app_commands.command(name="loa_admin", description="Admin LOA management (admin only).")
    @discord.app_commands.describe(
        user="User to manage LOA for",
        action="Action to perform",
        days="Days to extend (for extend action only)"
    )
    @discord.app_commands.choices(action=[
        discord.app_commands.Choice(name="Extend LOA", value="extend"),
        discord.app_commands.Choice(name="Administer LOA", value="administer"),
        discord.app_commands.Choice(name="End LOA", value="end")
    ])
    async def loa_admin(self, interaction: discord.Interaction, user: discord.Member, action: discord.app_commands.Choice[str], days: int = None):
        """Admin commands to manage LOAs."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Guild only.", ephemeral=True)
            return
        
        # Check admin role
        admin_role_id = 1318181592719687681
        if not any(r.id == admin_role_id for r in interaction.user.roles):
            await interaction.response.send_message("You lack admin role.", ephemeral=True)
            return
        
        loa_role = guild.get_role(LOA_ACTIVE_ROLE)
        if not loa_role:
            await interaction.response.send_message("LOA role not found.", ephemeral=True)
            return
        
        if action.value == "extend":
            if days is None or days <= 0:
                await interaction.response.send_message("Please provide a positive number of days to extend.", ephemeral=True)
                return
            
            # Check if user has active LOA
            try:
                with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
                    active_loas = json.load(f)
            except Exception:
                active_loas = {}
            
            if str(user.id) not in active_loas:
                await interaction.response.send_message(f"{user.mention} does not have an active LOA.", ephemeral=True)
                return
            
            # Extend the LOA
            current_end = datetime.fromisoformat(active_loas[str(user.id)])
            new_end = current_end + timedelta(days=days)
            active_loas[str(user.id)] = new_end.isoformat()
            
            with open(ACTIVE_LOAS_FILE, "w", encoding="utf-8") as f:
                json.dump(active_loas, f, indent=2)
            
            log_loa_action(f"EXTENDED: {user} ({user.id}) LOA extended by {days} days by {interaction.user} ({interaction.user.id})")
            
            embed = discord.Embed(
                title="LOA Extended",
                description=f"Extended {user.mention}'s LOA by {days} days.",
                color=discord.Color.green()
            )
            embed.add_field(name="New End Date", value=f"<t:{int(new_end.timestamp())}:F>", inline=True)
            embed.add_field(name="Extended by", value=f"{days} days", inline=True)
            
            await interaction.response.send_message(embed=embed)
            
            # Notify user
            try:
                await user.send(f"Your LOA has been extended by {days} days. New end date: <t:{int(new_end.timestamp())}:F>")
            except Exception:
                pass
        
        elif action.value == "administer":
            # Check if user already has LOA role
            if loa_role in user.roles:
                await interaction.response.send_message(f"{user.mention} already has the LOA role.", ephemeral=True)
                return

            # Add LOA role
            try:
                await user.add_roles(loa_role, reason="LOA administered by admin")
                log_loa_action(f"ADMINISTERED: {user} ({user.id}) LOA role added by {interaction.user} ({interaction.user.id})")

                # Treat as a requested+approved LOA so it shows in active LOAs:
                now = datetime.now(timezone.utc)
                # allow admin to provide a days param; fall back to default 28
                default_days = 28
                if days is not None:
                    try:
                        days_int = int(days)
                        if days_int < 1 or days_int > 28:
                            raise ValueError("days out of range")
                    except Exception:
                        await interaction.response.send_message("Invalid days value. Use 1–28.", ephemeral=True)
                        return
                else:
                    days_int = default_days

                end_date = now + timedelta(days=days_int)
                request = {
                    "user_id": user.id,
                    "user_tag": str(user),
                    "reason": "Administered LOA",
                    "duration": days_int,
                    "requested_at": now.isoformat(),
                    "end_date": end_date.isoformat(),
                    "status": "Approved"
                }
                save_loa_request(request)
                add_active_loa(user.id, end_date.isoformat())

                embed = discord.Embed(
                    title="LOA Administered",
                    description=f"LOA role has been given to {user.mention}. Treated as an approved request (ends <t:{int(end_date.timestamp())}:F>).",
                    color=discord.Color.green()
                )
                await interaction.response.send_message(embed=embed)

                # Notify user as embed
                try:
                    dm_embed = discord.Embed(
                        title="✅ LOA Administered",
                        description="An administrator has given you an LOA. This has been recorded as an approved request.",
                        color=discord.Color.green()
                    )
                    dm_embed.add_field(name="Ends", value=f"<t:{int(end_date.timestamp())}:F>", inline=False)
                    await user.send(embed=dm_embed)
                except Exception:
                    pass
            except Exception as e:
                await interaction.response.send_message(f"Failed to add LOA role: {e}", ephemeral=True)
        
        elif action.value == "end":
            # Remove LOA role and active LOA entry
            removed_role = False
            removed_entry = False
            
            if loa_role in user.roles:
                try:
                    await user.remove_roles(loa_role, reason="LOA ended by admin")
                    removed_role = True
                except Exception as e:
                    await interaction.response.send_message(f"Failed to remove LOA role: {e}", ephemeral=True)
                    return
            
            # Remove from active LOAs
            try:
                with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
                    active_loas = json.load(f)
            except Exception:
                active_loas = {}
            
            if str(user.id) in active_loas:
                del active_loas[str(user.id)]
                with open(ACTIVE_LOAS_FILE, "w", encoding="utf-8") as f:
                    json.dump(active_loas, f, indent=2)
                removed_entry = True
            
            log_loa_action(f"ENDED: {user} ({user.id}) LOA ended by {interaction.user} ({interaction.user.id})")
            
            embed = discord.Embed(
                title="LOA Ended",
                description=f"LOA has been ended for {user.mention}.",
                color=discord.Color.red()
            )
            if removed_role:
                embed.add_field(name="Role Removed", value="✅ LOA role removed", inline=True)
            if removed_entry:
                embed.add_field(name="Entry Removed", value="✅ Active LOA entry removed", inline=True)
            
            await interaction.response.send_message(embed=embed)
            
            # Notify user
            try:
                await user.send("Your LOA has been ended by an administrator.")
            except Exception:
                pass

    @tasks.loop(minutes=10)
    async def loa_expiry_check(self):
        ensure_dirs()
        now = datetime.now(timezone.utc)
        # Check active LOAs
        try:
            with open(ACTIVE_LOAS_FILE, "r", encoding="utf-8") as f:
                active_loas = json.load(f)
        except Exception:
            active_loas = {}

        # Use correct guild lookup
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            try:
                guild = await self.bot.fetch_guild(GUILD_ID)
            except Exception:
                guild = None

        loa_role = guild.get_role(LOA_ACTIVE_ROLE) if guild else None
        expired_users = []
        for user_id, end_date_str in active_loas.items():
            try:
                # parse as UTC-aware
                d = datetime.fromisoformat(end_date_str)
                if d.tzinfo is None:
                    end_date = d.replace(tzinfo=timezone.utc)
                else:
                    end_date = d.astimezone(timezone.utc)
            except Exception:
                continue
            if now >= end_date:
                member = guild.get_member(int(user_id)) if guild else None
                if member and loa_role and loa_role in member.roles:
                    try:
                        await member.remove_roles(loa_role, reason="LOA expired")
                        log_loa_action(f"EXPIRED: {member} ({user_id}) LOA expired and role removed.")
                        try:
                            dm_embed = discord.Embed(
                                title="LOA expired",
                                description="Your LOA has expired and the LOA role has been removed.",
                                color=discord.Color.red()
                            )
                            await member.send(embed=dm_embed)
                        except Exception:
                            pass
                    except Exception:
                        pass
                expired_users.append(user_id)
        # Remove expired users from active_loas.json
        for user_id in expired_users:
            remove_active_loa(user_id)

async def setup(bot):
    await bot.add_cog(LOACog(bot))