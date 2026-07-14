from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import discord
from discord import ui
from discord.components import _component_factory
from discord.ext import commands
from discord.ui.view import _component_to_item


ALLOWED_USER_ID = 840949634071658507
EMBED_WAIT_SECONDS = 30  # increased to allow multi-upload
ALLOWED_EXTENSIONS = (".txt", ".py", ".json")
NO_MENTIONS = discord.AllowedMentions.none()
PERSISTENT_VIEWS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "persistent_views.json"
)


def _extract_flow_backup_ids(data: dict) -> list[tuple[str, str, str]]:
    """Extract (custom_id, backupId, label) for buttons with flow type 6 actions.
    Recursively searches through all nesting levels (containers, action rows, etc.)."""
    results: list[tuple[str, str, str]] = []

    def _recurse(components_list: list) -> None:
        for component in components_list:
            comp_type = component.get("type")
            # Action Row (type 1) — check its buttons
            if comp_type == 1:
                for btn in component.get("components", []):
                    if btn.get("type") == 2:  # Button
                        flow = btn.get("flow")
                        if flow and isinstance(flow, dict):
                            actions = flow.get("actions", [])
                            for action in actions:
                                if action.get("type") == 6:  # Send Message flow action
                                    backup_id = str(action.get("backupId", ""))
                                    if backup_id:
                                        results.append((
                                            btn.get("custom_id", ""),
                                            backup_id,
                                            btn.get("label", "Unnamed Button"),
                                        ))
                                    break
            # Container types (e.g. type 17) — recurse into their components
            inner = component.get("components")
            if inner and isinstance(inner, list):
                _recurse(inner)

    _recurse(data.get("components", []))
    return results


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


