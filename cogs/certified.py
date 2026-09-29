from __future__ import annotations

from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands


ATTEMPT_LOG_CHANNEL_ID = 1554566076090683422
PASSING_SCORE = 4
QUESTION_COUNT = 5
PANEL_TITLE = ""
PANEL_DESCRIPTION = ""
PANEL_IMAGE_URL = "https://cdn.discordapp.com/attachments/1398427497724383356/1554603759747993622/Templateeee.png?backend=b2&ex=6abd7d13&is=6abc2b93&hm=736b215c460f0ce60abfb06347de2e03e64ecd0250049b74c486eaea7291cf01&"

# Fill in each course's explanation, role ID, question, three choices, and
# correct answer index (0=A, 1=B, 2=C). Keep exactly five questions per course.
CERTIFICATIONS: Dict[str, Dict[str, Any]] = {
    "certification_1": {
        "label": "Boat Certification",
        "role_id": 1554580639523545118,
        "explanation_title": "Boat Certification — Introduction",
        "explanation": (
            "While on maritime patrol, all Florida state boating laws apply. "
            "At all times, a proper lookout must be kept, and travel must be done at a safe speed. "
            "When two power-driven vessels are meeting head-on, both vessels should alter course to starboard "
            "(right) and pass port-to-port (left side to left side). When two power-driven vessels cross at an angle, "
            "the vessel that has the other vessel on its starboard (right) side must give way and avoid crossing "
            "ahead if circumstances allow; the other vessel generally maintains its course and speed. "
            "You must at all times follow the applicable right-of-way rules: "
            "the vessel required to give way must take early and clear action to keep clear, while the stand-on "
            "vessel generally maintains its course and speed but must act if necessary to avoid collision. "
            "Depending on the situation, power-driven vessels must also keep clear of vessels not under command, "
            "restricted in their ability to maneuver, engaged in fishing, sailing, or constrained by draft. "
            "If involved in a boating collision or other casualty, render reasonable assistance to anyone affected "
            "when you can do so without serious danger to your own vessel or people aboard, and provide "
            "information to the other operator."
        ),
        "explanation_image_url": "https://media.discordapp.net/attachments/1398427497724383356/1554602994404827166/31.Starboard.png?backend=b2&ex=6abd7c5c&is=6abc2adc&hm=b1b874a967ce347b91aa454a347fa2bc39f18b0cddb849eb36ab11eb8554683a&=&format=webp&quality=lossless",
        "questions": [
            {"prompt": "In this scenario, which vessel must give way?", "choices": ["Vessel A", "Vessel B", "Neither Vessel"], "correct_index": 0, "image_url": "https://cdn.discordapp.com/attachments/1398427497724383356/1554604537745113248/images.png?backend=b2&ex=6abd7dcc&is=6abc2c4c&hm=42a527ac65b6d9a7df836c672b44d764ebc83bcf98d6c9625524f9866aff15d1&"},
            {"prompt": "Which direction must both vessels alter course toward?", "choices": ["Starboard", "Port", "Up"], "correct_index": 0, "image_url": "https://cdn.discordapp.com/attachments/1398427497724383356/1554605695008243815/5d260904-d712-4ef0-a760-4216a900569b.png?backend=b2&ex=6abd7ee0&is=6abc2d60&hm=da82cc271dc9a01aff9d35ef47404e2cddbdaf0adc52255d9964e05f0b523029&"},
            {"prompt": "Which vessel would have right of way?", "choices": ["Vessel A", "Vessel B", "Neither Vessel"], "correct_index": 1, "image_url": "https://cdn.discordapp.com/attachments/1398427497724383356/1554606390775910571/e41d1490-f351-4547-b0f8-7a7ea778985a.png?backend=b2&ex=6abd7f86&is=6abc2e06&hm=1815f6bdfd60183976f3766d6e47ac6b3c66bc3d4245e05a93ad18f18f66b015&"},
            {"prompt": "Do you have the obligation to render aid to others in distress when safe to do so?", "choices": ["Yes", "No", "It depends"], "correct_index": 0, "image_url": ""},
            {"prompt": "Visibilty is poor, and traffic is heavy. Which of these is the safest option?", "choices": ["Increase speed", "Maintain speed", "Reduce speed"], "correct_index": None, "image_url": "https://cdn.discordapp.com/attachments/1398427497724383356/1554607564019204197/360_F_304677008_d6yFl6obkIVElw8Hy7giHdkb3v3WTzCx.png?backend=b2&ex=6abd809e&is=6abc2f1e&hm=6d4d2086e05ddc26d0bbaaeb7d53ff624a4a11bb877b93467c4d91ff66bdb203&"},
        ],
    },
    "certification_2": {
        "label": "Canine Certification",
        "role_id": 1549411815132368906,
        "explanation_title": "Canine Certification — Introduction",
        "explanation": (
            "Temporary course introduction: follow department policy and applicable law "
            "when deploying a canine. Use force only when legally justified, necessary, "
            "and proportionate; give clear warnings when feasible, maintain control of "
            "the canine, and stop the use of force when the subject is no longer a threat."
        ),
        "explanation_image_url": "",
        "questions": [
            {"prompt": "", "choices": ["", "", ""], "correct_index": None, "image_url": ""},
            {"prompt": "", "choices": ["", "", ""], "correct_index": None, "image_url": ""},
            {"prompt": "", "choices": ["", "", ""], "correct_index": None, "image_url": ""},
            {"prompt": "", "choices": ["", "", ""], "correct_index": None, "image_url": ""},
            {"prompt": "", "choices": ["", "", ""], "correct_index": None, "image_url": ""},
        ],
    },
}


