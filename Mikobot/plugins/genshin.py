# <============================================== IMPORTS =========================================================>
import html

import httpx
from aiogram import F
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from Mikobot import LOGGER, dp
from Mikobot.state import state

# <=======================================================================================================>

# <================================================= CONSTANTS =================================================>
API = "https://genshin.jmp.blue"
REQUEST_TIMEOUT = 20

# Only these return populated records. pt and ru exist upstream but carry a
# handful of entries each, and de/tr/id/ja/zh 404 outright, so offering them
# would send most users to a dead end.
LANGS = {"en": "English", "fr": "Français"}

# Entity types with a uniform record shape. Materials group by category and
# are served through their own command.
TYPES = ("characters", "weapons", "artifacts")

TYPE_LABEL = {"characters": "Character", "weapons": "Weapon", "artifacts": "Artifact"}

VISION_EMOJI = {
    "ANEMO": "🍃", "CRYO": "❄️", "DENDRO": "🌿", "ELECTRO": "⚡",
    "GEO": "🪨", "HYDRO": "💧", "PYRO": "🔥",
}

RARITY_EMOJI = {1: "⚪", 2: "🔵", 3: "🔷", 4: "🟣", 5: "🟡"}

PAGE_SIZE = 8
# Telegram truncates at 4096; leave room for the header and footer.
MAX_MESSAGE = 3600

# The API's material groups. Fixed rather than fetched, so this only needs
# touching when a new ascension tier is added upstream.
MATERIAL_CATEGORIES = (
    "boss-material", "common-material", "expeditions-material", "food-material",
    "forged-material", "gem-material", "jade-material", "region-material",
    "scroll-material", "speciality-material", "talent-book-material", "weapon-material",
)

# <=======================================================================================================>

# <================================================= HELPERS =================================================>
def _cut(text, limit: int) -> str:
    """Trim to a character budget."""
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _lines(text, limit: int = 220) -> str:
    """Flatten a multi-line description into one readable block."""
    return _cut(" ".join(str(text or "").split()), limit)


def _rarity(value) -> str:
    try:
        return RARITY_EMOJI.get(int(value), "")
    except (TypeError, ValueError):
        return ""


def _lang_arg(command: CommandObject) -> str:
    """Read an optional trailing `-fr` from the arguments."""
    args = (command.args or "").split()
    # The language is a suffix on the last token, so `/gchar albedo-fr` and
    # `/gchar hu tao fr` both resolve. Splitting on hyphens alone would break
    # the two-word names that already contain one.
    if args and "-" in args[-1]:
        head, _, tail = args[-1].rpartition("-")
        if tail.lower() in LANGS and head:
            return tail.lower()
    return "en"


def _strip_lang(command: CommandObject) -> str:
    """The query with any `-xx` language suffix removed."""
    args = (command.args or "").split()
    if args and "-" in args[-1]:
        head, _, tail = args[-1].rpartition("-")
        if tail.lower() in LANGS and head:
            args[-1] = head
    return " ".join(args)