def _store_view_record(
    source_text: str,
    channel_id: int,
    message_id: int,
    button_responses: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Persist a view record so it can be re-registered on bot restart."""
    views_dir = os.path.dirname(PERSISTENT_VIEWS_FILE)
    os.makedirs(views_dir, exist_ok=True)

    records: list[dict[str, Any]] = []
    if os.path.exists(PERSISTENT_VIEWS_FILE):
        try:
            with open(PERSISTENT_VIEWS_FILE, "r", encoding="utf-8") as f:
                records = json.load(f)
        except (json.JSONDecodeError, Exception):
            records = []

    record: dict[str, Any] = {
        "source": source_text,
        "channel_id": channel_id,
        "message_id": message_id,
    }
    if button_responses:
        record["button_responses"] = button_responses

    records.append(record)

    with open(PERSISTENT_VIEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _load_view_records() -> list[dict[str, Any]]:
    """Load all stored persistent view records."""
    if not os.path.exists(PERSISTENT_VIEWS_FILE):
        return []
    try:
        with open(PERSISTENT_VIEWS_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
        if not isinstance(records, list):
            return []
        return records
    except (json.JSONDecodeError, Exception):
        return []


def _build_flow_response_map() -> dict[str, dict[str, Any]]:
    """Build a mapping of custom_id -> response data from all stored records."""
    result: dict[str, dict[str, Any]] = {}
    records = _load_view_records()
    for record in records:
        responses = record.get("button_responses") or {}
        result.update(responses)
    return result


class EmbedCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        """Re-register all persistent views after cog load / bot restart."""
        records = _load_view_records()
        if not records:
            print("[EmbedCog] No persistent views to re-register.")
            return

        registered = 0
        failed = 0
        for record in records:
            source = record.get("source", "")
            if not source:
                failed += 1
                continue
            try:
                view = _parse_embed_file(source)

                message_id = record.get("message_id")
                if message_id:
                    self.bot.add_view(view, message_id=message_id)
                else:
                    self.bot.add_view(view)
                registered += 1
            except Exception as exc:
                failed += 1
                print(f"[EmbedCog] Failed to re-register persistent view (msg {record.get('message_id')}): {exc}")

        print(f"[EmbedCog] Re-registered {registered} persistent views ({failed} failed).")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        """Listen for button interactions and handle flow button clicks."""
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id") if interaction.data else None
        if not custom_id:
            return

        # Check if this custom_id has a stored flow response
        flow_responses = _build_flow_response_map()
        response = flow_responses.get(custom_id)
        if not response:
            return  # Not a flow button we manage

        # Defer and respond with the stored response embed ephemerally
        try:
            source = response.get("source", "")
            if not source:
                await interaction.response.send_message(
                    "❌ Response source is empty.", ephemeral=True
                )
                return

            response_view = _parse_embed_file(source)
            await interaction.response.send_message(
                view=response_view, ephemeral=True, allowed_mentions=NO_MENTIONS
            )
        except Exception as exc:
            try:
                await interaction.response.send_message(
                    f"❌ Failed to load response: {exc}", ephemeral=True
                )
            except Exception:
                pass

    @commands.command(name="embed")
    async def embed(self, ctx: commands.Context):
        """Upload a Components V2 embed file (.txt/.py/.json) within 30 seconds.
        If the embed contains buttons with flows, you'll be prompted to upload
        response embeds for each button. Button responses are sent ephemerally."""
        if ctx.author.id != ALLOWED_USER_ID:
            await ctx.reply("You don't have permission to use this command.", mention_author=False)
            return

        # Track all messages to delete after successful send
        cleanup_messages: list[discord.Message] = []

        prompt_msg = await ctx.reply(
            f"Upload your embed file (`.txt`, `.py`, or `.json`) within **{EMBED_WAIT_SECONDS}** seconds.",
            mention_author=False,
        )
        cleanup_messages.append(prompt_msg)

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

        cleanup_messages.append(upload)  # user's upload message

        attachment = upload.attachments[0]
        try:
            raw = await attachment.read()
            text = raw.decode("utf-8")
        except Exception as exc:
            await ctx.send(f"Failed to read file: {exc}", allowed_mentions=NO_MENTIONS)
            return

        # Check if this is JSON with flow buttons
        button_responses: dict[str, dict[str, Any]] = {}
        data: dict | None = None

        if text.strip().startswith("{"):
            try:
                data = json.loads(text.strip())
            except json.JSONDecodeError:
                data = None

            if data and isinstance(data, dict):
                flow_info = _extract_flow_backup_ids(data)
                if flow_info:
                    # Group by backupId — multiple buttons can share the same backup
                    backup_map: dict[str, list[tuple[str, str]]] = {}
                    for custom_id, backup_id, label in flow_info:
                        backup_map.setdefault(backup_id, []).append((custom_id, label))

                    status_msg = await ctx.send(
                        f"🔍 Detected **{len(flow_info)}** flow button(s) backed by "
                        f"**{len(backup_map)}** unique backup message(s).\n"
                        f"I'll ask you to upload the response embed for each backup ID.\n"
                        f"Button responses will be sent **ephemerally** (only the clicker can see them).",
                        allowed_mentions=NO_MENTIONS,
                    )
                    cleanup_messages.append(status_msg)

                    for backup_id, buttons in backup_map.items():
                        button_labels = ", ".join(f"**{lbl}**" for _, lbl in buttons)
                        prompt = await ctx.send(
                            f"📤 **Backup ID: `{backup_id}`** — Used by: {button_labels}\n"
                            f"Upload the response embed file (`.txt`, `.py`, `.json`) "
                            f"within **{EMBED_WAIT_SECONDS}** seconds.",
                            allowed_mentions=NO_MENTIONS,
                        )
                        cleanup_messages.append(prompt)

                        try:
                            resp_upload = await self.bot.wait_for(
                                "message", check=check, timeout=EMBED_WAIT_SECONDS
                            )
                        except asyncio.TimeoutError:
                            await ctx.send(
                                f"⏱️ Timed out waiting for backup `{backup_id}`. "
                                f"Skipping all buttons referencing this backup.",
                                allowed_mentions=NO_MENTIONS,
                            )
                            continue

                        cleanup_messages.append(resp_upload)  # user's response upload

                        resp_attachment = resp_upload.attachments[0]
                        try:
                            resp_raw = await resp_attachment.read()
                            resp_text = resp_raw.decode("utf-8")
                            # Validate it parses correctly
                            _parse_embed_file(resp_text)
                            # Store the response for EACH button that uses this backupId
                            response_entry = {
                                "source": resp_text,
                                "ephemeral": True,
                                "backup_id": backup_id,
                            }
                            for custom_id, _ in buttons:
                                button_responses[custom_id] = response_entry
                            ok_msg = await ctx.send(
                                f"✅ Stored response for backup `{backup_id}` "
                                f"(applied to {len(buttons)} button(s)).",
                                allowed_mentions=NO_MENTIONS,
                            )
                            cleanup_messages.append(ok_msg)
                        except Exception as exc:
                            fail_msg = await ctx.send(
                                f"❌ Invalid response embed for backup `{backup_id}`: {exc}\n"
                                f"Skipping.",
                                allowed_mentions=NO_MENTIONS,
                            )
                            cleanup_messages.append(fail_msg)

        # Send the main embed
        try:
            view = _parse_embed_file(text)
            sent_msg = await ctx.channel.send(view=view, allowed_mentions=NO_MENTIONS)

            # Register as a persistent view and persist to disk for restart recovery
            self.bot.add_view(view, message_id=sent_msg.id)
            _store_view_record(text, ctx.channel.id, sent_msg.id, button_responses or None)

            # Delete the original command message and all intermediate messages
            try:
                await ctx.message.delete()
            except Exception:
                pass
            for msg in cleanup_messages:
                try:
                    await msg.delete()
                except Exception:
                    pass

            # Send a single clean confirmation (will auto-delete after 5s)
            parts = ["✅ Embed sent."]
            if button_responses:
                parts.append(f" ({len(button_responses)} button response(s) registered)")
            confirm = await ctx.send("".join(parts), allowed_mentions=NO_MENTIONS)
            await asyncio.sleep(5)
            try:
                await confirm.delete()
            except Exception:
                pass

        except Exception as exc:
            await ctx.send(f"Failed to send embed: {exc}", allowed_mentions=NO_MENTIONS)


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedCog(bot))