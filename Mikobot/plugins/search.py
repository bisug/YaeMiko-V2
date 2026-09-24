# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

import html
import random

from httpx import HTTPError
from pyrogram import Client, filters
from pyrogram.types import InputMediaPhoto, Message
from telegram import LinkPreviewOptions

from Mikobot import app
from Mikobot.state import state

OPENVERSE_IMAGES_URL = "https://api.openverse.org/v1/images/"
DUCKDUCKGO_URL = "https://api.duckduckgo.com/"
HACKER_NEWS_URL = "https://hn.algolia.com/api/v1/search"
MAX_RESULTS = 7


def _query(message: Message) -> str:
    return " ".join(message.command[1:]).strip()


async def _get_json(url: str, params: dict):
    response = await state.get(url, params=params)
    response.raise_for_status()
    return response.json()


def _safe_text(value, limit: int = 300) -> str:
    return html.unescape(str(value or "")).replace("\n", " ").strip()[:limit]


async def _send_images(message: Message, query: str) -> None:
    status = await message.reply_text("🔎 Searching open image sources…")
    try:
        data = await _get_json(
            OPENVERSE_IMAGES_URL,
            {"q": query, "page_size": MAX_RESULTS, "mature": "false"},
        )
        results = data.get("results", []) if isinstance(data, dict) else []
        images = []
        credits = []
        for result in results:
            if not isinstance(result, dict):
                continue
            image_url = result.get("url")
            if not isinstance(image_url, str) or not image_url:
                continue
            images.append(InputMediaPhoto(media=image_url))
            creator = _safe_text(result.get("creator"), 80)
            license_name = _safe_text(result.get("license"), 30)
            source = _safe_text(result.get("source"), 60)
            license_url = _safe_text(result.get("license_url"), 200)
            credits.append(
                f"• {creator or 'Unknown creator'} — {license_name or 'license unavailable'}"
                f"{f' ({license_url})' if license_url else ''}{f' via {source}' if source else ''}"
            )
            if len(images) == MAX_RESULTS:
                break
        if not images:
            await status.edit_text("No openly licensed images found.")
            return
        await message.reply_media_group(media=images)
        await status.delete()
        await message.reply_text(
            "Images: Openverse\n" + "\n".join(credits),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except (HTTPError, ValueError, TypeError, KeyError, AttributeError):
        await status.edit_text("Image search failed. Please try again later.")





@app.on_message(filters.command(["googleimg", "bingimg"]))
async def image_search(client: Client, message: Message):
    query = _query(message)
    if not query:
        await message.reply_text("Provide a query to search!")
        return
    await _send_images(message, query)


@app.on_message(filters.command("news"))
async def news(_, message: Message):
    query = _query(message)
    if not query:
        await message.reply_text("Provide a keyword to search for.")
        return
    try:
        data = await _get_json(
            HACKER_NEWS_URL,
            {"query": query, "tags": "story", "hitsPerPage": MAX_RESULTS},
        )
        hits = data.get("hits", []) if isinstance(data, dict) else []
        if not hits:
            await message.reply_text("No news found.")
            return
        item = random.choice(hits)
        title = _safe_text(item.get("title"), 250)
        url = _safe_text(item.get("url") or item.get("story_url"), 500)
        author = _safe_text(item.get("author"), 80)
        await message.reply_text(
            f"📰 <b>{title}</b>\n\n"
            f"Author: {author or 'Unknown'}\n"
            f"Points: {item.get('points', 0)} | Comments: {item.get('num_comments', 0)}\n"
            f"URL: {url or 'https://news.ycombinator.com/item?id=' + str(item.get('objectID', ''))}\n\n"
            "News source: Hacker News Algolia API"
        )
    except (HTTPError, ValueError, TypeError, KeyError, AttributeError):
        await message.reply_text("News search failed. Please try again later.")


@app.on_message(filters.command(["bingsearch", "duckduckgo"]))
async def web_search(client: Client, message: Message):
    query = _query(message)
    if not query:
        await message.reply_text("Please provide a keyword to search.")
        return
    try:
        data = await _get_json(
            DUCKDUCKGO_URL,
            {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        )
        sections = []
        abstract = _safe_text(data.get("AbstractText"), 700)
        if abstract:
            sections.append(abstract)
        for topic in data.get("RelatedTopics", [])[:MAX_RESULTS]:
            if not isinstance(topic, dict):
                continue
            text = _safe_text(topic.get("Text"), 300)
            url = _safe_text(topic.get("FirstURL"), 500)
            if text and url:
                sections.append(f"{text}\n{url}")
            if len(sections) >= MAX_RESULTS:
                break
        if not sections:
            await message.reply_text("No instant answer found.")
            return
        await message.reply_text(
            "\n\n".join(sections) + "\n\nSearch source: DuckDuckGo Instant Answer API"
        )
    except (HTTPError, ValueError, TypeError, KeyError, AttributeError):
        await message.reply_text("Search failed. Please try again later.")

# <=================================================== HELP ====================================================>
__mod_name__ = "SEARCH"

__help__ = """
💭 𝗦𝗘𝗔𝗥𝗖𝗛

➠ *Available commands:*

» /googleimg <query> or /bingimg <query>: Search openly licensed images via Openverse.

» /news <query>: Search technology news via Hacker News.

» /bingsearch <query> or /duckduckgo <query>: Search quick answers via DuckDuckGo.
"""
# <================================================ END =======================================================>