async def _fetch(path: str, lang: str = "en"):
    """One GET against the API, returning decoded JSON.

    A 404 means the id or language is absent, which callers turn into a
    "no results" reply rather than an error.
    """
    response = await state.get(
        f"{API}/{path}", params={"lang": lang}, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()


async def _fetch_all(kind: str, lang: str = "en") -> list:
    data = await _fetch(f"{kind}/all", lang)
    if not isinstance(data, list):
        raise ValueError(f"{kind}/all did not return a list")
    return [e for e in data if isinstance(e, dict) and e.get("id")]


def _match(entries: list, query: str) -> list:
    """Rank entries by how well the name matches.

    The API has no search endpoint, so the whole list is filtered client side.
    Exact name wins over prefix, prefix over substring, so /gchar albedo is not
    shadowed by a longer name that merely contains the word.
    """
    query = query.casefold().strip()
    if not query:
        return entries

    def rank(entry) -> int:
        name = str(entry.get("name", "")).casefold()
        ident = str(entry.get("id", "")).casefold()
        if name == query or ident == query:
            return 0
        if name.startswith(query) or ident.startswith(query):
            return 1
        if any(word.startswith(query) for word in name.split()):
            return 2
        if query in name or query in ident:
            return 3
        # Ids are slugified, so `hutao` has to reach `hu-tao` some other way.
        squashed = _strip_spaces(query)
        if squashed and (
            _strip_spaces(name).startswith(squashed)
            or _strip_spaces(ident).startswith(squashed)
        ):
            return 4
        return 9

    hits = [e for e in entries if rank(e) < 9]
    return sorted(hits, key=lambda e: (rank(e), str(e.get("name", "")).casefold()))


def _strip_spaces(text: str) -> str:
    """Drop spaces so `hutao` still matches the id `hu-tao`."""
    return text.replace(" ", "").replace("-", "")


def _paginate(items: list, page: int):
    total = max(1, -(-len(items) // PAGE_SIZE))
    page = min(max(1, page), total)
    start = (page - 1) * PAGE_SIZE
    return items[start : start + PAGE_SIZE], page, total


async def _replace(status: Message, text: str, markup=None):
    """Swap the placeholder for the answer, in place.

    Editing keeps the result where the user's command already is, which is what
    a pagination button on that message expects to follow.
    """
    try:
        await status.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    except TelegramAPIError:
        # "message is not modified" and friends: fall back to a new message so
        # the user still gets an answer.
        try:
            await status.answer(
                text, parse_mode=ParseMode.HTML, reply_markup=markup
            )
        except TelegramAPIError:
            LOGGER.debug("Could not deliver a genshin lookup result", exc_info=True)


# <=======================================================================================================>
# <=============================================== RENDERING ===============================================>
def _render_character(entry: dict) -> str:
    emoji = VISION_EMOJI.get(str(entry.get("vision_key", "")).upper(), "")
    body = [f"{emoji} <b>{html.escape(str(entry.get('name', '?')))}</b>"]

    facts = (
        ("Title", entry.get("title")),
        ("Vision", entry.get("vision")),
        ("Weapon", entry.get("weapon")),
        ("Rarity", _rarity(entry.get("rarity")) or entry.get("rarity")),
        ("Nation", entry.get("nation")),
        ("Affiliation", entry.get("affiliation")),
        ("Constellation", entry.get("constellation")),
        ("Birthday", entry.get("birthday")),
        ("Released", entry.get("release")),
    )
    for label, value in facts:
        if value:
            body.append(f"<b>{label}:</b> {html.escape(str(value))}")

    if entry.get("description"):
        body.append(f"\n{_lines(entry['description'], 400)}")

    talents = [t for t in (entry.get("skillTalents") or []) if isinstance(t, dict)]
    if talents:
        body.append("\n<b>Talents</b>")
        for talent in talents[:3]:
            name = html.escape(str(talent.get("name", "?")))
            body.append(f"• <b>{name}</b> — {_lines(talent.get('description'), 110)}")

    return "\n".join(body)


def _render_weapon(entry: dict) -> str:
    body = [
        f"{_rarity(entry.get('rarity'))} <b>{html.escape(str(entry.get('name', '?')))}</b>",
        f"<b>Type:</b> {html.escape(str(entry.get('type', '?')))}",
        f"<b>Base ATK:</b> {html.escape(str(entry.get('baseAttack', '?')))}",
        f"<b>Substat:</b> {html.escape(str(entry.get('subStat', '?')))}",
    ]
    if entry.get("location"):
        body.append(f"<b>Obtained:</b> {html.escape(str(entry['location']))}")
    if entry.get("passiveName"):
        body.append(
            f"\n<b>{html.escape(str(entry['passiveName']))}</b>\n"
            f"{_lines(entry.get('passiveDesc'), 320)}"
        )
    return "\n".join(body)


def _render_artifact(entry: dict) -> str:
    body = [
        f"{_rarity(entry.get('max_rarity'))} "
        f"<b>{html.escape(str(entry.get('name', '?')))}</b>",
        f"<b>Max rarity:</b> {html.escape(str(entry.get('max_rarity', '?')))}★",
    ]
    for key, label in (("2-piece_bonus", "2-piece"), ("4-piece_bonus", "4-piece")):
        if entry.get(key):
            body.append(f"\n<b>{label}:</b> {_lines(entry[key], 200)}")
    return "\n".join(body)


RENDERERS = {
    "characters": _render_character,
    "weapons": _render_weapon,
    "artifacts": _render_artifact,
}


def _render_list(kind: str, items: list, query: str, page: int, lang: str) -> str:
    shown, page, total = _paginate(items, page)
    header = (
        f"<b>{html.escape(query.title())}</b> — {len(items)} "
        f"{TYPE_LABEL[kind].lower()} match(es)"
    )
    lines = []
    for entry in shown:
        star = _rarity(
            entry.get("max_rarity") if kind == "artifacts" else entry.get("rarity")
        )
        vision = (
            VISION_EMOJI.get(str(entry.get("vision_key", "")).upper(), "")
            if kind == "characters"
            else ""
        )
        lines.append(
            f"{vision}{star} {html.escape(str(entry.get('name', '?')))}"
            f" — <code>{html.escape(str(entry.get('id', '')))}</code>"
        )
    footer = f"\n\nPage {page}/{total}" if total > 1 else ""
    if lang != "en":
        footer += f" · {LANGS[lang]}"
    return f"{header}\n\n" + "\n".join(lines) + footer


def _list_keyboard(
    kind: str, query: str, page: int, lang: str
) -> InlineKeyboardMarkup:
    """Page controls. Callback data is capped at 64 bytes by Telegram."""

    def data(step: int) -> str:
        return f"genshin|{kind}|{step}|{lang}|{query}"[:64]

    builder = InlineKeyboardBuilder()
    builder.button(text="◁", callback_data=data(page - 1))
    builder.button(text="⋮", callback_data=f"genshin_close|{kind}"[:64])
    builder.button(text="▷", callback_data=data(page + 1))
    builder.adjust(3)
    return builder.as_markup()


# <================================================= COMMANDS ================================================
_CMD_NAMES = {"characters": "gchar", "weapons": "gweapon", "artifacts": "gartifact"}


async def _lookup(message: Message, command: CommandObject, kind: str):
    lang = _lang_arg(command)
    query = _strip_lang(command)

    if not query:
        await message.reply_html(
            f"Give me a name. Example: <code>/{_CMD_NAMES[kind]} albedo</code> · "
            "add <code>-fr</code> for French."
        )
        return

    status = await message.reply_html("Looking that up…")
    try:
        entries = await _fetch_all(kind, lang)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        LOGGER.warning("Genshin %s lookup failed: %s", kind, err)
        await _replace(status, "The lookup service is not responding right now.")
        return

    # A language with no coverage for this type comes back empty.
    if not entries:
        await _replace(
            status,
            f"No {TYPE_LABEL[kind].lower()} data in {LANGS[lang]} yet. "
            "Try <code>-en</code>.",
        )
        return

    matches = _match(entries, query)
    if not matches:
        await _replace(
            status,
            f"No {TYPE_LABEL[kind].lower()} called <b>{html.escape(query)}</b>.\n"
            "Check the spelling, or try part of the name.",
        )
        return

    if len(matches) > 1:
        await _replace(
            status,
            _render_list(kind, matches, query, 1, lang),
            _list_keyboard(kind, query, 1, lang),
        )
        return

    try:
        entry = await _fetch(f"{kind}/{matches[0]['id']}", lang)
        if not isinstance(entry, dict):
            raise ValueError("record was not an object")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        # The index listed it but the record is absent in this language.
        entry = matches[0]

    await _replace(status, _cut(RENDERERS[kind](entry), MAX_MESSAGE))


async def genshin_character(message: Message, command: CommandObject):
    await _lookup(message, command, "characters")


async def genshin_weapon(message: Message, command: CommandObject):
    await _lookup(message, command, "weapons")


async def genshin_artifact(message: Message, command: CommandObject):
    await _lookup(message, command, "artifacts")


async def genshin_material(message: Message, command: CommandObject):
    args = (command.args or "").split()
    lang = "en"
    if args and args[-1].lower() in LANGS:
        lang = args.pop().lower()
    query = " ".join(args)

    categories = ", ".join(f"<code>{c}</code>" for c in MATERIAL_CATEGORIES)
    if not query:
        await message.reply_html(
            f"Name a material or a category. Categories: {categories}"
        )
        return

    status = await message.reply_html("Looking that up…")
    try:
        data = await _fetch("materials/all", lang)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        LOGGER.warning("Genshin material lookup failed: %s", err)
        await _replace(status, "The lookup service is not responding right now.")
        return

    # Materials come back as a list of category objects, each keyed by its own
    # id and holding every item under it as sibling keys.
    if not isinstance(data, list):
        await _replace(status, "The lookup service returned something unexpected.")
        return

    wanted = query.casefold()
    groups = {}
    for category in data:
        if not isinstance(category, dict):
            continue
        label = str(category.get("id", "")).casefold()
        if not label:
            continue
        # Everything except the trailing id is one of this category's items.
        items = {k: v for k, v in category.items() if k != "id" and isinstance(v, dict)}
        if wanted in label or any(
            wanted in str(item.get("name", "")).casefold() for item in items.values()
        ):
            groups[label] = items

    if not groups:
        await _replace(
            status,
            f"No material called <b>{html.escape(query)}</b>.\n"
            f"Categories: {categories}",
        )
        return

    if len(groups) > 1:
        # A term spanning categories (a boss name, say) matches too much to
        # list inline, so name the categories and stop.
        listing = "\n".join(
            f"• {html.escape(cat.replace('-', ' ').title())} ({len(items)})"
            for cat, items in list(groups.items())[:PAGE_SIZE]
        )
        await _replace(status, f"<b>{html.escape(query.title())}</b>\n{listing}")
        return

    category, items = next(iter(groups.items()))
    lines = [f"<b>{html.escape(category.replace('-', ' ').title())}</b>"]
    for item in list(items.values())[:PAGE_SIZE]:
        if not isinstance(item, dict):
            continue
        line = f"• {html.escape(str(item.get('name', '?')))}"
        if item.get("source"):
            line += f" — <i>{html.escape(str(item['source']))}</i>"
        lines.append(line)
    await _replace(status, "\n".join(lines))


async def genshin_page(query: CallbackQuery):
    parts = (query.data or "").split("|")
    if len(parts) != 5 or parts[1] not in TYPES:
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, kind, raw_page, lang, term = parts
    try:
        page = int(raw_page)
    except ValueError:
        await query.answer("This button is out of date.", show_alert=True)
        return

    try:
        matches = _match(await _fetch_all(kind, lang), term)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        LOGGER.warning("Genshin page turn failed: %s", err)
        await query.answer("The lookup service is not responding.", show_alert=True)
        return

    if not matches:
        await query.answer("Nothing left to show.", show_alert=True)
        return

    try:
        await query.message.edit_text(
            _render_list(kind, matches, term, page, lang),
            parse_mode=ParseMode.HTML,
            reply_markup=_list_keyboard(kind, term, page, lang),
        )
    except TelegramAPIError as err:
        LOGGER.debug("Genshin pagination edit failed: %s", err)
        await query.answer("Nothing changed.", show_alert=True)
        return
    await query.answer()


async def genshin_close(query: CallbackQuery):
    try:
        await query.message.delete()
    except TelegramAPIError:
        # Already gone, or not ours to delete; clearing the buttons will do.
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            LOGGER.debug("Could not close a genshin listing", exc_info=True)
    await query.answer()


# <================================================= HELP ====================================================
__help__ = """
⛩ *Genshin Impact Lookup*

» */gchar* `<name>` — vision, talents, constellation and lore
» */gweapon* `<name>` — type, base ATK, substat and passive
» */gartifact* `<name>` — set bonuses
» */gmaterial* `<name>` — what it drops from and who uses it

➠ Append *-fr* for French: `/gchar albedo-fr`.
➠ Several matches come back as a paged list you can page through.
➠ Data is the community API at *genshin.jmp.blue*, which serves static game
  data only. It cannot look up a player account by UID.
"""

__mod_name__ = "Genshin"

# <================================================ HANDLER =================================================>
dp.message.register(genshin_character, Command("gchar", "gcharlist"))
dp.message.register(genshin_weapon, Command("gweapon"))
dp.message.register(genshin_artifact, Command("gartifact", "gset"))
dp.message.register(genshin_material, Command("gmaterial"))
dp.callback_query.register(genshin_page, F.data.startswith("genshin|"))
dp.callback_query.register(genshin_close, F.data.startswith("genshin_close|"))
# <================================================== END ====================================================