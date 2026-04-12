import asyncio
import discord
from discord.ext import commands
from discord import app_commands

HOST_ROLE_ID = 1400862319495479407
PING_ROLE_ID = 1400570836510838835

RIDEALONG_CHANNEL = 1400928626811342869
TRAINING_CHANNEL  = 1396050841567232082

BANNER_URL = (
    "https://media.discordapp.net/attachments/1403360987096027268/"
    "1403476370855559178/image.png?ex=69dcaa7a&is=69db58fa"
    "&hm=46e8ad31d4375e03ae1b758cec02fc9dd94f66e0a074e1a9eb5b83addd783366"
    "&=&format=webp&quality=lossless&width=1867&height=70"
)

TIMEOUT_SECONDS = 30 * 60  # 30 minutes

# message_id -> {"host": Member, "voters": list[Member], "locked": bool, "max_voters": int}
active_sessions: dict[int, dict] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def build_embed(title: str, host: discord.Member, voters: list[discord.Member]) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=(
            "**This is your chance to showcase your skills and accomplish your duty "
            "of becoming the newest Trooper of the Florida Highway Patrol Ghost Unit.**\n\n"
            "\U0001f537 Be in-game and ready."
        ),
        color=discord.Color.from_rgb(0, 80, 180),
    )
    embed.add_field(name="\U0001f4c5 Time",     value="Within the next 30 minutes", inline=True)
    embed.add_field(name="\U0001f4cd Location", value="FHP Briefing Room",           inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    embed.add_field(
        name="Instructions",
        value=(
            "- Please arrive at the briefing room at the scheduled time.\n"
            "- Have your GU uniform on.\n"
            "- Be on the FHP team, with your GU callsign."
        ),
        inline=False,
    )
    embed.add_field(
        name="React with \u2705 if you can attend.",
        value=f"**Host:** {host.mention}",
        inline=False,
    )
    if voters:
        embed.add_field(
            name="Attendees",
            value="\n".join(v.mention for v in voters),
            inline=False,
        )
    embed.set_image(url=BANNER_URL)
    return embed


async def expire_session(message: discord.Message, session: dict, label: str) -> None:
    """Called after 30 min if the session was never started."""
    await asyncio.sleep(TIMEOUT_SECONDS)

    if session.get("locked"):
        return  # Already started -nothing to do.

    session["locked"] = True

    # Disable all buttons on the original message
    try:
        view = discord.ui.View()
        # Rebuild disabled buttons so the message still shows them greyed out
        vote_btn = discord.ui.Button(
            label="Vote", style=discord.ButtonStyle.success, emoji="✅", disabled=True
        )
        start_btn = discord.ui.Button(
            label="Start", style=discord.ButtonStyle.secondary, emoji="🟡", disabled=True
        )
        view.add_item(vote_btn)
        view.add_item(start_btn)
        await message.edit(view=view)
    except discord.HTTPException:
        pass

    try:
        await message.channel.send(
            f"\u23f0 The **{label}** hosted by {session['host'].mention} was **cancelled** -"
            f"timed out after 30 minutes."
        )
    except discord.HTTPException:
        pass

    active_sessions.pop(message.id, None)


# ─────────────────────────────────────────────────────────────────────────────
# Ride Along view  (max 1 voter)
# ─────────────────────────────────────────────────────────────────────────────

class RideAlongView(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__(timeout=None)
        self.host = host

    @discord.ui.button(
        label="Vote",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="ridealong:vote",
    )
    async def vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = active_sessions.get(interaction.message.id)
        if session is None:
            await interaction.response.send_message("Session no longer active.", ephemeral=True)
            return
        if session["locked"]:
            await interaction.response.send_message("This ride along has already started or expired.", ephemeral=True)
            return
        if interaction.user.id == session["host"].id:
            await interaction.response.send_message("You can't vote for your own ride along.", ephemeral=True)
            return
        if any(v.id == interaction.user.id for v in session["voters"]):
            await interaction.response.send_message("You already voted.", ephemeral=True)
            return
        if len(session["voters"]) >= session["max_voters"]:
            await interaction.response.send_message("The rider slot is already taken.", ephemeral=True)
            return

        session["voters"].append(interaction.user)

        try:
            await session["host"].send(
                f"\U0001f6a8 **{interaction.user.display_name}** (`{interaction.user}`) "
                f"voted to join your ride along!"
            )
        except discord.Forbidden:
            pass

        embed = build_embed("\U0001f6a8 FHP | Ghost Unit Training \U0001f6a8", session["host"], session["voters"])
        await interaction.message.edit(embed=embed)
        await interaction.response.send_message("You've been added as the rider!", ephemeral=True)

    @discord.ui.button(
        label="Start",
        style=discord.ButtonStyle.secondary,
        emoji="🟡",
        custom_id="ridealong:start",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = active_sessions.get(interaction.message.id)
        if session is None:
            await interaction.response.send_message("Session no longer active.", ephemeral=True)
            return
        if interaction.user.id != session["host"].id:
            await interaction.response.send_message("Only the host can start the ride along.", ephemeral=True)
            return
        if session["locked"]:
            await interaction.response.send_message("Already started or expired.", ephemeral=True)
            return

        session["locked"] = True

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        voters = session["voters"]
        rider_text = voters[0].mention if voters else "No rider."
        await interaction.channel.send(
            f"\U0001f6a8 The ride along hosted by {session['host'].mention} has **started**! "
            f"Rider: {rider_text} -get in position."
        )
        await interaction.response.defer()
        active_sessions.pop(interaction.message.id, None)


# ─────────────────────────────────────────────────────────────────────────────
# Training view  (max 3 voters)
# ─────────────────────────────────────────────────────────────────────────────

class TrainingView(discord.ui.View):
    def __init__(self, host: discord.Member):
        super().__init__(timeout=None)
        self.host = host

    @discord.ui.button(
        label="Vote",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="training:vote",
    )
    async def vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = active_sessions.get(interaction.message.id)
        if session is None:
            await interaction.response.send_message("Session no longer active.", ephemeral=True)
            return
        if session["locked"]:
            await interaction.response.send_message("This training has already started or expired.", ephemeral=True)
            return
        if interaction.user.id == session["host"].id:
            await interaction.response.send_message("You can't vote for your own training.", ephemeral=True)
            return
        if any(v.id == interaction.user.id for v in session["voters"]):
            await interaction.response.send_message("You already voted.", ephemeral=True)
            return
        if len(session["voters"]) >= session["max_voters"]:
            await interaction.response.send_message("All attendee slots are filled (max 3).", ephemeral=True)
            return

        session["voters"].append(interaction.user)

        try:
            await session["host"].send(
                f"\U0001f3ab **{interaction.user.display_name}** (`{interaction.user}`) "
                f"voted to join your training! "
                f"({len(session['voters'])}/{session['max_voters']} slots filled)"
            )
        except discord.Forbidden:
            pass

        embed = build_embed("\U0001f3ab FHP | Ghost Unit Training \U0001f3ab", session["host"], session["voters"])
        await interaction.message.edit(embed=embed)
        await interaction.response.send_message(
            f"You're signed up for the training! ({len(session['voters'])}/{session['max_voters']} slots)",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Start",
        style=discord.ButtonStyle.secondary,
        emoji="🟡",
        custom_id="training:start",
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = active_sessions.get(interaction.message.id)
        if session is None:
            await interaction.response.send_message("Session no longer active.", ephemeral=True)
            return
        if interaction.user.id != session["host"].id:
            await interaction.response.send_message("Only the host can start the training.", ephemeral=True)
            return
        if session["locked"]:
            await interaction.response.send_message("Already started or expired.", ephemeral=True)
            return

        session["locked"] = True

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        voters = session["voters"]
        if voters:
            attendee_text = ", ".join(v.mention for v in voters)
        else:
            attendee_text = "No attendees."

        await interaction.channel.send(
            f"\U0001f3ab The training hosted by {session['host'].mention} has **started**! "
            f"Attendees: {attendee_text} -get in position."
        )
        await interaction.response.defer()
        active_sessions.pop(interaction.message.id, None)


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class RideAlong(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /ridealong ────────────────────────────────────────────────────────────

    @app_commands.command(name="ridealong", description="Host a FHP Ghost Unit ride along")
    @app_commands.checks.has_role(HOST_ROLE_ID)
    async def ridealong(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(RIDEALONG_CHANNEL)
        if channel is None:
            await interaction.response.send_message("Ride along channel not found.", ephemeral=True)
            return

        host = interaction.user
        embed = build_embed("\U0001f6a8 FHP | Ghost Unit Training \U0001f6a8", host, [])
        view  = RideAlongView(host=host)

        msg = await channel.send(content=f"<@&{PING_ROLE_ID}>", embed=embed, view=view)

        session = {"host": host, "voters": [], "locked": False, "max_voters": 1}
        active_sessions[msg.id] = session

        asyncio.create_task(expire_session(msg, session, "ride along"))

        await interaction.response.send_message(
            f"Ride along posted in {channel.mention}.", ephemeral=True
        )

    @ridealong.error
    async def ridealong_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message(
                "You don't have the required role to host a ride along.", ephemeral=True
            )
        else:
            raise error

    # ── /training ─────────────────────────────────────────────────────────────

    @app_commands.command(name="training", description="Host a FHP Ghost Unit training session")
    @app_commands.checks.has_role(HOST_ROLE_ID)
    async def training(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(TRAINING_CHANNEL)
        if channel is None:
            await interaction.response.send_message("Training channel not found.", ephemeral=True)
            return

        host = interaction.user
        embed = build_embed("\U0001f3ab FHP | Ghost Unit Training \U0001f3ab", host, [])
        view  = TrainingView(host=host)

        msg = await channel.send(content=f"<@&{PING_ROLE_ID}>", embed=embed, view=view)

        session = {"host": host, "voters": [], "locked": False, "max_voters": 3}
        active_sessions[msg.id] = session

        asyncio.create_task(expire_session(msg, session, "training"))

        await interaction.response.send_message(
            f"Training posted in {channel.mention}.", ephemeral=True
        )

    @training.error
    async def training_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingRole):
            await interaction.response.send_message(
                "You don't have the required role to host a training.", ephemeral=True
            )
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(RideAlong(bot))