def _display(value: str) -> str:
    """Use a zero-width placeholder for not-yet-configured embed text."""
    return value.strip() or "\u200b"


class CoursePickerView(discord.ui.View):
    def __init__(self, cog: "CertifiedCog"):
        super().__init__(timeout=None)
        self.cog = cog
        self.certification_one.label = CERTIFICATIONS["certification_1"]["label"][:80]
        self.certification_two.label = CERTIFICATIONS["certification_2"]["label"][:80]

    async def _start(self, interaction: discord.Interaction, course_key: str) -> None:
        view = CourseSessionView(self.cog, course_key, interaction.user.id)
        await interaction.response.send_message(
            embed=view.explanation_embed(), view=view, ephemeral=True
        )
        await self.cog.log_attempt(
            interaction,
            course_key,
            "STARTED",
            "The participant opened the course; completion is not yet recorded.",
        )

    @discord.ui.button(
        label="Boat Certification", style=discord.ButtonStyle.primary, custom_id="certified_select_1"
    )
    async def certification_one(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._start(interaction, "certification_1")

    @discord.ui.button(
        label="Canine Certification", style=discord.ButtonStyle.primary, custom_id="certified_select_2"
    )
    async def certification_two(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._start(interaction, "certification_2")


class CourseSessionView(discord.ui.View):
    def __init__(self, cog: "CertifiedCog", course_key: str, user_id: int):
        super().__init__(timeout=900)
        self.cog = cog
        self.course_key = course_key
        self.user_id = user_id
        self.question_index: Optional[int] = None
        self.answers: List[int] = []
        self.answer_buttons = [
            child for child in self.children
            if isinstance(child, discord.ui.Button)
            and child.custom_id
            and child.custom_id.startswith("certified_answer_")
        ]
        for button in self.answer_buttons:
            self.remove_item(button)
        self._set_page_controls()

    @property
    def course(self) -> Dict[str, Any]:
        return CERTIFICATIONS[self.course_key]

    def explanation_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=_display(self.course["explanation_title"]),
            description=(
                f"{_display(self.course['explanation'])}\n\n"
                f"This quiz has {QUESTION_COUNT} multiple-choice questions. "
                f"You need at least {PASSING_SCORE}/{QUESTION_COUNT} correct to pass. "
                "Press **Next** when you are ready."
            ),
        )
        image_url = self.course.get("explanation_image_url", "").strip()
        if image_url:
            embed.set_image(url=image_url)
        return embed

    def question_embed(self) -> discord.Embed:
        question = self.course["questions"][self.question_index]
        embed = discord.Embed(
            title=f"Question {self.question_index + 1}/{QUESTION_COUNT}",
            description=_display(question["prompt"]),
        )
        for index, choice in enumerate(question["choices"]):
            embed.add_field(
                name=chr(ord("A") + index), value=_display(choice), inline=False
            )
        image_url = question.get("image_url", "").strip()
        if image_url:
            embed.set_image(url=image_url)
        return embed

    async def _check_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This certification attempt belongs to someone else.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Next", style=discord.ButtonStyle.success, row=0, custom_id="certified_next"
    )
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not await self._check_owner(interaction):
            return
        self.question_index = 0
        for button in self.answer_buttons:
            self.add_item(button)
        self._set_page_controls()
        await interaction.response.edit_message(embed=self.question_embed(), view=self)

    def _set_page_controls(self) -> None:
        is_explanation = self.question_index is None
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "certified_next":
                    child.disabled = not is_explanation
                elif child.custom_id and child.custom_id.startswith("certified_answer_"):
                    child.disabled = is_explanation

    async def _choose(self, interaction: discord.Interaction, choice_index: int) -> None:
        if not await self._check_owner(interaction):
            return
        if self.question_index is None:
            await interaction.response.send_message(
                "Press Next to begin the questions.", ephemeral=True
            )
            return

        question = self.course["questions"][self.question_index]
        self.answers.append(choice_index)
        if self.question_index + 1 < QUESTION_COUNT:
            self.question_index += 1
            await interaction.response.edit_message(
                embed=self.question_embed(), view=self
            )
            return

        await interaction.response.defer()
        score = sum(
            answer == item.get("correct_index")
            for answer, item in zip(self.answers, self.course["questions"])
        )
        passed = score >= PASSING_SCORE
        role_note = ""
        if passed:
            role_note = await self.cog.assign_role(interaction, self.course)

        answer_summary = ", ".join(
            f"Q{index + 1}:{chr(ord('A') + answer)}"
            for index, answer in enumerate(self.answers)
        )
        outcome = "PASSED" if passed else "FAILED"
        await self.cog.log_attempt(
            interaction,
            self.course_key,
            outcome,
            f"Score: {score}/{QUESTION_COUNT}; answers: {answer_summary}; {role_note or 'role not applicable'}",
        )

        result = discord.Embed(
            title="Certification complete",
            description=(
                f"You scored **{score}/{QUESTION_COUNT}**. "
                + ("You passed. " if passed else "You did not pass; you may try again. ")
                + role_note
            ),
            color=discord.Color.green() if passed else discord.Color.orange(),
        )
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.edit_original_response(embed=result, view=self)
        self.stop()

    @discord.ui.button(label="A", style=discord.ButtonStyle.secondary, row=1, custom_id="certified_answer_a")
    async def answer_a(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._choose(interaction, 0)

    @discord.ui.button(label="B", style=discord.ButtonStyle.secondary, row=1, custom_id="certified_answer_b")
    async def answer_b(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._choose(interaction, 1)

    @discord.ui.button(label="C", style=discord.ButtonStyle.secondary, row=1, custom_id="certified_answer_c")
    async def answer_c(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._choose(interaction, 2)


class CertifiedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    get_group = app_commands.Group(name="get", description="Get department resources")

    @get_group.command(name="certified", description="Open the certification courses.")
    @app_commands.guild_only()
    async def get_certified(self, interaction: discord.Interaction) -> None:
        # This is a standard legacy embed, visually blank until its text is configured.
        panel = discord.Embed(
            title=PANEL_TITLE or None,
            description=_display(PANEL_DESCRIPTION),
        )
        if PANEL_IMAGE_URL.strip():
            panel.set_image(url=PANEL_IMAGE_URL.strip())
        await interaction.response.send_message(embed=panel, view=CoursePickerView(self))

    async def cog_load(self) -> None:
        self.bot.add_view(CoursePickerView(self))

    async def assign_role(
        self, interaction: discord.Interaction, course: Dict[str, Any]
    ) -> str:
        role_id = int(course.get("role_id") or 0)
        if role_id == 0:
            return "The passing role is not configured yet."
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return "Role assignment is only available in a server."
        role = interaction.guild.get_role(role_id)
        if role is None:
            return f"Configured role {role_id} was not found."
        try:
            await interaction.user.add_roles(role, reason="Completed certification course")
        except discord.Forbidden:
            return "The bot could not assign the configured role; check role hierarchy and permissions."
        return f"Role {role.mention} has been assigned."

    async def log_attempt(
        self,
        interaction: discord.Interaction,
        course_key: str,
        status: str,
        details: str,
    ) -> None:
        channel = self.bot.get_channel(ATTEMPT_LOG_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(ATTEMPT_LOG_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if not hasattr(channel, "send"):
            return
        embed = discord.Embed(
            title=f"Certification attempt — {status}",
            description=(
                f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                f"**Course:** {CERTIFICATIONS[course_key]['label']}\n"
                f"**Details:** {details}"
            ),
            color=discord.Color.green() if status == "PASSED" else discord.Color.orange(),
        )
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            print(f"Unable to log certification attempt to channel {ATTEMPT_LOG_CHANNEL_ID}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CertifiedCog(bot))