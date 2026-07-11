from __future__ import annotations

import asyncio
import json
from typing import Any

import discord
from discord import ui
from discord.components import _component_factory
from discord.ext import commands
from discord.ui.view import _component_to_item


ALLOWED_USER_ID = 840949634071658507
EMBED_WAIT_SECONDS = 5
ALLOWED_EXTENSIONS = (".txt", ".py", ".json")
NO_MENTIONS = discord.AllowedMentions.none()


def _layout_view_from_json(data: dict[str, Any]) -> ui.LayoutView:
    components = data.get("components")
    if not components:
        raise ValueError("JSON must include a `components` array.")

    view = ui.LayoutView(timeout=None)
    for comp_data in components:
        component = _component_factory(comp_data, None)
        if component is None:
            raise ValueError(f"Unsupported component type: {comp_data.get('type')}")
        view.add_item(_component_to_item(component))
    return view


def _layout_view_from_python(source: str) -> ui.LayoutView:
    namespace: dict[str, Any] = {"discord": discord, "ui": ui}
    exec(source, namespace)  # noqa: S102

    layout_view = namespace.get("view")
    if isinstance(layout_view, ui.LayoutView):
        return layout_view

    component = namespace.get("component")
    if component is None:
        raise ValueError("Python file must define `component` or `view`.")

    if isinstance(component, ui.LayoutView):
        return component

    view = ui.LayoutView(timeout=None)
    view.add_item(component)
    return view


def _parse_embed_file(text: str) -> ui.LayoutView:
    stripped = text.strip()
    if not stripped:
        raise ValueError("File is empty.")

    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON root must be an object.")
        return _layout_view_from_json(data)

    return _layout_view_from_python(stripped)


class EmbedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="embed")
    async def embed(self, ctx: commands.Context):
        """Upload a Components V2 embed file (.txt/.py/.json) within 5 seconds."""
        if ctx.author.id != ALLOWED_USER_ID:
            await ctx.reply("You don't have permission to use this command.", mention_author=False)
            return

        await ctx.reply(
            f"Upload your embed file (`.txt`, `.py`, or `.json`) within **{EMBED_WAIT_SECONDS}** seconds.",
            mention_author=False,
        )

        def check(message: discord.Message) -> bool:
            if message.author.id != ctx.author.id or message.channel.id != ctx.channel.id:
                return False
            if not message.attachments:
                return False
            return message.attachments[0].filename.lower().endswith(ALLOWED_EXTENSIONS)

        try:
            upload = await self.bot.wait_for("message", check=check, timeout=EMBED_WAIT_SECONDS)
        except asyncio.TimeoutError:
            await ctx.send("Timed out. No embed was sent.", allowed_mentions=NO_MENTIONS)
            return

        attachment = upload.attachments[0]
        try:
            raw = await attachment.read()
            text = raw.decode("utf-8")
            view = _parse_embed_file(text)
            await ctx.channel.send(view=view, allowed_mentions=NO_MENTIONS)
            await ctx.send("Embed sent.", allowed_mentions=NO_MENTIONS)
        except Exception as exc:
            await ctx.send(f"Failed to send embed: {exc}", allowed_mentions=NO_MENTIONS)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))
