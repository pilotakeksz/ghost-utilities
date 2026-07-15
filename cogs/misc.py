from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
import time
from io import BytesIO
import asyncio
try:
    from PIL import Image
except Exception:
    Image = None

import aiohttp
import json
import zipfile
import re
import os
import sys


ALLOWED_TUNA_USER_ID = 840949634071658507

# Embed persistence helpers (reuse from embed.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cogs.embed import _load_view_records, _parse_embed_file, NO_MENTIONS, PERSISTENT_VIEWS_FILE
sys.path.pop(0)


def resolve_role(ctx, argument: str) -> discord.Role | None:
    """Resolve a role by ID, mention (<@&...>), or name."""
    if not ctx.guild:
        return None
    # Try mention <@&123>
    if argument.startswith("<@&") and argument.endswith(">"):
        try:
            role_id = int(argument[3:-1])
            role = ctx.guild.get_role(role_id)
            if role:
                return role
        except ValueError:
            pass
    # Try raw ID
    if argument.isdigit():
        role = ctx.guild.get_role(int(argument))
        if role:
            return role
    # Try name (case-insensitive)
    role = discord.utils.find(lambda r: r.name.lower() == argument.lower(), ctx.guild.roles)
    if role:
        return role
    return None


class MiscCog(commands.Cog):
    def __init__(self, bot: commands.Bot):

        self.bot = bot
        self.start_time = time.time()

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        """Simple ping command to check bot responsiveness."""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latency: {latency}ms",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="server_info", description="Get server information")
    async def server_info(self, interaction: discord.Interaction):
        """Display basic server information."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Server Information: {guild.name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Members", value=guild.member_count, inline=True)
        embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        
        await interaction.response.send_message(embed=embed)

    @commands.command(name="ping")
    async def ping_prefix(self, ctx):
        """Simple ping command to check bot responsiveness."""
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latency: {latency}ms",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="uptime")
    async def uptime(self, ctx):
        """Shows how long the bot has been running."""
        uptime_seconds = int(time.time() - self.start_time)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        
        uptime_str = ""
        if days > 0:
            uptime_str += f"{days}d "
        if hours > 0:
            uptime_str += f"{hours}h "
        if minutes > 0:
            uptime_str += f"{minutes}m "
        uptime_str += f"{seconds}s"
        
        embed = discord.Embed(
            title="⏰ Bot Uptime",
            description=f"I've been running for **{uptime_str}**",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @commands.group(name="tuna")
    @commands.has_guild_permissions(administrator=True)
    async def tuna(self, ctx):
        """Tuna utility commands. Only server admins may use these."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `!tuna role` or `!tuna dm` for available commands.")

    @tuna.group(name="role")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_role(self, ctx):
        """Role management commands (admins only)."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `!tuna role add`, `!tuna role list`, or `!tuna role remove`")

    @tuna.group(name="create")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_create(self, ctx):
        """Creation utilities for tuna (admins only)."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `!tuna create role <name> [hexcolor]`")

    @tuna_role.command(name="add")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_role_add(self, ctx, user: discord.Member, *, role: str):
        """Add a role to a user. Accepts role name, ID, or mention. (admins only)"""
        try:
            resolved = resolve_role(ctx, role)
            if not resolved:
                await ctx.send(f"❌ Role '{role}' not found.")
                return

            if resolved in user.roles:
                await ctx.send(f"❌ {user.mention} already has the role {resolved.mention}")
                return

            await user.add_roles(resolved)
            embed = discord.Embed(
                title="✅ Role Added",
                description=f"Successfully added {resolved.mention} to {user.mention}",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)

        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage roles.")
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {str(e)}")

    @tuna_role.command(name="list")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_role_list(self, ctx, user: discord.Member):
        """List all roles for a user. (admins only)"""
        roles = [role.mention for role in user.roles if role.name != "@everyone"]
        
        if not roles:
            await ctx.send(f"{user.mention} has no roles.")
            return
        
        embed = discord.Embed(
            title=f"Roles for {user.display_name}",
            description="\n".join(roles),
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await ctx.send(embed=embed)

    @tuna_role.command(name="remove")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_role_remove(self, ctx, user: discord.Member, *, role: str):
        """Remove a role from a user. Accepts role name, ID, or mention. (admins only)"""
        try:
            resolved = resolve_role(ctx, role)
            if not resolved:
                await ctx.send(f"❌ Role '{role}' not found.")
                return
            
            if resolved not in user.roles:
                await ctx.send(f"❌ {user.mention} doesn't have the role {resolved.mention}")
                return
            
            await user.remove_roles(resolved)
            embed = discord.Embed(
                title="✅ Role Removed",
                description=f"Successfully removed {resolved.mention} from {user.mention}",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage roles.")
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {str(e)}")

    @tuna_role.command(name="members")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_role_members(self, ctx, *, role: str):
        """List members who have a given role (admins only)."""
        resolved = resolve_role(ctx, role)
        if resolved is None:
            await ctx.send(f"❌ Role '{role}' not found.")
            return

        members = [member.mention for member in resolved.members]
        if not members:
            await ctx.send(f"No members have {resolved.mention}.")
            return

        joined = ", ".join(members)
        if len(joined) > 3800:
            await ctx.send(f"Members with {resolved.mention} (total {len(members)}):")
            chunk = []
            length = 0
            for m in members:
                if length + len(m) + 2 > 1900:
                    await ctx.send(", ".join(chunk))
                    chunk = [m]
                    length = len(m)
                else:
                    chunk.append(m)
                    length += len(m) + 2
            if chunk:
                await ctx.send(", ".join(chunk))
            return

        embed = discord.Embed(
            title=f"Members with {resolved.name}",
            description=joined,
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)

    @tuna.command(name="dm")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_dm(self, ctx, target, *, message: str):
        """Send a DM to a user or all members with a specific role. (admins only)"""
        try:
            role = None
            try:
                if target.startswith('<@') and target.endswith('>'):
                    user_id = int(target[2:-1].replace('!', ''))
                    user = await self.bot.fetch_user(user_id)
                    await user.send(f"**Message from {ctx.guild.name}:**\n{message}")
                    await ctx.send(f"✅ DM sent to {user.mention}")
                    return
                else:
                    user_id = int(target)
                    user = await self.bot.fetch_user(user_id)
                    await user.send(f"**Message from {ctx.guild.name}:**\n{message}")
                    await ctx.send(f"✅ DM sent to {user.mention}")
                    return
            except (ValueError, discord.NotFound):
                role = resolve_role(ctx, target)

            if role is None:
                role = discord.utils.get(ctx.guild.roles, name=target) if ctx.guild else None
            if role:
                member_count = len(role.members)
                if member_count == 0:
                    await ctx.send(f"❌ No members have the role {role.mention}.")
                    return

                # Confirmation prompt
                confirm_msg = await ctx.send(
                    f"⚠️ **Are you sure?** This will DM **{member_count}** members with role {role.mention}.\n"
                    f"React with ✅ to confirm or ❌ to cancel."
                )
                await confirm_msg.add_reaction("✅")
                await confirm_msg.add_reaction("❌")

                def check(reaction, user):
                    return (
                        user == ctx.author
                        and reaction.message.id == confirm_msg.id
                        and str(reaction.emoji) in ("✅", "❌")
                    )

                try:
                    reaction, _ = await self.bot.wait_for("reaction_add", timeout=30.0, check=check)
                except asyncio.TimeoutError:
                    await confirm_msg.edit(content="⏱️ Confirmation timed out. No DMs were sent.")
                    return

                if str(reaction.emoji) == "❌":
                    await confirm_msg.edit(content="❌ Cancelled. No DMs were sent.")
                    return

                await confirm_msg.edit(content=f"📨 Sending DMs to {member_count} members with {role.mention}...")

                sent_count = 0
                failed_count = 0
                
                for member in role.members:
                    try:
                        await member.send(f"**Message from {ctx.guild.name} (via {role.name}):**\n{message}")
                        sent_count += 1
                    except:
                        failed_count += 1
                    await asyncio.sleep(0.25)  # small delay to avoid rate limits
                
                embed = discord.Embed(
                    title="✅ DMs Sent",
                    description=f"Sent to {sent_count} members with role {role.mention}",
                    color=discord.Color.green()
                )
                if failed_count > 0:
                    embed.add_field(name="Failed", value=f"{failed_count} members couldn't receive DMs", inline=False)
                await ctx.send(embed=embed)
                return
            
            await ctx.send("❌ Could not find user or role. Use @user, user ID, or role name.")
            
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {str(e)}")

    @tuna.command(name="say")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_say(self, ctx, channel: discord.TextChannel = None, *, message: str = None):
        """Send a message to a channel. (admins only)"""
        if message is None and channel is None:
            await ctx.send("Usage: `!tuna say [#channel] <message>`")
            return
        if message is None and channel is not None:
            await ctx.send("Usage: `!tuna say [#channel] <message>`")
            return
        target_channel = channel or ctx.channel
        try:
            await target_channel.send(message)
            if target_channel.id != ctx.channel.id:
                await ctx.send(f"✅ Sent message in {target_channel.mention}")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to send messages in that channel.")
        except Exception as e:
            await ctx.send(f"❌ Failed to send message: {str(e)}")

    @tuna.command(name="servers")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_servers(self, ctx):
        """List servers the bot is in (admins only)."""
        guilds = list(self.bot.guilds)
        guilds_sorted = sorted(guilds, key=lambda g: g.member_count or 0, reverse=True)
        total = len(guilds_sorted)
        lines = [f"{g.name} — ID: `{g.id}` — Members: {g.member_count}" for g in guilds_sorted]
        header = f"I am in {total} server(s):\n"
        text = header + "\n".join(lines)
        if len(text) <= 1900:
            await ctx.send("```\n" + text + "\n```")
        else:
            await ctx.send(header)
            chunk = []
            size = 0
            for line in lines:
                if size + len(line) + 1 > 1900:
                    await ctx.send("```\n" + "\n".join(chunk) + "\n```")
                    chunk = [line]
                    size = len(line)
                else:
                    chunk.append(line)
                    size += len(line) + 1
            if chunk:
                await ctx.send("```\n" + "\n".join(chunk) + "\n```")

    @tuna.command(name="perms")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_perms(self, ctx, channel: discord.TextChannel = None):
        """Show the bot's permissions in the guild or a specified channel. (admins only)"""
        target_channel = channel or ctx.channel
        me = ctx.guild.me
        perms = target_channel.permissions_for(me)
        true_perms = [
            name.replace('_', ' ').title()
            for name, value in perms if value
        ]
        false_perms = [
            name.replace('_', ' ').title()
            for name, value in perms if not value
        ]

        embed = discord.Embed(
            title="Bot Permissions",
            description=f"Channel: {target_channel.mention}",
            color=discord.Color.teal()
        )
        embed.add_field(name="Allowed", value=", ".join(true_perms) or "None", inline=False)
        embed.add_field(name="Denied", value=", ".join(false_perms) or "None", inline=False)
        await ctx.send(embed=embed)

    @tuna.command(name="invite")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_invite(self, ctx):
        """Show OAuth2 invite links for the bot (admins only)."""
        client_id = self.bot.user.id if self.bot.user else None
        if client_id is None:
            await ctx.send("❌ Unable to determine bot user ID.")
            return
        scopes = "bot%20applications.commands"
        base = f"https://discord.com/oauth2/authorize?client_id={client_id}&scope={scopes}"
        basic_url = base
        admin_url = base + "&permissions=8"
        embed = discord.Embed(title="Invite Links", color=discord.Color.gold())
        embed.add_field(name="Basic", value=f"[Add Bot]({basic_url})", inline=False)
        embed.add_field(name="Admin", value=f"[Add Bot (Administrator)]({admin_url})", inline=False)
        await ctx.send(embed=embed)

    @tuna.command(name="invite_all")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_invite_all(self, ctx, include_admin: bool = False):
        """DM invite link(s) to each guild owner for all servers the bot is in (admins only).
        Usage: !tuna invite_all [include_admin=True]"""
        client_id = self.bot.user.id if self.bot.user else None
        if client_id is None:
            await ctx.send("❌ Unable to determine bot user ID.")
            return

        scopes = "bot%20applications.commands"
        base = f"https://discord.com/oauth2/authorize?client_id={client_id}&scope={scopes}"
        basic_url = base
        admin_url = base + "&permissions=8"

        sent = 0
        failed = 0
        skipped = 0

        for guild in list(self.bot.guilds):
            try:
                owner = guild.owner
                if owner is None and getattr(guild, "owner_id", None):
                    try:
                        owner = await self.bot.fetch_user(guild.owner_id)
                    except Exception:
                        owner = None

                if owner is None:
                    skipped += 1
                    continue

                embed = discord.Embed(
                    title=f"Invite links for {self.bot.user.name}",
                    description=f"Provided on behalf of the bot in `{guild.name}` (ID: {guild.id})",
                    color=discord.Color.gold()
                )
                embed.add_field(name="Basic", value=f"[Add Bot]({basic_url})", inline=False)
                if include_admin:
                    embed.add_field(name="Admin", value=f"[Add Bot (Administrator)]({admin_url})", inline=False)
                embed.set_footer(text=f"Server: {guild.name}")

                try:
                    await owner.send(embed=embed)
                    sent += 1
                except discord.Forbidden:
                    try:
                        sc = guild.system_channel
                        if sc and sc.permissions_for(guild.me).send_messages:
                            await sc.send(f"{owner.mention} — I'm posting invite links here because I couldn't DM you.", embed=embed)
                            sent += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1
            except Exception:
                failed += 1

            await asyncio.sleep(0.25)

        await ctx.send(f"✅ Invite distribution complete — sent: {sent}, failed: {failed}, skipped (no owner): {skipped}")

    @tuna.command(name="shard")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_shard(self, ctx):
        """Show shard info (admins only)."""
        shard_count = self.bot.shard_count or 1
        latencies = getattr(self.bot, "latencies", None) or []
        if not latencies:
            latencies = [(0, self.bot.latency)]
        per_shard = {}
        for g in self.bot.guilds:
            sid = g.shard_id if g.shard_id is not None else 0
            per_shard[sid] = per_shard.get(sid, 0) + 1
        lines = []
        for sid, latency in sorted(latencies, key=lambda x: x[0]):
            ms = int(latency * 1000)
            count = per_shard.get(sid, 0)
            lines.append(f"Shard {sid}: {ms}ms — {count} guilds")
        embed = discord.Embed(title="Shard Info", color=discord.Color.purple())
        embed.add_field(name="Shard Count", value=str(shard_count), inline=True)
        embed.add_field(name="Total Guilds", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Latencies", value="\n".join(lines) or "N/A", inline=False)
        await ctx.send(embed=embed)

    @tuna.command(name="stats")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_stats(self, ctx):
        """Show system and runtime stats for the bot (admins only)."""
        uptime_seconds = int(time.time() - self.start_time)
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_str = (f"{days}d " if days else "") + (f"{hours}h " if hours else "") + (f"{minutes}m " if minutes else "") + f"{seconds}s"

        import sys as _sys  # local import to avoid global dependency
        pyver = f"{_sys.version_info.major}.{_sys.version_info.minor}.{_sys.version_info.micro}"
        dpyver = discord.__version__
        guilds = len(self.bot.guilds)
        users = sum(g.member_count or 0 for g in self.bot.guilds)

        cpu = mem = None
        try:
            import psutil  # type: ignore
            process = psutil.Process()
            with process.oneshot():
                rss = process.memory_info().rss
                mem = f"{rss / (1024*1024):.2f} MiB"
                cpu = f"{psutil.cpu_percent(interval=0.2):.1f}%"
        except Exception:
            pass

        embed = discord.Embed(title="Bot Stats", color=discord.Color.green())
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Guilds", value=str(guilds), inline=True)
        embed.add_field(name="Users (sum)", value=str(users), inline=True)
        embed.add_field(name="Python", value=pyver, inline=True)
        embed.add_field(name="discord.py", value=dpyver, inline=True)
        if mem:
            embed.add_field(name="Memory", value=mem, inline=True)
        if cpu:
            embed.add_field(name="CPU", value=cpu, inline=True)
        await ctx.send(embed=embed)

    @tuna_create.command(name="role")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_create_role(self, ctx, role_name: str, color: str = None):
        """Create a role. (admins only)"""
        is_admin = getattr(ctx.author.guild_permissions, "administrator", False)
        if ctx.author.id != ALLOWED_TUNA_USER_ID and not is_admin:
            await ctx.send("❌ You are not allowed to use tuna commands.")
            return

        role_color = None
        c = None
        if color:
            c = color.strip()
            if c.startswith("#"):
                c = c[1:]
            if len(c) == 3:
                c = "".join(ch * 2 for ch in c)
            if len(c) != 6:
                await ctx.send("❌ Invalid color. Use 3- or 6-digit hex like `#F80` or `#FF8800`.")
                return
            try:
                color_val = int(c, 16)
                role_color = discord.Color(value=color_val)
            except Exception:
                await ctx.send("❌ Invalid color. Use hex like `#RRGGBB` or `RRGGBB`.")
                return

        try:
            guild = ctx.guild
            if not guild:
                await ctx.send("❌ This command must be run in a server.")
                return
            role = await guild.create_role(
                name=role_name,
                color=role_color or discord.Color.default(),
                mentionable=False,
                reason=f"Created by {ctx.author}"
            )
            embed = discord.Embed(title="✅ Role Created", description=f"Created role {role.mention}", color=discord.Color.green())
            embed.add_field(name="Name", value=role.name, inline=True)
            embed.add_field(name="ID", value=str(role.id), inline=True)
            if c:
                embed.add_field(name="Color", value=f"#{c.upper()}", inline=True)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to create roles.")
        except Exception as e:
            await ctx.send(f"❌ Failed to create role: {e}")

    @tuna.command(name="colour")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_colour(self, ctx, hex_color: str):
        """Show a small image filled with the given hex colour. (admins only)"""
        is_admin = getattr(ctx.author.guild_permissions, "administrator", False)
        if ctx.author.id != ALLOWED_TUNA_USER_ID and not is_admin:
            await ctx.send("❌ You are not allowed to use tuna commands.")
            return

        c = hex_color.strip().lstrip("#")
        if len(c) not in (3, 6):
            await ctx.send("❌ Invalid color. Provide 3- or 6-digit hex, e.g. `FF8800` or `F80`.")
            return
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        try:
            value = int(c, 16)
        except ValueError:
            await ctx.send("❌ Invalid hex value.")
            return

        r = (value >> 16) & 0xFF
        g = (value >> 8) & 0xFF
        b = value & 0xFF

        try:
            me = ctx.guild.me if ctx.guild else None
            if me and not ctx.channel.permissions_for(me).attach_files:
                await ctx.send("❌ I don't have permission to attach files in this channel. Showing fallback embed instead.")
                embed = discord.Embed(title=f"Colour: #{c.upper()}", color=discord.Color(value))
                embed.description = f"RGB: {r}, {g}, {b}"
                await ctx.send(embed=embed)
                return
        except Exception:

            pass

        if Image is None:
            embed = discord.Embed(title=f"Colour: #{c.upper()}", color=discord.Color(value))
            embed.description = f"RGB: {r}, {g}, {b}\n\n(Pillow not installed — install with `pip install Pillow` to get an image attachment.)"
            await ctx.send(embed=embed)
            return

        try:
            img = Image.new("RGB", (256, 256), (r, g, b))
            bio = BytesIO()
            img.save(bio, "PNG")
            bio.seek(0)
            file = discord.File(bio, filename="colour.png")

            embed = discord.Embed(title=f"Colour: #{c.upper()}", color=discord.Color(value))
            embed.set_image(url="attachment://colour.png")
            embed.add_field(name="RGB", value=f"{r}, {g}, {b}", inline=True)

            await ctx.send(embed=embed, file=file)
        except Exception as e:
            await ctx.send(f"❌ Failed to send image attachment: {e}")
            embed = discord.Embed(title=f"Colour: #{c.upper()}", color=discord.Color(value))
            embed.description = f"RGB: {r}, {g}, {b}"
            await ctx.send(embed=embed)

    @tuna.command(name="emojis")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_emojis(self, ctx):
        """Create a zip of all custom emojis in this guild and send it."""
        guild = ctx.guild
        if not guild:
            await ctx.send("This command must be used in a server.")
            return

        emojis = guild.emojis
        if not emojis:
            await ctx.send("No custom emojis in this server.")
            return

        msg = await ctx.send("Creating emoji zip — this may take a moment...")
        bio = BytesIO()
        try:
            with zipfile.ZipFile(bio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                async with aiohttp.ClientSession() as session:
                    used_filenames = set()
                    for e in emojis:
                        url = str(e.url)
                        ext = "gif" if getattr(e, "animated", False) else "png"
                        base_name = re.sub(r'[^A-Za-z0-9_.-]+', '_', (e.name or '').strip())
                        if not base_name:
                            base_name = f"emoji_{e.id}"

                        filename = f"{base_name}.{ext}"
                        if filename in used_filenames:
                            idx = 1
                            while True:
                                candidate = f"{base_name}_{idx}.{ext}"
                                if candidate not in used_filenames:
                                    filename = candidate
                                    break
                                idx += 1

                        used_filenames.add(filename)

                        try:
                            async with session.get(url) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    zf.writestr(filename, data)
                        except Exception:
                            continue
            bio.seek(0)
            file = discord.File(bio, filename=f"{guild.name}_emojis.zip")
            await msg.edit(content="Here is the emoji zip:")
            await ctx.send(file=file)
        except Exception as exc:
            await msg.edit(content="Failed to create emoji zip.")
            await ctx.send(f"Error: {exc}")

    # ── New utility commands ──────────────────────────────────────────────

    @tuna.command(name="userinfo")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_userinfo(self, ctx, user: discord.Member = None):
        """Show detailed info about a user. (admins only)"""
        user = user or ctx.author

        roles = [role.mention for role in user.roles if role.name != "@everyone"]
        joined_at = f"<t:{int(user.joined_at.timestamp())}:F>" if user.joined_at else "Unknown"
        created_at = f"<t:{int(user.created_at.timestamp())}:F>"

        embed = discord.Embed(
            title=f"User Info: {user.display_name}",
            color=user.top_role.color if user.top_role.color.value else discord.Color.blurple()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="ID", value=f"`{user.id}`", inline=True)
        embed.add_field(name="Bot", value="Yes" if user.bot else "No", inline=True)
        embed.add_field(name="Joined Server", value=joined_at, inline=True)
        embed.add_field(name="Joined Discord", value=created_at, inline=True)
        embed.add_field(name="Top Role", value=user.top_role.mention if user.top_role.name != "@everyone" else "None", inline=True)
        embed.add_field(name=f"Roles ({len(roles)})", value=", ".join(roles) if roles else "None", inline=False)
        if user.activities:
            activities = "\n".join(
                f"• {a.name}" for a in user.activities if a.name
            )
            if activities:
                embed.add_field(name="Activities", value=activities, inline=False)

        await ctx.send(embed=embed)

    @tuna.command(name="roleinfo")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_roleinfo(self, ctx, *, role: str):
        """Show detailed info about a role. Accepts name, ID, or mention. (admins only)"""
        resolved = resolve_role(ctx, role)
        if not resolved:
            await ctx.send(f"❌ Role '{role}' not found.")
            return

        perms = []
        perm_map = {
            "administrator": "Administrator",
            "manage_guild": "Manage Server",
            "manage_roles": "Manage Roles",
            "manage_channels": "Manage Channels",
            "manage_messages": "Manage Messages",
            "kick_members": "Kick Members",
            "ban_members": "Ban Members",
            "mention_everyone": "Mention Everyone",
            "moderate_members": "Timeout Members",
        }
        for perm_key, perm_name in perm_map.items():
            if getattr(resolved.permissions, perm_key, False):
                perms.append(perm_name)

        embed = discord.Embed(
            title=f"Role Info: {resolved.name}",
            color=resolved.color if resolved.color.value else discord.Color.blurple()
        )
        embed.add_field(name="Role", value=resolved.mention, inline=True)
        embed.add_field(name="ID", value=f"`{resolved.id}`", inline=True)
        embed.add_field(name="Color", value=str(resolved.color) if resolved.color.value else "Default", inline=True)
        embed.add_field(name="Members", value=str(len(resolved.members)), inline=True)
        embed.add_field(name="Hoisted", value="Yes" if resolved.hoist else "No", inline=True)
        embed.add_field(name="Mentionable", value="Yes" if resolved.mentionable else "No", inline=True)
        embed.add_field(name="Position", value=str(resolved.position), inline=True)
        embed.add_field(name="Created", value=f"<t:{int(resolved.created_at.timestamp())}:F>", inline=True)
        if perms:
            embed.add_field(name="Key Permissions", value=", ".join(perms), inline=False)

        await ctx.send(embed=embed)

    @tuna.command(name="channelinfo")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_channelinfo(self, ctx, channel: discord.TextChannel = None):
        """Show detailed info about a channel. (admins only)"""
        channel = channel or ctx.channel

        embed = discord.Embed(
            title=f"Channel Info: #{channel.name}",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="ID", value=f"`{channel.id}`", inline=True)
        embed.add_field(name="Type", value=str(channel.type).title(), inline=True)
        embed.add_field(name="Topic", value=channel.topic or "No topic", inline=False)
        embed.add_field(name="Category", value=channel.category.name if channel.category else "None", inline=True)
        embed.add_field(name="Position", value=str(channel.position), inline=True)
        embed.add_field(name="NSFW", value="Yes" if channel.is_nsfw() else "No", inline=True)
        embed.add_field(name="Slowmode", value=f"{channel.slowmode_delay}s" if channel.slowmode_delay else "Off", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(channel.created_at.timestamp())}:F>", inline=True)

        await ctx.send(embed=embed)

    @tuna.command(name="guildinfo")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_guildinfo(self, ctx):
        """Show detailed info about the guild. (admins only)"""
        guild = ctx.guild
        if not guild:
            await ctx.send("This command must be used in a server.")
            return

        boost_tier = guild.premium_tier
        boost_count = guild.premium_subscription_count or 0

        embed = discord.Embed(
            title=f"Guild Info: {guild.name}",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        embed.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
        embed.add_field(name="Members", value=str(guild.member_count), inline=True)
        embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
        embed.add_field(name="Boosts", value=f"Tier {boost_tier} ({boost_count} boosts)", inline=True)
        embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:F>", inline=True)
        embed.add_field(name="Verification", value=str(guild.verification_level).title(), inline=True)

        await ctx.send(embed=embed)

    @tuna.command(name="avatar")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_avatar(self, ctx, user: discord.Member = None):
        """Get a user's avatar. (admins only)"""
        user = user or ctx.author

        embed = discord.Embed(
            title=f"{user.display_name}'s Avatar",
            color=discord.Color.blurple()
        )
        embed.set_image(url=user.display_avatar.url)
        embed.add_field(name="Links", value=f"[PNG]({user.display_avatar.with_format('png').url}) | [JPG]({user.display_avatar.with_format('jpg').url}) | [WEBP]({user.display_avatar.with_format('webp').url})", inline=False)
        if user.display_avatar.is_animated():
            embed.add_field(name="GIF", value=f"[GIF]({user.display_avatar.with_format('gif').url})", inline=False)

        await ctx.send(embed=embed)

    @tuna.command(name="servericon")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_servericon(self, ctx):
        """Get the server icon. (admins only)"""
        guild = ctx.guild
        if not guild or not guild.icon:
            await ctx.send("❌ This server has no icon.")
            return

        embed = discord.Embed(
            title=f"{guild.name}'s Icon",
            color=discord.Color.blurple()
        )
        embed.set_image(url=guild.icon.url)
        embed.add_field(name="Links", value=f"[PNG]({guild.icon.with_format('png').url}) | [JPG]({guild.icon.with_format('jpg').url}) | [WEBP]({guild.icon.with_format('webp').url})", inline=False)
        if guild.icon.is_animated():
            embed.add_field(name="GIF", value=f"[GIF]({guild.icon.with_format('gif').url})", inline=False)

        await ctx.send(embed=embed)

    @tuna.command(name="banner")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_banner(self, ctx):
        """Get the server banner. (admins only)"""
        guild = ctx.guild
        if not guild or not guild.banner:
            await ctx.send("❌ This server has no banner.")
            return

        embed = discord.Embed(
            title=f"{guild.name}'s Banner",
            color=discord.Color.blurple()
        )
        embed.set_image(url=guild.banner.url)
        embed.add_field(name="Links", value=f"[PNG]({guild.banner.with_format('png').url}) | [JPG]({guild.banner.with_format('jpg').url}) | [WEBP]({guild.banner.with_format('webp').url})", inline=False)

        await ctx.send(embed=embed)

    @tuna.command(name="nick")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_nick(self, ctx, user: discord.Member, *, nickname: str = None):
        """Change or reset a user's nickname. (admins only)"""
        try:
            await user.edit(nick=nickname)
            if nickname:
                await ctx.send(f"✅ Changed {user.mention}'s nickname to **{nickname}**")
            else:
                await ctx.send(f"✅ Reset {user.mention}'s nickname")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to change that user's nickname.")
        except Exception as e:
            await ctx.send(f"❌ Failed to change nickname: {str(e)}")

    @tuna.command(name="lockdown")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_lockdown(self, ctx, channel: discord.TextChannel = None):
        """Lock a channel by denying send_messages to @everyone. (admins only)"""
        channel = channel or ctx.channel
        try:
            everyone = ctx.guild.default_role
            await channel.set_permissions(everyone, send_messages=False)
            await ctx.send(f"🔒 {channel.mention} has been locked down.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage this channel.")
        except Exception as e:
            await ctx.send(f"❌ Failed to lock channel: {str(e)}")

    @tuna.command(name="unlock")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_unlock(self, ctx, channel: discord.TextChannel = None):
        """Unlock a channel by granting send_messages to @everyone (does not grant view_channel). (admins only)"""
        channel = channel or ctx.channel
        try:
            everyone = ctx.guild.default_role
            await channel.set_permissions(everyone, send_messages=True, view_channel=None)
            await ctx.send(f"🔓 {channel.mention} has been unlocked.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage this channel.")
        except Exception as e:
            await ctx.send(f"❌ Failed to unlock channel: {str(e)}")

    @tuna.command(name="slowmode")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_slowmode(self, ctx, seconds: int, channel: discord.TextChannel = None):
        """Set slowmode delay (in seconds) for a channel. (admins only)"""
        if seconds < 0 or seconds > 21600:
            await ctx.send("❌ Slowmode must be between 0 and 21600 seconds (6 hours).")
            return

        channel = channel or ctx.channel
        try:
            await channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send(f"⏱️ Slowmode disabled in {channel.mention}.")
            else:
                await ctx.send(f"⏱️ Slowmode set to **{seconds}s** in {channel.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to edit this channel.")
        except Exception as e:
            await ctx.send(f"❌ Failed to set slowmode: {str(e)}")

    @tuna.command(name="purge")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_purge(self, ctx, amount: int):
        """Purge a number of messages from the current channel. (admins only)"""
        if amount < 1 or amount > 1000:
            await ctx.send("❌ You can purge between 1 and 1000 messages.")
            return

        try:
            deleted = await ctx.channel.purge(limit=amount + 1)
            # +1 to include the command message
            msg = await ctx.send(f"🗑️ Deleted {len(deleted) - 1} message(s).")
            await asyncio.sleep(3)
            await msg.delete()
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage messages.")
        except Exception as e:
            await ctx.send(f"❌ Failed to purge messages: {str(e)}")

    @tuna.command(name="rename")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_rename(self, ctx, *, new_name: str):
        """Rename the server. (admins only)"""
        if len(new_name) < 2 or len(new_name) > 100:
            await ctx.send("❌ Server name must be between 2 and 100 characters.")
            return

        try:
            old_name = ctx.guild.name
            await ctx.guild.edit(name=new_name)
            await ctx.send(f"✅ Server renamed from **{old_name}** to **{new_name}**.")
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to edit the server.")
        except Exception as e:
            await ctx.send(f"❌ Failed to rename server: {str(e)}")

    @tuna.command(name="rolecolor")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_rolecolor(self, ctx, role: str, color: str):
        """Change a role's color. Accepts hex color (#RRGGBB or RRGGBB). (admins only)"""
        resolved = resolve_role(ctx, role)
        if not resolved:
            await ctx.send(f"❌ Role '{role}' not found.")
            return

        c = color.strip().lstrip("#")
        if len(c) not in (3, 6):
            await ctx.send("❌ Invalid color. Provide 3- or 6-digit hex, e.g. `FF8800` or `F80`.")
            return
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        try:
            color_val = int(c, 16)
            new_color = discord.Color(value=color_val)
        except ValueError:
            await ctx.send("❌ Invalid hex value.")
            return

        try:
            await resolved.edit(color=new_color)
            embed = discord.Embed(
                title="✅ Role Color Updated",
                description=f"Changed {resolved.mention} to `#{c.upper()}`",
                color=new_color
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to edit that role.")
        except Exception as e:
            await ctx.send(f"❌ Failed to change role color: {str(e)}")

    @tuna.command(name="roles")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_roles(self, ctx):
        """List all roles in the server. (admins only)"""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return

        roles = sorted(ctx.guild.roles, key=lambda r: r.position, reverse=True)
        role_list = []
        for r in roles:
            if r.name == "@everyone":
                continue
            role_list.append(f"{r.mention} — ID: `{r.id}` — Members: {len(r.members)}")

        if not role_list:
            await ctx.send("No roles in this server.")
            return

        text = "\n".join(role_list)
        if len(text) <= 1900:
            embed = discord.Embed(
                title=f"Roles in {ctx.guild.name} ({len(role_list)})",
                description=text,
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"**Roles in {ctx.guild.name} ({len(role_list)}):**")
            chunk = []
            size = 0
            for line in role_list:
                if size + len(line) + 1 > 1900:
                    await ctx.send("\n".join(chunk))
                    chunk = [line]
                    size = len(line)
                else:
                    chunk.append(line)
                    size += len(line) + 1
            if chunk:
                await ctx.send("\n".join(chunk))

    @tuna.command(name="categories")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_categories(self, ctx):
        """List all categories and their channels in the server. (admins only)"""
        if not ctx.guild:
            await ctx.send("This command must be used in a server.")
            return

        categories = ctx.guild.by_category
        lines = []
        for cat, channels in categories:
            cat_name = cat.name if cat else "No Category"
            ch_names = [f"  - {ch.mention} (`{ch.id}`)" for ch in channels if isinstance(ch, discord.TextChannel) or isinstance(ch, discord.VoiceChannel)]
            if ch_names:
                lines.append(f"**{cat_name}**")
                lines.extend(ch_names)

        if not lines:
            await ctx.send("No channels found.")
            return

        text = "\n".join(lines)
        if len(text) <= 1900:
            await ctx.send(text)
        else:
            chunk = []
            size = 0
            for line in lines:
                if size + len(line) + 1 > 1900:
                    await ctx.send("\n".join(chunk))
                    chunk = [line]
                    size = len(line)
                else:
                    chunk.append(line)
                    size += len(line) + 1
            if chunk:
                await ctx.send("\n".join(chunk))


    @tuna.group(name="embed")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_embed(self, ctx):
        """Embed management commands (admins only)."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `!tuna embed status`, `!tuna embed restore`, or `!tuna embed export`")

    @tuna_embed.command(name="status")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_embed_status(self, ctx):
        """Show how many persistent embeds are stored. (admins only)"""
        records = _load_view_records()
        if not records:
            await ctx.send("📂 No persistent embed records found.")
            return

        total = len(records)
        per_channel: dict[int, list[int]] = {}
        for r in records:
            cid = r.get("channel_id")
            mid = r.get("message_id")
            if cid is not None:
                per_channel.setdefault(cid, []).append(mid)

        embed = discord.Embed(
            title="📂 Stored Embed Records",
            description=f"**{total}** persistent embed(s) stored across **{len(per_channel)}** channel(s).",
            color=discord.Color.blurple()
        )

        # Show breakdown per channel (up to 10 channels)
        shown = 0
        for cid, mids in per_channel.items():
            if shown >= 10:
                embed.add_field(name="...", value=f"And {len(per_channel) - 10} more channel(s)", inline=False)
                break
            channel = self.bot.get_channel(cid)
            ch_name = f"#{channel.name}" if channel else f"`{cid}` (unknown)"
            embed.add_field(name=ch_name, value=f"{len(mids)} embed(s)", inline=True)
            shown += 1

        footer_parts = []
        alive = sum(1 for r in records if r.get("message_id"))
        if alive:
            footer_parts.append(f"{alive} have message IDs registered")
        if not alive:
            footer_parts.append("No message IDs registered (orphaned)")
        embed.set_footer(text=" | ".join(footer_parts))

        await ctx.send(embed=embed)

    @tuna_embed.command(name="restore")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_embed_restore(self, ctx, channel: discord.TextChannel = None):
        """Re-send all stored embeds to their original channels. (admins only)"""
        records = _load_view_records()
        if not records:
            await ctx.send("📂 No persistent embed records found to restore.")
            return

        target_channel = channel  # None = restore to original channels
        restored = 0
        failed = 0
        status_msg = await ctx.send(f"🔄 Restoring {len(records)} embed(s)...")

        for i, record in enumerate(records):
            source = record.get("source", "")
            ch_id = record.get("channel_id")
            if not source or not ch_id:
                failed += 1
                continue

            # Determine target channel
            ch = target_channel or self.bot.get_channel(ch_id)
            if not ch:
                failed += 1
                continue

            try:
                view = _parse_embed_file(source)
                await ch.send(view=view, allowed_mentions=NO_MENTIONS)
                restored += 1
            except Exception:
                failed += 1

            # Update status every 5 records
            if i > 0 and i % 5 == 0:
                await status_msg.edit(
                    content=f"🔄 Restoring embeds... ({restored} done, {failed} failed, {len(records) - i - 1} remaining)"
                )

            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title="✅ Restore Complete",
            color=discord.Color.green()
        )
        embed.add_field(name="Restored", value=str(restored), inline=True)
        embed.add_field(name="Failed", value=str(failed), inline=True)
        embed.add_field(name="Total Records", value=str(len(records)), inline=True)
        if target_channel:
            embed.add_field(name="Target Channel", value=target_channel.mention, inline=False)
        else:
            embed.add_field(name="Note", value="Embeds were restored to their original channels.", inline=False)

        await status_msg.edit(content=None, embed=embed)

    @tuna_embed.command(name="export")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_embed_export(self, ctx):
        """Export all stored embed records as a JSON file. (admins only)"""
        if not os.path.exists(PERSISTENT_VIEWS_FILE):
            await ctx.send("📂 No persistent view records file found.")
            return

        try:
            # Read the full JSON file
            with open(PERSISTENT_VIEWS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if not data:
                await ctx.send("📂 The persistent views file is empty.")
                return

            # Write to a bytes buffer
            bio = BytesIO()
            bio.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            bio.seek(0)

            file = discord.File(bio, filename="embeds_export.json")
            await ctx.send(
                f"📂 Here are all {len(data)} stored embed record(s):",
                file=file
            )
        except Exception as e:
            await ctx.send(f"❌ Failed to export embed records: {str(e)}")


async def setup(bot: commands.Bot):
    await bot.add_cog(MiscCog(bot))
