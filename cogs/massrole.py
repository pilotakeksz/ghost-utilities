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
                embed = discord.Embed(
                    title="❌ Invalid Target Role",
                    description=(
                        f"Target role has sensitive permissions: `{', '.join(dangerous)}`. "
                        "This command cannot assign roles with elevated permissions."
                    ),
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return

        bot_top_role = guild.me.top_role
        if target_role >= bot_top_role:
            embed = discord.Embed(
                title="❌ Cannot Assign Role",
                description=f"**{target_role.name}** is at or above my highest role. I can't assign it.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            return

        members = [m for m in source_role.members if target_role not in m.roles]

        if not members:
            embed = discord.Embed(
                title="✅ No Action Needed",
                description=f"No members with {source_role.mention} are missing {target_role.mention}.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            return

        token = uuid.uuid4().hex[:8].upper()
        confirm_embed = discord.Embed(
            title="⚠️ Confirm Mass Role Assignment",
            description=(
                f"You are about to give **{target_role.name}** to **{len(members)}** member(s) "
                f"who have **{source_role.name}**.\n\n"
                f"To confirm, type the following token in this channel:\n"
                f"```{token}```"
            ),
            color=discord.Color.gold()
        )
        await ctx.send(embed=confirm_embed)

        def check(m: discord.Message):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=60)
        except Exception:
            timeout_embed = discord.Embed(
                title="⏰ Timed Out",
                description="No roles were assigned.",
                color=discord.Color.red()
            )
            await ctx.send(embed=timeout_embed)
            return

        if msg.content.strip() != token:
            mismatch_embed = discord.Embed(
                title="❌ Token Mismatch",
                description="No roles were assigned.",
                color=discord.Color.red()
            )
            await ctx.send(embed=mismatch_embed)
            return

        status_embed = discord.Embed(
            title="⏳ Assigning Roles...",
            description=f"Assigning **{target_role.name}** to **{len(members)}** member(s)...",
            color=discord.Color.blurple()
        )
        status = await ctx.send(embed=status_embed)
        success = 0
        failed = 0
        for member in members:
            try:
                await member.add_roles(target_role, reason=f"massrole by {ctx.author}")
                success += 1
            except Exception:
                failed += 1

        result_embed = discord.Embed(
            title="✅ Mass Role Complete",
            color=discord.Color.green()
        )
        result_embed.add_field(name="Role Assigned", value=target_role.name, inline=True)
        result_embed.add_field(name="Source Role", value=source_role.name, inline=True)
        result_embed.add_field(name="Success", value=str(success), inline=True)
        result_embed.add_field(name="Failed", value=str(failed), inline=True)
        await status.edit(embed=result_embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MassRoleCog(bot))