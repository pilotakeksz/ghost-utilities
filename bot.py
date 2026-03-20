import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv
import sys
import io
import base64 
import traceback
from aiohttp import web
import json
from datetime import datetime, timezone, date
from typing import Optional
import re



load_dotenv(".env")
load_dotenv(".env.token")


APPLICATION_ID = os.getenv("APPLICATION_ID")
if not APPLICATION_ID:
    print("❌ ERROR: APPLICATION_ID not set in environment variables")
else:
    try:
        APPLICATION_ID = int(APPLICATION_ID)
    except ValueError:
        raise ValueError("APPLICATION_ID must be an integer")


encoded_token = os.getenv("DISCORD_BOT_TOKEN_BASE64")
if not encoded_token:
    raise ValueError("No DISCORD_BOT_TOKEN_BASE64 found in environment variables")

try:
    TOKEN = base64.b64decode(encoded_token).decode("utf-8")
except Exception as e:
    raise ValueError(f"Failed to decode DISCORD_BOT_TOKEN_BASE64: {e}")


LOG_CHANNEL_ID = 1453463104531857548  
LOGS_FOLDER = "logs"  


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=APPLICATION_ID
)


startup_output = io.StringIO()
old_stdout = sys.stdout
old_stderr = sys.stderr
sys.stdout = startup_output
sys.stderr = startup_output

async def log_command_use(kind: str, user: discord.abc.User, guild: Optional[discord.Guild], channel: Optional[discord.abc.Messageable], command_name: str, content: str = "", affected_ids: Optional[list] = None):

    try:
        ts = datetime.now(timezone.utc)

        emb = discord.Embed(title=f"Command: {command_name}", colour=discord.Colour.blurple(), timestamp=ts)
        try:
            emb.add_field(name="Invoker", value=f"{user.mention} ({user.id})", inline=True)
        except Exception:
            emb.add_field(name="Invoker", value=f"{getattr(user,'name',str(user))} ({getattr(user,'id', 'N/A')})", inline=True)
        emb.add_field(name="Type", value=kind, inline=True)
        if guild:
            emb.add_field(name="Guild", value=f"{guild.name} ({guild.id})", inline=True)
        else:
            emb.add_field(name="Guild", value="DM/Unknown", inline=True)

        ch_text = ""
        try:
            if channel is None:
                ch_text = "None"
            else:
                ch_text = f"{getattr(channel,'mention', getattr(channel,'name', str(channel)))} ({getattr(channel,'id', 'N/A')})"
        except Exception:
            ch_text = str(channel)
        emb.add_field(name="Channel", value=ch_text, inline=True)

        if content:
            txt = content if len(content) <= 1024 else (content[:1021] + "...")
            emb.add_field(name="Args/Content", value=txt, inline=False)

        affected_ids = affected_ids or []
        affected = ", ".join(f"<@{uid}>" for uid in affected_ids) if affected_ids else "None"
        emb.add_field(name="Affected", value=affected, inline=False)

        try:
            log_ch = bot.get_channel(LOG_CHANNEL_ID)
            if isinstance(log_ch, discord.TextChannel):
                await log_ch.send(embed=emb)
        except Exception as e:
            print(f"Failed to send command log embed: {e}")

        try:
            os.makedirs(LOGS_FOLDER, exist_ok=True)
            path = os.path.join(LOGS_FOLDER, f"commands_{date.today().isoformat()}.log")
            record = {
                "timestamp": ts.isoformat(),
                "type": kind,
                "command": command_name,
                "invoker_id": getattr(user, "id", None),
                "invoker_name": str(user),
                "guild_id": getattr(guild, "id", None),
                "guild_name": getattr(guild, "name", None),
                "channel_id": getattr(channel, "id", None),
                "channel_name": getattr(channel, "name", None),
                "content": content,
                "affected": affected_ids,
            }
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Failed to write command log locally: {e}")
    except Exception as e:
        print(f"Unexpected error in log_command_use: {e}")


@bot.event
async def on_command(ctx: commands.Context):
    """Log legacy prefix commands invoked via `!` prefix."""
    try:
        if ctx.author and getattr(ctx.author, "bot", False):
            return
        cmd_name = ctx.command.qualified_name if ctx.command else (ctx.message.content.split()[0] if ctx.message and ctx.message.content else "(unknown)")
        mentions = [m.id for m in ctx.message.mentions] if ctx.message else []
        await log_command_use(kind="prefix", user=ctx.author, guild=ctx.guild, channel=ctx.channel, command_name=cmd_name, content=(ctx.message.content if ctx.message else ""), affected_ids=mentions)
    except Exception as e:
        print(f"Failed to log prefix command: {e}")

