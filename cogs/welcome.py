import discord
from discord.ext import commands
import os
import datetime
import json

FOOTER_TEXT = "FS:RP | Florida Highway Patrol Ghost Unit"  
FOOTER_ICON = "https://cdn.discordapp.com/emojis/1398999132357525586.webp?size=128"
EMBED_COLOR = 0x1487d9
MILESTONE_ROLE_ID = 1317963317272252428
MILESTONE_MEMBER_COUNT = 600
MILESTONE_COOLDOWN_HOURS = 150
MILESTONE_DATA_FILE = os.path.join("data", "milestone_data.json")

# Read env vars with safe fallbacks. If ROLE_ID_ON_JOIN isn't set, fall back to the
# commonly used role for new members (1329910383678328922).
DEFAULT_ROLE_ON_JOIN = 1407409515221225552
DEFAULT_WELCOME_CHANNEL = None

role_env = os.getenv("ROLE_ID_ON_JOIN")
try:
    ROLE_ID_ON_JOIN = int(role_env) if role_env else DEFAULT_ROLE_ON_JOIN
except Exception:
    ROLE_ID_ON_JOIN = DEFAULT_ROLE_ON_JOIN

chan_env = 1317963317272252428
try:
    WELCOME_CHANNEL_ID = int(chan_env) if chan_env else DEFAULT_WELCOME_CHANNEL
except Exception:
    WELCOME_CHANNEL_ID = DEFAULT_WELCOME_CHANNEL

# Users automatically blacklisted: the bot will DM and ban these user IDs on join
# Add user IDs (integers) to this list to have them auto-banned when they join.
BLACKLISTED_USER_IDS = [
    # Example: 1163179403954618469,
]
 
class WelcomeView(discord.ui.View):
    def __init__(self, member_count: int):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Regulations",
            url="https://discord.com/channels/1317959054177599559/1398962874294075392",
            style=discord.ButtonStyle.secondary,
            emoji="<:regulations:1482070596648173668>"
        ))
        button = discord.ui.Button(
            label=f"Members: {member_count}",
            style=discord.ButtonStyle.secondary,
            emoji="<:Member:1482070549076246683>",
            disabled=True
        )
        self.add_item(button)

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_milestone_time = {}  # Track when last milestone was sent per guild (guild_id -> timestamp)
        self.load_milestone_data()

    def load_milestone_data(self):
        """Load milestone data from JSON file."""
        if os.path.exists(MILESTONE_DATA_FILE):
            try:
                with open(MILESTONE_DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Convert string keys to int keys and ISO strings to datetime objects
                    self.last_milestone_time = {
                        int(guild_id): datetime.datetime.fromisoformat(timestamp_str)
                        for guild_id, timestamp_str in data.items()
                    }
            except Exception as e:
                print(f"Error loading milestone data: {e}")
                self.last_milestone_time = {}
        else:
            self.last_milestone_time = {}

    def save_milestone_data(self):
        """Save milestone data to JSON file."""
        try:
            os.makedirs("data", exist_ok=True)
            # Convert datetime objects to ISO strings for JSON
            data = {
                str(guild_id): timestamp.isoformat()
                for guild_id, timestamp in self.last_milestone_time.items()
            }
            with open(MILESTONE_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving milestone data: {e}")

    def can_send_milestone(self, guild_id: int) -> bool:
        """Check if enough time has passed since last milestone (48 hours)."""
        if guild_id not in self.last_milestone_time:
            return True  # Never sent before, can send
        
        last_time = self.last_milestone_time[guild_id]
        now = datetime.datetime.utcnow()
        time_diff = now - last_time
        
        # Check if 48 hours have passed
        return time_diff.total_seconds() >= (MILESTONE_COOLDOWN_HOURS * 3600)
    @commands.command(name="welcome")
    async def test_welcome(self, ctx):
        ALLOWED_ROLE_ID = 1318181592719687681  # Role ID that allows using this command (e.g., Admin role)
        if not any(r.id == ALLOWED_ROLE_ID for r in ctx.author.roles):
            await ctx.reply("You do not have permission to use this command.", mention_author=False)
            return

        member_count = ctx.guild.member_count
        welcome_text = f"Welcome {ctx.author.mention}!"

        embed = discord.Embed(
            color=EMBED_COLOR,
            description=f"Welcome to the FS:RP | **Florida Highway Patrol Ghost Unit!**\nYou are member number: **{member_count}**"
        )
        embed.add_field(
            name="<:check:1482070474962763899> Verify",
            value="`・` https://discord.com/channels/1317959054177599559/1395072429931495455",
            inline=True
        )
        embed.add_field(
            name="<:New:1414207385412567192> Chat",
            value="`・` https://discord.com/channels/1317959054177599559/1317963328198279179",
            inline=True
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1403360987096027268/1408449383925809262/image.png?ex=69b568b4&is=69b41734&hm=3ed12e4ff85a2cea9ed3ab7dad606ec20fde048785de6fc5ec17b1e425c006df&")
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)

        await ctx.send(content=welcome_text, embed=embed, view=WelcomeView(member_count))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # Auto-ban blacklisted users: DM then ban on join

        member_count = member.guild.member_count
        welcome_text = f"Welcome {member.mention}!"

        embed = discord.Embed(
            color=EMBED_COLOR,
            description=f"Welcome to the FS:RP | **Florida Highway Patrol Ghost Unit!**\nYou are member number: **{member_count}**"
        )
        embed.add_field(
            name="<:check:1482070474962763899> Verify",
            value="`・` https://discord.com/channels/1317959054177599559/1395072429931495455",
            inline=True
        )
        embed.add_field(
            name="<:New:1414207385412567192> Chat",
            value="`・` [Chat here](https://discord.com/channels/1317959054177599559/1317963328198279179)",
            inline=True
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/1403360987096027268/1408449383925809262/image.png?ex=69b568b4&is=69b41734&hm=3ed12e4ff85a2cea9ed3ab7dad606ec20fde048785de6fc5ec17b1e425c006df&")
        embed.set_footer(text=FOOTER_TEXT, icon_url=FOOTER_ICON)
        

        channel = member.guild.get_channel(WELCOME_CHANNEL_ID) or member.guild.system_channel

        if channel:
            try:
                await channel.send(content=welcome_text, embed=embed, view=WelcomeView(member_count))
            except Exception as e:
                print(f"Failed to send welcome message: {e}")
        else:
            print("Welcome channel not found.")

async def setup(bot):
    await bot.add_cog(Welcome(bot))
