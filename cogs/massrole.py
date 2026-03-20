from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import uuid
from typing import Optional


ROLE_ADMIN = 1318181592719687681


class MassRoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="massrole")
    @commands.has_guild_permissions(administrator=True)
    async def massrole(self, ctx: commands.Context, source_role: discord.Role, target_role: discord.Role):
        """Give every member with source_role the target_role.
        Usage: !massrole @SourceRole @TargetRole"""
        guild = ctx.guild
        if guild is None:
            return

        if target_role.permissions.value != 0:
            dangerous = [
                name for name, val in iter(target_role.permissions)
                if val and name in (
                    "administrator", "ban_members", "kick_members", "manage_guild",
                    "manage_roles", "manage_channels", "manage_webhooks",
                    "manage_expressions", "mention_everyone", "moderate_members",
                )
            ]
            if dangerous:
                await ctx.send(
                    f"❌ Target role has sensitive permissions: `{', '.join(dangerous)}`. "
                    f"This command cannot assign roles with elevated permissions."
                )
                return

        bot_top_role = guild.me.top_role
        if target_role >= bot_top_role:
            await ctx.send(
                f"❌ **{target_role.name}** is at or above my highest role. I can't assign it."
            )
            return

        members = [m for m in source_role.members if target_role not in m.roles]

        if not members:
            await ctx.send(f"No members with {source_role.mention} are missing {target_role.mention}.")
            return

        token = uuid.uuid4().hex[:8].upper()
        await ctx.send(
            f"You are about to give **{target_role.mention}** to **{len(members)}** member(s) "
            f"who have **{source_role.mention}**.\n\n"
            f"To confirm, type the following token in this channel:\n"
            f"```{token}```",
            allowed_mentions=discord.AllowedMentions.none()
        )

        def check(m: discord.Message):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except Exception:
            await ctx.send("⏰ Timed out. No roles were assigned.")
            return

        if msg.content.strip() != token:
            await ctx.send("❌ Token mismatch. No roles were assigned.")
            return

        status = await ctx.send(f"⏳ Assigning {target_role.mention} to {len(members)} member(s)...")
        success = 0
        failed = 0
        for member in members:
            try:
                await member.add_roles(target_role, reason=f"massrole by {ctx.author}")
                success += 1
            except Exception:
                failed += 1

        lines = [f"✅ Done. Assigned **{target_role.name}** to **{success}** member(s)."]
        if failed:
            lines.append(f"⚠️ Failed for {failed} member(s) (missing permissions or left server).")
        await status.edit(content="\n".join(lines))


async def setup(bot: commands.Bot):
    await bot.add_cog(MassRoleCog(bot))