@bot.event
async def on_interaction(interaction: discord.Interaction):

    try:
        if interaction.type == discord.InteractionType.application_command:
            try:

                user = interaction.user
                guild = interaction.guild
                channel = interaction.channel or (guild.get_channel(interaction.channel_id) if guild else None)
                cmd_name = None
                args_text = None
                mentions_list = []
                if interaction.data:
                    cmd_name = interaction.data.get("name")
        
                    try:
                        args_text = json.dumps(interaction.data.get("options", {}), ensure_ascii=False)
                    except Exception:
                        args_text = str(interaction.data.get("options", {}))
        
                    resolved = interaction.data.get("resolved", {}) or {}
                    users = resolved.get("users", {})
                    if isinstance(users, dict):
                        mentions_list = [int(uid) for uid in users.keys()]
                await log_command_use(
                    kind="slash",
                    user=user,
                    guild=guild,
                    channel=channel,
                    command_name=cmd_name or "(unknown)",
                    content=args_text or "",
                    affected_ids=mentions_list,
                )
            except Exception as e:
                print(f"Failed to log slash command interaction: {e}")
    except Exception:

        pass

    if not interaction.data or not interaction.data.get("custom_id"):
        return
    
    custom_id = interaction.data["custom_id"]
    

    if custom_id.startswith("sendembed:"):
        try:

            parts = custom_id.split(":", 2)
            if len(parts) != 3:
                await interaction.response.send_message("Invalid button configuration.", ephemeral=True)
                return
            
            target = parts[1]
            ephemeral_flag = parts[2]
            is_ephemeral = ephemeral_flag == "e"
            

            embed_data = None

            if target.startswith("send_json:"):
                import base64
                import json
                try:
                    b64_data = target.split(":", 1)[1]
                    json_text = base64.b64decode(b64_data).decode("utf-8")
                    embed_data = json.loads(json_text)
                except Exception as e:
                    await interaction.response.send_message(f"Failed to decode embed data: {e}", ephemeral=True)
                    return
            

            elif target:
                import os
                embed_dir = os.path.join(os.path.dirname(__file__), "embed-builder-web", "data")
                os.makedirs(embed_dir, exist_ok=True)
                embed_file = os.path.join(embed_dir, f"{target}.json")
                
                if os.path.exists(embed_file):
                    try:
                        with open(embed_file, "r", encoding="utf-8") as f:
                            saved_data = json.load(f)
                        embed_data = saved_data.get("embed", saved_data)
                    except Exception as e:
                        await interaction.response.send_message(f"Failed to load saved embed: {e}", ephemeral=True)
                        return
                else:
                    await interaction.response.send_message(f"Saved embed '{target}' not found.", ephemeral=True)
                    return
            
            if not embed_data:
                await interaction.response.send_message("No embed data found.", ephemeral=True)
                return
            

            embed = discord.Embed(
                title=embed_data.get("title"),
                description=embed_data.get("description"),
                color=discord.Color(embed_data.get("color", 0)) if embed_data.get("color") else None
            )
            

            for field in embed_data.get("fields", []):
                embed.add_field(
                    name=field.get("name", ""),
                    value=field.get("value", ""),
                    inline=field.get("inline", False)
                )
            

            if embed_data.get("footer"):
                footer = embed_data["footer"]
                embed.set_footer(
                    text=footer.get("text"),
                    icon_url=footer.get("icon_url")
                )
            
         
            if embed_data.get("thumbnail"):
                embed.set_thumbnail(url=embed_data["thumbnail"].get("url"))
            
       
            if embed_data.get("image"):
                embed.set_image(url=embed_data["image"].get("url"))
            
      
            if embed_data.get("author"):
                author = embed_data["author"]
                embed.set_author(
                    name=author.get("name"),
                    url=author.get("url"),
                    icon_url=author.get("icon_url")
                )
            
  
            await interaction.response.send_message(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.response.send_message(f"Error handling button: {e}", ephemeral=True)

@bot.event
async def on_ready():

    sys.stdout = old_stdout
    sys.stderr = old_stderr
    
    output = startup_output.getvalue()
    print(output)

    try:
        user = await bot.fetch_user(840949634071658507)  
        if user:
            for i in range(0, len(output), 1900):
                await user.send(f"Console output (part {i//1900+1}):\n```\n{output[i:i+1900]}\n```")
    except Exception as e:
        print(f"Failed to DM console output: {e}")
    
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Configured tuna admins: {TUNA_ADMIN_IDS}")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Courtesy, Service, and Protection"))

    
    if not getattr(bot, "_synced", False):
        try:

            print("⏳ Syncing global commands...")
            synced_global = await bot.tree.sync()
            print(f"✅ Synced {len(synced_global)} global commands")
            

            if APPLICATION_ID:
                guild_obj = discord.Object(id=int(os.getenv("GUILD_ID", "0")))
                if guild_obj.id != 0:
                    print(f"⏳ Syncing guild commands to guild {guild_obj.id} ...")
                    synced_guild = await bot.tree.sync(guild=guild_obj)
                    print(f"✅ Synced {len(synced_guild)} guild commands")
                else:
                    print("⚠️ GUILD_ID environment variable not set or invalid. Skipping guild sync.")
            else:
                print("⚠️ APPLICATION_ID missing, skipping guild sync.")
                
            bot._synced = True
        except Exception as e:
            print(f"❌ Failed to sync commands: {e}")
            traceback.print_exc()


