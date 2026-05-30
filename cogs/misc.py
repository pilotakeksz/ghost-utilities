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
import zipfile
import re


ALLOWED_TUNA_USER_ID = 840949634071658507

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
    async def tuna_role_add(self, ctx, user: discord.Member, *, role_name: str):
        """Add a role to a user. (admins only)"""
        try:
            role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
            if not role:
                await ctx.send(f"❌ Role '{role_name}' not found.")
                return

            if role in user.roles:
                await ctx.send(f"❌ {user.mention} already has the role {role.mention}")
                return

            await user.add_roles(role)
            embed = discord.Embed(
                title="✅ Role Added",
                description=f"Successfully added {role.mention} to {user.mention}",
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
    async def tuna_role_remove(self, ctx, user: discord.Member, *, role_name: str):
        """Remove a role from a user. (admins only)"""
        try:
            role = discord.utils.get(ctx.guild.roles, name=role_name)
            if not role:
                await ctx.send(f"❌ Role '{role_name}' not found.")
                return
            
            if role not in user.roles:
                await ctx.send(f"❌ {user.mention} doesn't have the role {role.mention}")
                return
            
            await user.remove_roles(role)
            embed = discord.Embed(
                title="✅ Role Removed",
                description=f"Successfully removed {role.mention} from {user.mention}",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ I don't have permission to manage roles.")
        except Exception as e:
            await ctx.send(f"❌ An error occurred: {str(e)}")

    @tuna_role.command(name="members")
    @commands.has_guild_permissions(administrator=True)
    async def tuna_role_members(self, ctx, *, role_name: str):
        """List members who have a given role (admins only)."""
        role = None
        if role_name.startswith("<@&") and role_name.endswith(">"):
            try:
                role_id = int(role_name[3:-1])
                role = ctx.guild.get_role(role_id)
            except ValueError:
                role = None
        if role is None:
            role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role is None:
            await ctx.send(f"❌ Role '{role_name}' not found.")
            return

        members = [member.mention for member in role.members]
        if not members:
            await ctx.send(f"No members have {role.mention}.")
            return

        joined = ", ".join(members)
        if len(joined) > 3800:
            await ctx.send(f"Members with {role.mention} (total {len(members)}):")
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
            title=f"Members with {role.name}",
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
                try:
                    if ctx.guild and target.isdigit():
                        role_candidate = ctx.guild.get_role(int(target))
                        if role_candidate:
                            role = role_candidate
                except Exception:
                    role = None

            if role is None:
                role = discord.utils.get(ctx.guild.roles, name=target) if ctx.guild else None
            if role:
                sent_count = 0
                failed_count = 0
                
                for member in role.members:
                    try:
                        await member.send(f"**Message from {ctx.guild.name} (via {role.name}):**\n{message}")
                        sent_count += 1
                    except:
                        failed_count += 1
                
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

async def setup(bot: commands.Bot):
    await bot.add_cog(MiscCog(bot))
