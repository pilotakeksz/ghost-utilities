import os
import discord
from discord.ext import commands

LOGS_DIR = os.path.join(os.path.dirname(__file__), "../logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOGS_DIR, "messages.txt")
LOG_CHANNEL_ID = 1525564400998551582

class MessageLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        log_entry = f"[{message.created_at}] ({message.guild.name if message.guild else 'DM'}) #{message.channel} | {message.author} ({message.author.id}): {message.content}\n"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)

        embed = discord.Embed(
            title="Message Logged",
            description=message.content or "[No Content]",
            color=discord.Color.blue(),
            timestamp=message.created_at
        )
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.add_field(name="Channel", value=f"{message.channel.mention}" if hasattr(message.channel, "mention") else "DM", inline=True)
        embed.add_field(name="User ID", value=str(message.author.id), inline=True)
        if message.attachments:
            embed.add_field(name="Attachments", value="\n".join(a.url for a in message.attachments), inline=False)

        channel = self.bot.get_channel(LOG_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(MessageLogger(bot))