from __future__ import annotations

import asyncio
import json
import os
import discord
from discord.ext import commands


# ── Role IDs ──────────────────────────────────────────────────────────────
ROLE_1_BOOST_A = 1399135941775593572   # Music Bot Access
ROLE_1_BOOST_B = 1349462336951554189   # 1 boost role
ROLE_2_BOOST   = 1426716068638101624   # 2 boost role
ROLE_3_BOOST   = 1398817408306647132   # 3+ boost / office key

ALL_BOOSTER_ROLES = {
    ROLE_1_BOOST_A,
    ROLE_1_BOOST_B,
    ROLE_2_BOOST,
    ROLE_3_BOOST,
}

# (min_boosts, roles_to_add) — best match wins
BOOST_TIERS = [
    (3, [ROLE_3_BOOST, ROLE_2_BOOST, ROLE_1_BOOST_A, ROLE_1_BOOST_B]),
    (2, [ROLE_2_BOOST, ROLE_1_BOOST_A, ROLE_1_BOOST_B]),
    (1, [ROLE_1_BOOST_A, ROLE_1_BOOST_B]),
]

THANK_YOU_IMAGE_URL = "https://cdn.discordapp.com/attachments/1399369851520290836/1527131305978892329/Templateeee.png"
HICOM_CHANNEL_ID = 1317963319172137103
BOOST_COUNTS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "boost_counts.json"
)
BOT_GIVEN_ROLES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "bot_given_roles.json"
)