async def load_cog_with_error_handling(cog_name):
    try:
        await bot.load_extension(cog_name)
        print(f"✅ Loaded {cog_name}")
    except Exception as e:
        print(f"❌ Failed to load {cog_name}: {e}")
        traceback.print_exc()


async def main():
    async with bot:
  


        cogs = []
        cog_directories = []


        env_cogs_path = os.path.join(os.path.dirname(__file__), ".env.cogs")
        if os.path.exists(env_cogs_path):
            try:
                with open(env_cogs_path, "r", encoding="utf-8") as f:
                    raw_lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]

                for ln in raw_lines:

                    if "=" in ln:
                        _, rhs = ln.split("=", 1)
                        ln = rhs.strip()

                    for part in ln.split(","):
                        part = part.strip()
                        if part:
                            cog_directories.append(part)

                if not cog_directories:
                    print("⚠️ Warning: .env.cogs exists but no valid entries were found; defaulting to 'cogs'")
                    cog_directories = ["cogs"]
            except Exception as e:
                print(f"⚠️ Warning: Failed to read .env.cogs: {e}; defaulting to 'cogs'")
                cog_directories = ["cogs"]
        else:
            print("⚠️ Warning: .env.cogs not found, defaulting to 'cogs' directory")
            cog_directories = ["cogs"]
            
        for directory in cog_directories:
            directory = directory.strip() 
            dir_path = os.path.join(os.path.dirname(__file__), directory)
            
            if not os.path.exists(dir_path):
                print(f"⚠️ Warning: Cog directory {directory} does not exist")
                continue
                

            if directory == "embed-builder-web":
                cogs.append("embed-builder-web.embed_new")
                continue
                
            for filename in os.listdir(dir_path):
                if filename.endswith(".py") and not filename.startswith("_"):
                    cogs.append(f"{directory}.{filename[:-3]}")
        

        cogs.sort()

        
        for cog in cogs:
            print(f"🔄 Loading cog {cog} ...")
            await load_cog_with_error_handling(cog)
        
        print("All cogs loaded. Starting bot...")
        await bot.start(TOKEN)

