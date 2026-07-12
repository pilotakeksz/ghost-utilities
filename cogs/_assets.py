"""Shared embed image assets.

The previous banner/logo images pointed at expiring Discord CDN signed URLs
(``media.discordapp.net/...?ex=...``) whose underlying attachments were deleted,
so every embed image was broken.  To make images reliable we generate local
asset files (if missing) and upload them once to a guild channel on startup to
obtain **permanent** ``cdn.discordapp.com`` URLs (these never expire).  The
resolved URLs are cached on disk so they survive restarts.
"""

from __future__ import annotations

import os
from typing import Optional

import discord

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
BANNER_PATH = os.path.join(ASSETS_DIR, "banner.png")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")
CACHE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "assets_cache.json"
)

ASSET_CHANNEL_ID = os.getenv("ASSET_CHANNEL_ID")
# Fallback channel name to create if no asset channel is configured.
ASSET_CHANNEL_NAME = "bot-assets"

# Runtime-resolved URLs (populated from cache at import, then uploaded if needed)
BANNER_URL: Optional[str] = None
LOGO_URL: Optional[str] = None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _load_cache() -> None:
    global BANNER_URL, LOGO_URL
    if not os.path.exists(CACHE_FILE):
        return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = __import__("json").load(f)
        BANNER_URL = data.get("banner") or None
        LOGO_URL = data.get("logo") or None
    except Exception:
        pass


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            __import__("json").dump(
                {"banner": BANNER_URL, "logo": LOGO_URL}, f, indent=2
            )
    except Exception as exc:  # pragma: no cover - non-fatal
        print(f"[assets] Failed to save cache: {exc}")


# ---------------------------------------------------------------------------
# Local image generation (Pillow)
# ---------------------------------------------------------------------------
def _load_font(size: int):
    from PIL import ImageFont

    candidates = [
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _generate_banner() -> None:
    from PIL import Image, ImageDraw

    W, H = 800, 200
    img = Image.new("RGB", (W, H), (11, 31, 58))  # dark navy
    draw = ImageDraw.Draw(img)

    # Left accent bar
    draw.rectangle([0, 0, 14, H], fill=(31, 78, 121))  # FHP blue
    # Thin red separator
    draw.rectangle([14, 0, 18, H], fill=(186, 101, 115))

    title_font = _load_font(26)
    big_font = _load_font(58)
    sub_font = _load_font(18)

    draw.text((40, 36), "FLORIDA HIGHWAY PATROL", font=title_font, fill=(173, 196, 230))
    draw.text((38, 70), "GHOST UNIT", font=big_font, fill=(255, 255, 255))
    draw.text((42, 150), "Courtesy • Service • Protection", font=sub_font, fill=(150, 170, 200))

    os.makedirs(ASSETS_DIR, exist_ok=True)
    img.save(BANNER_PATH, "PNG")
    print(f"[assets] Generated banner -> {BANNER_PATH}")


def _generate_logo() -> None:
    from PIL import Image, ImageDraw

    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle badge
    draw.ellipse([8, 8, S - 8, S - 8], fill=(31, 78, 121), outline=(255, 255, 255), width=6)
    draw.ellipse([22, 22, S - 22, S - 22], outline=(186, 101, 115), width=3)

    font = _load_font(96)
    text = "GU"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((S - tw) / 2 - bbox[0], (S - th) / 2 - bbox[1]), text, font=font, fill=(255, 255, 255))

    os.makedirs(ASSETS_DIR, exist_ok=True)
    img.save(LOGO_PATH, "PNG")
    print(f"[assets] Generated logo -> {LOGO_PATH}")


def _ensure_local_files() -> None:
    if not os.path.exists(BANNER_PATH):
        try:
            _generate_banner()
        except Exception as exc:
            print(f"[assets] Failed to generate banner: {exc}")
    if not os.path.exists(LOGO_PATH):
        try:
            _generate_logo()
        except Exception as exc:
            print(f"[assets] Failed to generate logo: {exc}")


# ---------------------------------------------------------------------------
# Upload to obtain permanent CDN URLs
# ---------------------------------------------------------------------------
async def _resolve_channel(bot: discord.Client) -> Optional[discord.TextChannel]:
    guild = None
    gid = os.getenv("GUILD_ID")
    if gid:
        try:
            guild = bot.get_guild(int(gid)) or await bot.fetch_guild(int(gid))
        except Exception:
            guild = None
    if guild is None:
        guild = bot.guilds[0] if bot.guilds else None
    if guild is None:
        return None

    # 1) Explicit configured channel
    if ASSET_CHANNEL_ID:
        try:
            ch = guild.get_channel(int(ASSET_CHANNEL_ID)) or await guild.fetch_channel(
                int(ASSET_CHANNEL_ID)
            )
            if isinstance(ch, discord.TextChannel):
                return ch
        except Exception:
            pass

    # 2) Existing bot-assets channel
    for ch in guild.text_channels:
        if ch.name == ASSET_CHANNEL_NAME:
            return ch

    # 3) Create one
    try:
        return await guild.create_text_channel(
            ASSET_CHANNEL_NAME,
            topic="Internal storage for bot embed images (do not delete).",
        )
    except Exception as exc:
        print(f"[assets] Could not create asset channel: {exc}")

    # 4) Fallback: any channel the bot can post to
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages:
            return ch
    return None


async def ensure_assets(bot: discord.Client) -> None:
    """Upload local asset images (if not already cached) and resolve CDN URLs."""
    global BANNER_URL, LOGO_URL

    _load_cache()
    _ensure_local_files()

    if BANNER_URL and LOGO_URL:
        return  # already resolved previously

    channel = await _resolve_channel(bot)
    if channel is None:
        print("[assets] No suitable channel to upload assets; images will be blank.")
        return

    try:
        if not BANNER_URL and os.path.exists(BANNER_PATH):
            msg = await channel.send(file=discord.File(BANNER_PATH))
            if msg.attachments:
                BANNER_URL = msg.attachments[0].url
                print(f"[assets] Banner URL resolved: {BANNER_URL}")
        if not LOGO_URL and os.path.exists(LOGO_PATH):
            msg = await channel.send(file=discord.File(LOGO_PATH))
            if msg.attachments:
                LOGO_URL = msg.attachments[0].url
                print(f"[assets] Logo URL resolved: {LOGO_URL}")
    except Exception as exc:
        print(f"[assets] Failed to upload assets: {exc}")
        return

    _save_cache()


# Resolve cached values at import time so embeds work even before on_ready.
_load_cache()