def _load_boost_counts() -> dict[str, int]:
    """Load per-user boost counts from disk."""
    if not os.path.exists(BOOST_COUNTS_FILE):
        return {}
    try:
        with open(BOOST_COUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): int(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_boost_counts(data: dict[str, int]) -> None:
    """Save per-user boost counts to disk."""
    os.makedirs(os.path.dirname(BOOST_COUNTS_FILE), exist_ok=True)
    with open(BOOST_COUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _increment_boost(user_id: int) -> int:
    """Increment a user's lifetime boost count and return the new count."""
    counts = _load_boost_counts()
    key = str(user_id)
    current = counts.get(key, 0)
    counts[key] = current + 1
    _save_boost_counts(counts)
    return counts[key]


def _decrement_boost(user_id: int) -> int:
    """Decrement a user's lifetime boost count and return the new count."""
    counts = _load_boost_counts()
    key = str(user_id)
    current = counts.get(key, 0)
    if current > 0:
        counts[key] = current - 1
    else:
        counts[key] = 0
    _save_boost_counts(counts)
    return counts[key]


def _get_user_boost_count(user_id: int) -> int:
    """Get the total lifetime boost count for a user."""
    counts = _load_boost_counts()
    return counts.get(str(user_id), 0)


def _load_bot_given_roles() -> dict[str, list[int]]:
    """Load which users the bot has given which roles.
    Format: {user_id_str: [role_id, ...]}"""
    if not os.path.exists(BOT_GIVEN_ROLES_FILE):
        return {}
    try:
        with open(BOT_GIVEN_ROLES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {str(k): list(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_bot_given_roles(data: dict[str, list[int]]) -> None:
    """Save bot-given role tracking to disk."""
    os.makedirs(os.path.dirname(BOT_GIVEN_ROLES_FILE), exist_ok=True)
    with open(BOT_GIVEN_ROLES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _bot_gave_role(user_id: int, role_id: int) -> bool:
    """Check if the bot has recorded giving this role to this user."""
    records = _load_bot_given_roles()
    return role_id in records.get(str(user_id), [])


def _record_bot_gave_role(user_id: int, role_id: int) -> None:
    """Record that the bot gave a role to a user."""
    records = _load_bot_given_roles()
    key = str(user_id)
    if key not in records:
        records[key] = []
    if role_id not in records[key]:
        records[key].append(role_id)
    _save_bot_given_roles(records)


def _record_bot_removed_role(user_id: int, role_id: int) -> None:
    """Remove tracking that the bot gave a role (after bot removes it)."""
    records = _load_bot_given_roles()
    key = str(user_id)
    if key in records and role_id in records[key]:
        records[key].remove(role_id)
        if not records[key]:
            del records[key]
        _save_bot_given_roles(records)


class BoostPerksCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Tier helpers ─────────────────────────────────────────────────────

    def _get_boost_tier(self, member: discord.Member) -> int:
        """Return the highest boost tier (0-3) the member qualifies for
        based on their total lifetime boost count."""
        if not member.premium_since:
            return 0
        total_boosts = _get_user_boost_count(member.id)
        if total_boosts >= 3:
            return 3
        if total_boosts >= 2:
            return 2
        if total_boosts >= 1:
            return 1
        return 0

    def _get_boost_tier_from_count(self, count: int) -> int:
        """Return the tier based on a raw boost count."""
        if count >= 3:
            return 3
        if count >= 2:
            return 2
        if count >= 1:
            return 1
        return 0

    def _tier_roles(self, tier: int) -> list[int]:
        """Return role IDs for a given tier (1-3)."""
        for min_b, rids in BOOST_TIERS:
            if tier >= min_b:
                return list(rids)
        return []

    # ── Role assignment ──────────────────────────────────────────────────

    async def _sync_booster_roles(self, member: discord.Member) -> None:
        """Remove or assign booster roles based on current boost status.
        ROLE_3_BOOST (office key) is NEVER removed by the bot unless the bot itself gave it.
        Roles given manually by admins are preserved."""
        guild = member.guild
        if not guild:
            return

        current_ids = {r.id for r in member.roles}
        is_boosting = member.premium_since is not None

        if not is_boosting:
            # Only remove roles that the bot tracked as having given
            to_remove = []
            for rid in ALL_BOOSTER_ROLES:
                if rid in current_ids and _bot_gave_role(member.id, rid):
                    r = guild.get_role(rid)
                    if r:
                        to_remove.append(r)

            # Also remove roles the bot didn't give, EXCEPT ROLE_3_BOOST which is exclusive
            for rid in (ALL_BOOSTER_ROLES - {ROLE_3_BOOST}):
                if rid in current_ids and not _bot_gave_role(member.id, rid):
                    r = guild.get_role(rid)
                    if r:
                        to_remove.append(r)

            if to_remove:
                try:
                    await member.remove_roles(
                        *to_remove,
                        reason="Stopped boosting — removed booster roles"
                    )
                    for r in to_remove:
                        _record_bot_removed_role(member.id, r.id)
                except Exception:
                    pass

            # If they stopped boosting, clear the bot's tracking for the exclusive role
            # so it could be reassigned later if they boost again
            if _bot_gave_role(member.id, ROLE_3_BOOST):
                _record_bot_removed_role(member.id, ROLE_3_BOOST)
            return

        tier = self._get_boost_tier(member)
        target_ids = set(self._tier_roles(tier))

        to_add = []
        for rid in target_ids:
            if rid not in current_ids:
                r = guild.get_role(rid)
                if r:
                    to_add.append(r)

        to_remove = []
        for rid in ALL_BOOSTER_ROLES:
            if rid not in target_ids and rid in current_ids:
                # Never remove ROLE_3_BOOST unless the bot itself gave it
                if rid == ROLE_3_BOOST and not _bot_gave_role(member.id, rid):
                    continue
                r = guild.get_role(rid)
                if r:
                    to_remove.append(r)

        if to_add:
            try:
                await member.add_roles(*to_add, reason=f"Booster tier {tier} ({_get_user_boost_count(member.id)} lifetime boosts)")
                # Track that the bot gave these roles
                for r in to_add:
                    _record_bot_gave_role(member.id, r.id)
            except Exception:
                pass
        if to_remove:
            try:
                await member.remove_roles(*to_remove, reason=f"Booster tier {tier} — downgrade")
                for r in to_remove:
                    _record_bot_removed_role(member.id, r.id)
            except Exception:
                pass

    # ── DM helpers ───────────────────────────────────────────────────────

    async def _dm_boost_started(self, member: discord.Member, tier: int) -> None:
        total = _get_user_boost_count(member.id)
        embed = discord.Embed(
            title="🎉 Thank You for Boosting!",
            description=(
                f"Thank you for boosting **{member.guild.name}**!\n"
                f"You've unlocked **Tier {tier}** booster perks "
                f"({total} total boost{'s' if total != 1 else ''} given).\n"
                f"Your roles have been assigned automatically."
            ),
            color=discord.Color.from_str("#ff73fa"),
        )
        embed.set_image(url=THANK_YOU_IMAGE_URL)
        if tier >= 3:
            embed.add_field(
                name="<:Panic:1482070572606423103> Claim Your Office Key",
                value=(
                    "You've unlocked the **3+ Boost** tier, which includes "
                    "your very own office and office key!\n"
                    f"Please open a ticket in <#{HICOM_CHANNEL_ID}> to claim it."
                ),
                inline=False,
            )
        try:
            await member.send(embed=embed)
        except Exception:
            pass

    async def _dm_boost_lost(self, member: discord.Member) -> None:
        embed = discord.Embed(
            title="Boost Removed",
            description=(
                f"It looks like you've stopped boosting **{member.guild.name}**.\n"
                "Your booster roles have been removed.\n\n"
                "If you'd like to boost again you're always welcome!"
            ),
            color=discord.Color.red(),
        )
        try:
            await member.send(embed=embed)
        except Exception:
            pass

    # ── Listeners ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.premium_since == after.premium_since:
            return

        # Track lifetime boost count (only increment - never decrement)
        if after.premium_since is not None and before.premium_since is None:
            _increment_boost(after.id)

        await self._sync_booster_roles(after)

        if after.premium_since is not None:
            tier = self._get_boost_tier(after)
            await self._dm_boost_started(after, tier)
        else:
            await self._dm_boost_lost(after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.premium_since is not None:
            await self._sync_booster_roles(member)

    # ── Admin commands ──────────────────────────────────────────────────

    @commands.command(name="boosttest")
    @commands.has_guild_permissions(administrator=True)
    async def boost_test(self, ctx: commands.Context, member: discord.Member = None) -> None:
        """Test boost perk role assignment. (admins only)
        Usage: !boosttest [@user]"""
        target = member or ctx.author

        is_boosting = target.premium_since is not None
        total_boosts = _get_user_boost_count(target.id)
        tier = self._get_boost_tier(target) if is_boosting else 0

        embed = discord.Embed(
            title="Boost Perk Test",
            description=f"Testing boost perks for {target.mention}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Currently Boosting", value="✅ Yes" if is_boosting else "❌ No", inline=True)
        embed.add_field(name="Lifetime Boosts", value=str(total_boosts), inline=True)
        embed.add_field(name="Boost Tier", value=str(tier) if is_boosting else "N/A", inline=True)

        current_role_list = []
        target_ids = {r.id for r in target.roles}
        for rid in ALL_BOOSTER_ROLES:
            r = ctx.guild.get_role(rid)
            if r:
                has = "✅" if rid in target_ids else "❌"
                current_role_list.append(f"{has} {r.mention}")
        embed.add_field(
            name="Current Booster Roles",
            value="\n".join(current_role_list) if current_role_list else "None",
            inline=False,
        )

        if is_boosting:
            tier_roles = self._tier_roles(tier)
            embed.add_field(
                name="Roles That Would Be Assigned",
                value="\n".join(f"• <@&{rid}>" for rid in tier_roles) or "None",
                inline=False,
            )

        await ctx.send(embed=embed)

    @boost_test.error
    async def boost_test_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use this command.")
        else:
            await ctx.send(f"❌ An error occurred: {error}")

    @commands.command(name="boostcount")
    @commands.has_guild_permissions(administrator=True)
    async def boost_count(self, ctx: commands.Context, member: discord.Member) -> None:
        """Check the total lifetime boosts a user has given. (admins only)
        Usage: !boostcount @user"""
        total = _get_user_boost_count(member.id)
        is_boosting = member.premium_since is not None
        tier = self._get_boost_tier_from_count(total) if is_boosting else 0

        embed = discord.Embed(
            title="Boost Count",
            description=f"Boost history for {member.mention}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Lifetime Boosts Given", value=str(total), inline=True)
        embed.add_field(name="Currently Boosting", value="✅ Yes" if is_boosting else "❌ No", inline=True)
        embed.add_field(name="Current Tier", value=str(tier) if is_boosting else "Not boosting", inline=True)

        await ctx.send(embed=embed)

    @boost_count.error
    async def boost_count_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Usage: `!boostcount @user` — please mention a valid member.")
        else:
            await ctx.send(f"❌ An error occurred: {error}")

    @commands.command(name="boostset")
    @commands.has_guild_permissions(administrator=True)
    async def boost_set(self, ctx: commands.Context, member: discord.Member, count: int) -> None:
        """Manually set a user's lifetime boost count. (admins only)
        Usage: !boostset @user <count>"""
        if count < 0:
            await ctx.send("❌ Count cannot be negative.")
            return

        counts = _load_boost_counts()
        counts[str(member.id)] = count
        _save_boost_counts(counts)

        # Re-sync roles
        await self._sync_booster_roles(member)

        tier = self._get_boost_tier_from_count(count) if member.premium_since else 0
        embed = discord.Embed(
            title="✅ Boost Count Updated",
            description=f"Set {member.mention}'s lifetime boost count to **{count}**",
            color=discord.Color.green(),
        )
        embed.add_field(name="Current Tier", value=str(tier) if member.premium_since and tier else "Not boosting", inline=True)
        await ctx.send(embed=embed)

    @boost_set.error
    async def boost_set_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use this command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Usage: `!boostset @user <count>` — provide a valid member and number.")
        else:
            await ctx.send(f"❌ An error occurred: {error}")

    def _infer_tier_from_roles(self, member: discord.Member) -> int:
        """Infer a booster's tier from their existing booster roles.
        Returns 0-3. Used when a user is actively boosting but has no stored boost count."""
        current_ids = {r.id for r in member.roles}
        for tier, rids in [(3, [ROLE_3_BOOST]), (2, [ROLE_2_BOOST]), (1, [ROLE_1_BOOST_A, ROLE_1_BOOST_B])]:
            if any(rid in current_ids for rid in rids):
                return tier
        return 1  # Actively boosting but no booster roles = minimum tier 1

    @commands.command(name="boostrefresh")
    @commands.has_guild_permissions(administrator=True)
    async def boost_refresh(self, ctx: commands.Context) -> None:
        """Scan all members, sync booster roles, and re-send DM notifications. (admins only)
        Usage: !boostrefresh"""
        guild = ctx.guild
        if not guild:
            return

        # Gather members
        status = await ctx.send("🔄 Scanning all members for boost status...")

        boosting_members = []
        non_boosting_with_roles = []

        for member in guild.members:
            if member.bot:
                continue
            has_booster_role = any(rid in {r.id for r in member.roles} for rid in ALL_BOOSTER_ROLES)
            if member.premium_since is not None:
                boosting_members.append(member)
            elif has_booster_role:
                non_boosting_with_roles.append(member)

        total = len(boosting_members) + len(non_boosting_with_roles)
        if total == 0:
            await status.edit(content="✅ No members need booster role updates.")
            return

        # Ensure every boosting member has at least 1 stored boost count
        for member in boosting_members:
            count = _get_user_boost_count(member.id)
            if count < 1:
                # Infer from existing roles
                inferred = self._infer_tier_from_roles(member)
                counts = _load_boost_counts()
                counts[str(member.id)] = inferred
                _save_boost_counts(counts)

        # Compute per-user breakdowns for approval
        booster_details = []
        for member in boosting_members:
            count = _get_user_boost_count(member.id)
            tier = self._get_boost_tier(member)
            if count < 1:
                count = self._infer_tier_from_roles(member)
                tier = count
            booster_details.append((member, count, tier))

        stale_details = []
        for member in non_boosting_with_roles:
            roles_to_remove = []
            for rid in ALL_BOOSTER_ROLES:
                if rid in {r.id for r in member.roles} and _bot_gave_role(member.id, rid):
                    r = ctx.guild.get_role(rid)
                    if r:
                        roles_to_remove.append(r.name)
            stale_details.append((member.mention, roles_to_remove))

        # Build summary
        summary_lines = [
            f"**{len(boosting_members)}** actively boosting members will be processed:",
        ]

        # Show boosting members breakdown (up to 15 to avoid huge messages)
        for member, count, tier in booster_details[:15]:
            summary_lines.append(f"  • {member.mention} — {count} boost{'s' if count != 1 else ''}, Tier {tier}")
        if len(booster_details) > 15:
            summary_lines.append(f"  ... and {len(booster_details) - 15} more boosters")

        summary_lines.append("")
        summary_lines.append(f"**{len(non_boosting_with_roles)}** non-boosters with bot-assigned roles to clean:")
        for mention, roles in stale_details[:15]:
            if roles:
                summary_lines.append(f"  • {mention} — will lose: {', '.join(roles)}")
            else:
                summary_lines.append(f"  • {mention} — no bot-assigned roles (nothing to remove)")
        if len(stale_details) > 15:
            summary_lines.append(f"  ... and {len(stale_details) - 15} more non-boosters")

        summary_lines.append("")
        summary_lines.append("⚠️ Only roles the bot gave will be removed from non-boosters.")

        import uuid
        token = uuid.uuid4().hex[:8].upper()
        confirm_embed = discord.Embed(
            title="⚠️ Confirm Boost Refresh",
            description="\n".join(summary_lines) + f"\n\nTo confirm, type the following token in this channel:\n```{token}```",
            color=discord.Color.gold()
        )
        await status.edit(content=None, embed=confirm_embed)

        def check(m: discord.Message):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except Exception:
            await ctx.send("⏰ Timed out. No changes were made.")
            return

        if msg.content.strip() != token:
            await ctx.send("❌ Token mismatch. No changes were made.")
            return

        # Execute
        status = await ctx.send("🔄 Executing boost refresh...")
        processed = 0
        synced = 0
        dmed = 0
        cleaned = 0
        failed = 0

        for member in boosting_members:
            try:
                tier = self._get_boost_tier(member)
                await self._sync_booster_roles(member)
                synced += 1
                await self._dm_boost_started(member, tier)
                dmed += 1
            except Exception:
                failed += 1
            processed += 1
            if processed % 10 == 0:
                await status.edit(
                    content=f"🔄 **{processed}/{total}** — {synced} synced, {dmed} DMed, {cleaned} cleaned, {failed} failed"
                )
            await asyncio.sleep(0.25)

        for member in non_boosting_with_roles:
            try:
                await self._sync_booster_roles(member)
                cleaned += 1
            except Exception:
                failed += 1
            processed += 1
            if processed % 10 == 0:
                await status.edit(
                    content=f"🔄 **{processed}/{total}** — {synced} synced, {dmed} DMed, {cleaned} cleaned, {failed} failed"
                )
            await asyncio.sleep(0.25)

        result = discord.Embed(
            title="✅ Boost Refresh Complete",
            color=discord.Color.green()
        )
        result.add_field(name="Roles Synced", value=str(synced), inline=True)
        result.add_field(name="DMs Sent", value=str(dmed), inline=True)
        result.add_field(name="Stale Roles Cleaned", value=str(cleaned), inline=True)
        result.add_field(name="Failed", value=str(failed), inline=True)
        result.add_field(name="Total Processed", value=str(processed), inline=True)
        await status.edit(content=None, embed=result)

    @boost_refresh.error
    async def boost_refresh_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need administrator permissions to use this command.")
        else:
            await ctx.send(f"❌ An error occurred: {error}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BoostPerksCog(bot))