@bot.tree.command(name="sync", description="Sync slash commands (admin only).")
async def sync_commands(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You lack permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await interaction.client.tree.sync()
        await interaction.followup.send(f"✅ Synced {len(synced)} commands globally.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)


BOT_OWNER_ID = 840949634071658507

_tuna_admins_env = os.getenv("TUNA_ADMIN_IDS", "840949634071658507").strip()
if _tuna_admins_env:
    try:
        TUNA_ADMIN_IDS = [int(x.strip()) for x in _tuna_admins_env.split(",") if x.strip()]
    except Exception:
        print("⚠️ Warning: failed to parse TUNA_ADMIN_IDS env var; falling back to BOT_OWNER_ID only")
        TUNA_ADMIN_IDS = [BOT_OWNER_ID]
else:
    TUNA_ADMIN_IDS = [BOT_OWNER_ID]



async def _get_cog_directories() -> list:
    """Return list of cog directory names as used in startup (falls back to ['cogs'])."""
    env_cogs_path = os.path.join(os.path.dirname(__file__), ".env.cogs")
    cog_directories = []
    if os.path.exists(env_cogs_path):
        try:
            with open(env_cogs_path, "r", encoding="utf-8") as f:
                raw_lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
            for ln in raw_lines:
                if "=" in ln:
                    _, rhs = ln.split("=", 1)
                    ln = rhs.strip()
                for part in ln.split(","):
                    part = part.strip()
                    if part:
                        cog_directories.append(part)
        except Exception:
            cog_directories = ["cogs"]
    else:
        cog_directories = ["cogs"]
    return cog_directories


async def _gather_cog_list() -> list:

    cogs = []
    dirs = await _get_cog_directories()
    for directory in dirs:
        if directory == "embed-builder-web":
            cogs.append("embed-builder-web.embed_new")
            continue
        dir_path = os.path.join(os.path.dirname(__file__), directory)
        if not os.path.exists(dir_path):
            continue
        for filename in os.listdir(dir_path):
            if filename.endswith('.py') and not filename.startswith('_'):
                cogs.append(f"{directory}.{filename[:-3]}")
    cogs.sort()
    return cogs


async def _run_git_pull(repo_path: str) -> tuple:

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "pull", cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return proc.returncode, (out.decode(errors='replace') if out else ""), (err.decode(errors='replace') if err else "")
    except FileNotFoundError:
        return 127, "", "git not found"
    except Exception as e:
        return 1, "", str(e)


async def _reload_all_cogs() -> dict:
    """Attempt to reload or load all cogs; return dict with 'reloaded', 'loaded', 'failed'."""
    results = {"reloaded": [], "loaded": [], "failed": []}
    cogs = await _gather_cog_list()
    for cog in cogs:
        try:
            await bot.reload_extension(cog)
            results["reloaded"].append(cog)
        except commands.ExtensionNotLoaded:
            try:
                await bot.load_extension(cog)
                results["loaded"].append(cog)
            except Exception as e:
                results["failed"].append((cog, str(e)))
        except Exception as e:
            results["failed"].append((cog, str(e)))
    return results


@bot.group(name="tuna_admin", invoke_without_command=True)
async def tuna_admin(ctx: commands.Context):

    await ctx.send("Usage: `!tuna_admin deploy` or `!tuna_admin reboot`")


@tuna_admin.command(name="deploy")
async def tuna_deploy(ctx: commands.Context, *, _flags: str = ""):

    if ctx.author.id not in TUNA_ADMIN_IDS:
        await ctx.send("Only configured tuna admins can use this command.")
        return


    try:
        tokens = re.split(r"\s+", ctx.message.content.lower())
    except Exception:
        tokens = ctx.message.content.lower().split()

    restart_flags = {"--restart", "--reboot", "-r"}
    silent_flags = {"--silent", "-s", "silent", "quiet", "--quiet"}
    ping_flags = {"--ping", "-p", "ping"}
    do_restart = any(tok in restart_flags for tok in tokens)
    restart_silent = any(tok in silent_flags for tok in tokens)
    restart_ping = any(tok in ping_flags for tok in tokens)

    status_msg = await ctx.send("🔄 Running deploy (git pull + reload cogs)...")
    repo_path = os.path.dirname(__file__)
    code, out, err = await _run_git_pull(repo_path)

    out_text = out.strip()[:1500] if out else "(no stdout)"
    err_text = err.strip()[:1500] if err else "(no stderr)"


    reload_results = await _reload_all_cogs()


    msg = f"Git pull exit code: {code}\n\nStdout:\n{out_text}\n\nStderr:\n{err_text}\n\n"
    def _fmt_list(lst):
        return "\n".join(lst) if lst else "None"

    msg += "Reloaded:\n" + _fmt_list(reload_results.get("reloaded", [])) + "\n\n"
    msg += "Loaded:\n" + _fmt_list(reload_results.get("loaded", [])) + "\n\n"
    failed = reload_results.get("failed", [])
    if failed:
        msg += "Failed:\n" + "\n".join(f"{c}: {e}" for c, e in failed)
    else:
        msg += "Failed:\nNone"


    try:
        await status_msg.edit(content=f"```\n{msg[:1900]}\n```")
    except Exception:

        await ctx.send(f"```\n{msg[:1900]}\n```")


    if do_restart:

        os.environ["REBOOT_INITIATOR_ID"] = str(ctx.author.id)
        os.environ["REBOOT_INITIATOR_NAME"] = str(ctx.author)

        if restart_silent and not restart_ping:
            os.environ["REBOOT_SILENT"] = "1"

        if restart_ping:
            os.environ["REBOOT_PING"] = "1"

        try:
            await ctx.send("✅ Rebooting bot after deploy...")
        except Exception:
            pass

        await asyncio.sleep(0.5)

        try:
            await bot.close()
        except Exception as e:
            print(f"Error while closing bot for restart after deploy: {e}")

        try:
            print("Re-execing process to reboot bot after deploy.")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            print(f"Failed to execv for restart after deploy: {e}")


@tuna_admin.command(name="reboot")
async def tuna_reboot(ctx: commands.Context, *, _flags: str = ""):

    if ctx.author.id not in TUNA_ADMIN_IDS:
        await ctx.send("Only configured tuna admins can use this command.")
        return

    try:
        tokens = re.split(r"\s+", ctx.message.content.lower())
    except Exception:
        tokens = ctx.message.content.lower().split()

    silent_flags = {"--silent", "-s", "silent", "quiet", "--quiet"}
    ping_flags = {"--ping", "-p", "ping"}
    silent = any(tok in silent_flags for tok in tokens)
    force_ping = any(tok in ping_flags for tok in tokens)


    os.environ["REBOOT_INITIATOR_ID"] = str(ctx.author.id)
    os.environ["REBOOT_INITIATOR_NAME"] = str(ctx.author)
    

    try:
        await ctx.send("✅ Rebooting bot...")
    except Exception:
        pass


    await asyncio.sleep(0.5)


    if silent and not force_ping:
        os.environ["REBOOT_SILENT"] = "1"
    

    if force_ping:
        os.environ["REBOOT_PING"] = "1"


    try:
        await bot.close()
    except Exception as e:
        print(f"Error while closing bot for reboot: {e}")

    try:
        print("Re-execing process to reboot bot.")
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"Failed to execv for reboot: {e}")


@bot.command(name="tuna_troubleshoot")
async def tuna_troubleshoot(ctx: commands.Context, role_id: Optional[int] = None):

    if ctx.author.id != BOT_OWNER_ID:
        await ctx.send("Only the bot owner can use this command.")
        return

    import math
    data_path = os.path.join(os.path.dirname(__file__), "data", "role_timestamps.json")
    if not os.path.exists(data_path):
        await ctx.send("No role timestamp data found at data/role_timestamps.json.")
        return

    try:
        with open(data_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as e:
        await ctx.send(f"Failed to read timestamps file: {e}")
        return

    roles = raw_data.get("roles", {}) if isinstance(raw_data, dict) else {}
    if role_id is not None:
        roles = {str(role_id): roles.get(str(role_id), {})}


    guild = None
    gid_env = os.getenv("GUILD_ID")
    try:
        if gid_env:
            gid = int(gid_env)
            guild = ctx.bot.get_guild(gid) or await ctx.bot.fetch_guild(gid)
    except Exception:
        guild = None
    if guild is None:
        guild = ctx.guild or (ctx.bot.guilds[0] if ctx.bot.guilds else None)

    def human_td_seconds(seconds: int) -> str:
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        parts = []
        if d:
            parts.append(f"{d}d")
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s and not parts:
            parts.append(f"{s}s")
        return " ".join(parts) if parts else "0s"

    now_ts = int(datetime.now(timezone.utc).timestamp())
    lines = []
    total_cnt = 0
    for rid, users in roles.items():
        try:
            rid_int = int(rid)
        except Exception:
            rid_int = None
        role_name = None
        if guild and rid_int:
            role_obj = guild.get_role(rid_int)
            role_name = role_obj.name if role_obj else None
        lines.append(f"Role: {role_name or rid} (id: {rid})")
        if not users:
            lines.append("  (no records)")
            continue
        for uid, ts in users.items():
            total_cnt += 1
            try:
                uid_int = int(uid)
                ts_int = int(ts)
                elapsed = now_ts - ts_int
                lines.append(f"  <@{uid_int}> — set <t:{ts_int}:F> (<t:{ts_int}:R>) — {human_td_seconds(elapsed)}")
            except Exception:
                lines.append(f"  {uid} — {ts}")
        lines.append("")

    if not lines:
        await ctx.send("No role timestamp entries found.")
        return

    header = f"Role timestamps: {total_cnt} entries across {len(roles)} roles"
    out = "\n".join([header, ""] + lines)

    CHUNK = 1900
    for i in range(0, len(out), CHUNK):
        chunk = out[i:i+CHUNK]
        await ctx.send(f"```\n{chunk}\n```")

if __name__ == "__main__":
    asyncio.run(main())
