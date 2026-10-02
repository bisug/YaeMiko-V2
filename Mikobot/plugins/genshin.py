# <============================================== IMPORTS =========================================================>
import html
import logging
from dataclasses import dataclass

import httpx
from aiogram import F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputRichBlockBlockQuotation,
    InputRichBlockDivider,
    InputRichBlockList,
    InputRichBlockListItem,
    InputRichBlockParagraph,
    InputRichBlockPullQuotation,
    InputRichBlockSectionHeading,
    InputRichMessage,
    Message,
    RichText,
    RichTextBold,
    RichTextCode,
    RichTextItalic,
    RichTextUnderline,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from Mikobot import bot, dp
from Mikobot.state import state

# <=======================================================================================================>

# <================================================= CONSTANTS =================================================>
API = "https://genshin.jmp.blue"
REQUEST_TIMEOUT = 20
LOGGER = logging.getLogger(__name__)

# Upstream coverage is uneven: en carries the full character roster and fr about
# half of it, while pt and ru hold a handful of records and de/tr/id/ja/zh 404
# outright. Only the two that actually answer are offered.
LANGS = {"en": "English", "fr": "Français"}

PAGE_SIZE = 6

VISION_EMOJI = {
    "ANEMO": "🍃", "CRYO": "❄️", "DENDRO": "🌿", "ELECTRO": "⚡",
    "GEO": "🪨", "HYDRO": "💧", "PYRO": "🔥",
}

RARITY_EMOJI = {1: "⚪", 2: "🔵", 3: "🔷", 4: "🟣", 5: "🟡"}

# The five pieces an artifact set is drawn from, and the image slot each maps to.
ARTIFACT_PIECES = (
    ("flower-of-life", "Flower"),
    ("plume-of-death", "Plume"),
    ("sands-of-eon", "Sands"),
    ("goblet-of-eonothem", "Goblet"),
    ("circlet-of-logos", "Circlet"),
)


@dataclass(frozen=True)
class EntityType:
    """One of the API's collections.

    `grouped` marks the collections that arrive as a list of categories rather
    than a flat list of records, which changes both the search and the path used
    to reach a single item.
    """

    name: str
    label: str
    command: str
    emoji: str
    # Handler attribute name, singular so it reads like the other plugins.
    handler: str = ""
    grouped: bool = False
    # Image strategy. Characters and weapons expose a fixed name under
    # /{type}/{id}/{image}; artifact sets name their pieces directly; the
    # grouped collections and enemies/domains ship no art at all.
    image: str = ""


# The API serves ten collections. `boss` is excluded because it returns an empty
# list upstream, and advertising a type that always says "not found" is worse
# than leaving it out.
ENTITY_TYPES = {
    t.name: t
    for t in (
        EntityType("characters", "Character", "gchar", "🧝", handler="character", image="portrait"),
        EntityType("weapons", "Weapon", "gweapon", "⚔️", handler="weapon", image="icon"),
        EntityType("artifacts", "Artifact Set", "gartifact", "💍", handler="artifact", image="pieces"),
        EntityType("consumables", "Consumable", "gconsumable", "🍲", handler="consumable", grouped=True),
        EntityType("materials", "Material", "gmaterial", "🪵", handler="material", grouped=True),
        EntityType("enemies", "Enemy", "genemy", "👹", handler="enemy"),
        EntityType("domains", "Domain", "gdomain", "🏛️", handler="domain"),
        EntityType("nations", "Nation", "gnation", "🗺️", handler="nation", image="icon"),
        EntityType("elements", "Element", "gelement", "⚗️", handler="element", image="icon"),
    )
}

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


async def _fetch_flat(kind: str, lang: str) -> list:
    """Records for the seven collections that are a plain list of objects."""
    data = await _fetch(f"{kind}/all", lang)
    if not isinstance(data, list):
        raise ValueError(f"{kind}/all did not return a list")
    return [e for e in data if isinstance(e, dict) and e.get("id")]


async def _fetch_grouped(kind: str, lang: str) -> dict:
    """Flatten the two collections that arrive as a list of categories.

    Each element is a category whose own `id` names it, with every item stored
    as a sibling key. Reading it as a map of category to items returns nothing,
    because it is a list.
    """
    data = await _fetch(f"{kind}/all", lang)
    if not isinstance(data, list):
        raise ValueError(f"{kind}/all did not return a list")
    groups = {}
    for category in data:
        if not isinstance(category, dict):
            continue
        label = str(category.get("id", "")).casefold()
        if not label:
            continue
        items = {
            key: value
            for key, value in category.items()
            if key != "id" and isinstance(value, dict)
        }
        if items:
            groups[label] = items
    return groups


async def _search(kind: str, lang: str) -> list:
    """Every searchable record for a collection, whichever shape it has."""
    entity = ENTITY_TYPES[kind]
    if not entity.grouped:
        return await _fetch_flat(kind, lang)

    flat = []
    for category, items in (await _fetch_grouped(kind, lang)).items():
        for item_id, record in items.items():
            record = dict(record)
            record.setdefault("id", item_id)
            record["category"] = category
            flat.append(record)
    return flat


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


# Rich text runs are a list, not a string, and do not concatenate with +. The
# short helpers below build the shapes used throughout the renderers.
def _t(value) -> RichText:
    return RichText(text=_lines(value, 900))


def _bold(value) -> list:
    return [RichTextBold(text=_t(value))]


def _italic(value) -> list:
    return [RichTextItalic(text=_t(value))]


def _code(value) -> list:
    return [RichTextCode(text=_t(value))]


def _field(label: str, value) -> list | None:
    """A label/value run, or nothing when the field is absent upstream.

    The trailing space matters: rich runs are joined with no separator, so
    without it the fallback text renders "Title: KreideprinzVision: Geo".
    """
    if value in (None, "", [], {}):
        return None
    return [
        RichTextUnderline(text=RichText(text=f"{label}: ")),
        _t(value),
        RichText(text="  "),
    ]


def _bullet(label: str, value) -> InputRichBlockListItem | None:
    if value in (None, "", [], {}):
        return None
    return InputRichBlockListItem(
        label=label,
        blocks=[InputRichBlockParagraph(text=[RichTextUnderline(
            text=RichText(text=f"{label} — ")), _t(value)])],
    )


def _image_url(kind: str, record_id: str, slot: str = "") -> str | None:
    """Where the art for a record lives, if the collection has any.

    Art is inconsistent upstream: characters expose a fixed name, artifact sets
    name their pieces directly, and several collections have none, so a miss
    here is normal rather than exceptional.
    """
    entity = ENTITY_TYPES.get(kind)
    if entity is None or not entity.image:
        return None
    if entity.image == "pieces":
        piece = slot or ARTIFACT_PIECES[0][0]
        return f"{API}/{kind}/{record_id}/{piece}"
    return f"{API}/{kind}/{record_id}/{entity.image}"


# <=======================================================================================================>

# <=============================================== RENDERING ===============================================>
# Every renderer returns a list of rich blocks. There is no shared HTML string any
# more: rich blocks align label/value pairs natively, and the escaping step is
# gone because rich text is a structured tree rather than a string that has to
# survive a parser.


def _heading(text: str, size: int = 2):
    return InputRichBlockSectionHeading(text=RichText(text=text), size=size)


def _para(runs):
    return InputRichBlockParagraph(text=runs)


def _divider():
    return InputRichBlockDivider()


def _quote(runs):
    return InputRichBlockPullQuotation(text=runs)


def _rarity_line(record: dict) -> list | None:
    value = record.get("rarity", record.get("max_rarity"))
    if value in (None, "", []):
        return None
    return [RichText(text=f"{_rarity(value)} "), RichTextBold(text=_t(value))]


def _runlist(items) -> list:
    """Flatten the optional label/value groups a renderer collected."""
    return [run for group in items if group for run in group]


def _name_blocks(entry: dict, emoji: str) -> list:
    return [
        _heading(f"{emoji} {entry.get('name', '?')}", 2),
        _para(_rarity_line(entry) or _t(entry.get("name"))),
        _divider(),
    ]


def _field_para(fields) -> object | None:
    runs = _runlist(fields)
    return _para(runs) if runs else None


def _talent_list(records: list, heading: str) -> list:
    kept = [r for r in records if isinstance(r, dict) and r.get("name")]
    if not kept:
        return []
    items = [
        InputRichBlockListItem(
            label=str(r.get("unlock") or r.get("level") or "•"),
            blocks=[_para(_bold(r.get("name"))), _para(_italic(r.get("description")))],
        )
        for r in kept
    ]
    return [_heading(heading, 3), InputRichBlockList(items=items)]


def _render_character(entry: dict) -> list:
    emoji = VISION_EMOJI.get(str(entry.get("vision_key", "")).upper(), "")
    blocks = _name_blocks(entry, emoji)
    blocks.append(
        _field_para(
            [
                _field("Title", entry.get("title")),
                _field("Vision", entry.get("vision")),
                _field("Weapon", entry.get("weapon")),
                _field("Nation", entry.get("nation")),
                _field("Affiliation", entry.get("affiliation")),
                _field("Constellation", entry.get("constellation")),
                _field("Birthday", entry.get("birthday")),
                _field("Released", entry.get("release")),
            ]
        )
    )
    if entry.get("description"):
        blocks.append(_quote(_italic(entry["description"])))

    blocks += _talent_list(entry.get("skillTalents") or [], "Talents")

    consts = [c for c in (entry.get("constellations") or []) if isinstance(c, dict)]
    if consts:
        blocks.append(_heading("Constellations", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    InputRichBlockListItem(
                        label=f"C{c.get('level', '')}",
                        blocks=[_para(_bold(c.get("name"))), _para(_italic(c.get("description")))],
                    )
                    for c in consts
                    if c.get("name")
                ]
            )
        )

    blocks += _talent_list(entry.get("passiveTalents") or [], "Passives")

    materials = entry.get("ascension_materials")
    if isinstance(materials, dict):
        blocks.append(_heading("Ascension", 3))
        for tier, costs in materials.items():
            if not isinstance(costs, list):
                continue
            summary = ", ".join(
                f"{c.get('name')} x{c.get('value')}"
                for c in costs
                if isinstance(c, dict) and c.get("name")
            )
            if summary:
                blocks.append(
                    _para([RichTextUnderline(text=RichText(text=f"{tier}: ")), _t(summary)])
                )
    return [b for b in blocks if b is not None]


def _render_weapon(entry: dict) -> list:
    blocks = _name_blocks(entry, "⚔️")
    blocks.append(
        _field_para(
            [
                _field("Type", entry.get("type")),
                _field("Base ATK", entry.get("baseAttack")),
                _field("Substat", entry.get("subStat")),
                _field("Obtained", entry.get("location")),
            ]
        )
    )
    if entry.get("passiveName"):
        blocks.append(_heading("Passive", 3))
        blocks.append(_para(_bold(entry["passiveName"])))
        if entry.get("passiveDesc"):
            blocks.append(_para(_italic(entry["passiveDesc"])))
    return [b for b in blocks if b is not None]


def _render_artifact(entry: dict) -> list:
    blocks = _name_blocks(entry, "💍")
    items = [
        i
        for i in (
            _bullet("2-piece", entry.get("2-piece_bonus")),
            _bullet("4-piece", entry.get("4-piece_bonus")),
        )
        if i is not None
    ]
    if items:
        blocks.append(InputRichBlockList(items=items))
    return blocks


def _render_nation(entry: dict) -> list:
    blocks = _name_blocks(entry, "🗺️")
    blocks.append(
        _field_para(
            [
                _field("Element", entry.get("element")),
                _field("Archon", entry.get("archon")),
                _field("Ruling Body", entry.get("controllingEntity")),
            ]
        )
    )
    return [b for b in blocks if b is not None]


def _render_element(entry: dict) -> list:
    emoji = VISION_EMOJI.get(str(entry.get("key", "")).upper(), "⚗️")
    blocks = [
        _heading(f"{emoji} {entry.get('name', '?')}", 2),
        _para(_code(entry.get("key", ""))),
        _divider(),
    ]
    reactions = [r for r in (entry.get("reactions") or []) if isinstance(r, dict)]
    items = []
    for reaction in reactions:
        name = str(reaction.get("name", "?"))
        against = ", ".join(reaction.get("elements") or [])
        runs = _bold(name)
        if against:
            runs.append(_t(f" — against {against}"))
        if reaction.get("description"):
            runs.append(RichText(text=". "))
            runs.append(_italic(reaction["description"]))
        items.append(InputRichBlockListItem(label=name[:1] or "•", blocks=[_para(runs)]))
    if items:
        blocks.append(InputRichBlockList(items=items))
    return blocks


def _render_enemy(entry: dict) -> list:
    blocks = [_heading(f"👹 {entry.get('name', '?')}", 2), _divider()]
    blocks.append(
        _field_para(
            [
                _field("Type", entry.get("type")),
                _field("Family", entry.get("family")),
                _field("Faction", entry.get("faction")),
                _field("Region", entry.get("region")),
                _field("Elements", ", ".join(entry.get("elements") or []) or None),
            ]
        )
    )
    description = entry.get("description")
    if description and description != "N/A":
        blocks.append(_quote(_italic(description)))

    drops = [d for d in (entry.get("drops") or []) if isinstance(d, dict) and d.get("name")]
    if drops:
        blocks.append(_heading("Drops", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    InputRichBlockListItem(
                        label=_rarity(d.get("rarity")) or "•", blocks=[_para(_t(d.get("name")))]
                    )
                    for d in drops
                ]
            )
        )
    return [b for b in blocks if b is not None]


def _render_domain(entry: dict) -> list:
    blocks = [_heading(f"🏛️ {entry.get('name', '?')}", 2), _divider()]
    blocks.append(
        _field_para(
            [
                _field("Type", entry.get("type")),
                _field("Nation", entry.get("nation")),
                _field("Location", entry.get("location")),
                _field("Recommended", ", ".join(entry.get("recommendedElements") or []) or None),
            ]
        )
    )
    if entry.get("description"):
        blocks.append(_quote(_italic(entry["description"])))

    rewards = [r for r in (entry.get("rewards") or []) if isinstance(r, dict) and r.get("name")]
    if rewards:
        blocks.append(_heading("Rewards", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    InputRichBlockListItem(
                        label=str(r.get("level") or "•"), blocks=[_para(_t(r.get("name")))]
                    )
                    for r in rewards
                ]
            )
        )
    return [b for b in blocks if b is not None]


def _render_grouped(entry: dict, kind: str) -> list:
    """Consumables and materials share a shape once flattened."""
    emoji = ENTITY_TYPES[kind].emoji
    blocks = [_heading(f"{emoji} {entry.get('name', '?')}", 2)]
    category = str(entry.get("category", "")).replace("-", " ").title()
    if category:
        blocks.append(_para([RichTextItalic(text=_t(category))]))
    blocks.append(_divider())
    blocks.append(
        _field_para(
            [
                _field("Type", entry.get("type")),
                _field("Source", entry.get("source")),
            ]
        )
    )

    if entry.get("effect"):
        blocks.append(_para(_bold("Effect")))
        blocks.append(_para(_italic(entry["effect"])))
    if entry.get("description"):
        blocks.append(_quote(_italic(entry["description"])))

    crafting = entry.get("crafting") or entry.get("recipe")
    crafting = [c for c in crafting if isinstance(c, dict) and c.get("item")] if isinstance(crafting, list) else []
    if crafting:
        blocks.append(_heading("Crafting", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    InputRichBlockListItem(
                        label="•",
                        blocks=[_para([_t(f"{c['item']} "), _code(f"x{c.get('quantity')}")])],
                    )
                    for c in crafting
                ]
            )
        )

    users = entry.get("characters")
    if isinstance(users, list) and users:
        blocks.append(_heading("Used by", 3))
        blocks.append(_para(_italic(", ".join(users))))
    return [b for b in blocks if b is not None]


RENDERERS = {
    "characters": _render_character,
    "weapons": _render_weapon,
    "artifacts": _render_artifact,
    "nations": _render_nation,
    "elements": _render_element,
    "enemies": _render_enemy,
    "domains": _render_domain,
    "consumables": lambda e: _render_grouped(e, "consumables"),
    "materials": lambda e: _render_grouped(e, "materials"),
}


def _render_list(kind: str, items: list, query: str, page: int, lang: str) -> list:
    """A paged result list, as blocks.

    The vision and rarity markers the old string renderer used as leading emoji
    are carried by the list item label instead.
    """
    entity = ENTITY_TYPES[kind]
    shown, page, total = _paginate(items, page)
    blocks = [
        _heading(f"{entity.emoji} {query.title()} · {len(items)} match(es)", 3),
        _divider(),
        InputRichBlockList(
            items=[
                InputRichBlockListItem(
                    label=(
                        (VISION_EMOJI.get(str(e.get("vision_key", "")).upper(), "")
                         if kind == "characters" else "")
                        + _rarity(e.get("rarity", e.get("max_rarity")))
                    ) or "•",
                    blocks=[
                        _para([_bold(e.get("name", "?")), _code(f"  {e.get('id', '')}")])
                    ],
                )
                for e in shown
            ]
        ),
    ]
    footer = f"Page {page} of {total}"
    if lang != "en":
        footer += f" · {LANGS[lang]}"
    blocks.append(_para([RichTextItalic(text=RichText(text=footer))]))
    return blocks


def _list_keyboard(kind: str, query: str, page: int, lang: str) -> InlineKeyboardMarkup:
    """Page controls. Callback data is capped at 64 bytes by Telegram."""

    def data(step: int) -> str:
        return f"genshin|{kind}|{step}|{lang}|{query}"[:64]

    builder = InlineKeyboardBuilder()
    builder.button(text="◁", callback_data=data(page - 1))
    builder.button(text="✕", callback_data=f"genshin_close|{kind}"[:64])
    builder.button(text="▷", callback_data=data(page + 1))
    builder.adjust(3)
    return builder.as_markup()


# <=======================================================================================================>

# <================================================== SENDING ================================================>
async def _send_rich(chat_id: int, blocks: list, reply_markup=None, thread_id: int = None):
    """Send a rich message, falling back to plain text if the API rejects it.

    sendRichMessage is a comparatively new Bot API method. A bot pointed at an
    older server, or a client that cannot render blocks, answers with a
    TelegramAPIError; rather than leave the user with nothing, the blocks are
    flattened to readable text and sent normally.
    """
    rich = InputRichMessage(blocks=blocks)
    try:
        return await bot.send_rich_message(
            chat_id,
            rich,
            reply_markup=reply_markup,
            message_thread_id=thread_id,
        )
    except TelegramAPIError as err:
        LOGGER.debug("Rich message unavailable (%s), falling back to text", err)
        try:
            return await bot.send_message(
                chat_id, _blocks_to_text(blocks), reply_markup=reply_markup
            )
        except TelegramAPIError:
            LOGGER.debug("Could not deliver a genshin result", exc_info=True)
            return None


def _blocks_to_text(blocks: list) -> str:
    """Readable plain text from rich blocks, for the fallback path."""
    lines = []
    for block in blocks:
        kind = getattr(block, "type", None)
        if kind == "divider":
            lines.append("———")
            continue
        text = getattr(block, "text", None)
        if text is not None:
            lines.append(_flatten(text))
            continue
        items = getattr(block, "items", None)
        if items is not None:
            for item in items:
                label = getattr(item, "label", "")
                inner = " ".join(
                    _flatten(getattr(b, "text", "")) for b in getattr(item, "blocks", [])
                )
                lines.append(f"{label}. {inner}".strip())
            continue
    return "\n".join(x for x in lines if x)


def _is_run(value) -> bool:
    """A serialised run is `["text", value]`; anything else is not one."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and value[0] == "text"
    )


def _flatten(node) -> str:
    """Plain text out of any rich text shape.

    A run serialises two ways: as `RichText(text="Geo")` when it is the whole
    field, and as `["text", "Geo"]` once nested inside a styled run. Both have to
    be handled, since reading the first element as content prints the literal
    word "text" into every field of the fallback output.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if _is_run(node):
        return _flatten(node[1])
    if isinstance(node, (list, tuple)):
        return "".join(_flatten(part) for part in node)
    inner = getattr(node, "text", None)
    return _flatten(inner) if inner is not None else ""


# <================================================= COMMANDS ================================================>
async def _lookup(message: Message, command: CommandObject, kind: str):
    entity = ENTITY_TYPES[kind]
    lang = _lang_arg(command)
    query = _strip_lang(command)

    if not query:
        listing = "\n".join(
            f"{t.emoji} <code>/{t.command}</code> — {t.label.lower()}"
            for t in ENTITY_TYPES.values()
        )
        await message.reply_html(
            f"Give me a name. Example: <code>/{entity.command} {query or 'albedo'}</code>\n\n"
            f"{listing}\n\n"
            "Add <code>-fr</code> for French, e.g. <code>/gchar albedo-fr</code>."
        )
        return

    status = await message.reply_html(f"Looking up {html_escape(query)}…")
    try:
        entries = await _search(kind, lang)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        LOGGER.warning("Genshin %s lookup failed: %s", kind, err)
        await _replace(status, "The lookup service is not responding right now.")
        return

    if not entries:
        await _replace(
            status,
            f"No {entity.label.lower()} data in {LANGS[lang]} yet. Try <code>-en</code>.",
        )
        return

    matches = _match(entries, query)
    if not matches:
        await _replace(
            status,
            f"No {entity.label.lower()} called <b>{html_escape(query)}</b>.\n"
            "Check the spelling, or try part of the name.",
        )
        return

    thread_id = message.message_thread_id if message.chat.is_forum else None
    if len(matches) > 1:
        blocks = _render_list(kind, matches, query, 1, lang)
        markup = _list_keyboard(kind, query, 1, lang)
    else:
        record = matches[0]
        # A grouped record is already complete; a flat one needs its own fetch.
        if not entity.grouped and not record.get("skillTalents"):
            try:
                detail = await _fetch(f"{kind}/{record['id']}", lang)
                if isinstance(detail, dict):
                    record = detail
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        blocks = RENDERERS[kind](record)
        markup = None

    try:
        await status.delete()
    except TelegramAPIError:
        pass
    await _send_rich(message.chat.id, blocks, markup, thread_id)


def html_escape(text: str) -> str:
    """Escapes for the few plain-HTML notices still sent while loading."""
    return html.escape(str(text))


async def _replace(status: Message, text: str):
    """Swap the 'looking up' placeholder for a short plain-text notice."""
    try:
        await status.edit_text(text, parse_mode=None)
    except TelegramAPIError:
        try:
            await status.answer(text, parse_mode=None)
        except TelegramAPIError:
            LOGGER.debug("Could not deliver a genshin notice", exc_info=True)


# One thin handler per collection keeps the gate and the help text honest: a
# command exists only for a type the API actually serves.
def _make_handler(kind: str):
    """One thin handler per collection.

    This must be a plain `def`: an `async def` factory returns the coroutine
    object rather than the inner function, and aiogram then registers a
    coroutine where it expects a callable.
    """

    async def handler(message: Message, command: CommandObject):
        await _lookup(message, command, kind)

    handler.__name__ = f"genshin_{ENTITY_TYPES[kind].handler}"
    return handler


genshin_character = _make_handler("characters")
genshin_weapon = _make_handler("weapons")
genshin_artifact = _make_handler("artifacts")
genshin_consumable = _make_handler("consumables")
genshin_material = _make_handler("materials")
genshin_enemy = _make_handler("enemies")
genshin_domain = _make_handler("domains")
genshin_nation = _make_handler("nations")
genshin_element = _make_handler("elements")

async def genshin_page(query: CallbackQuery):
    """Advance a result list.

    There is no edit_rich_message in the Bot API, so a page turn cannot rewrite
    the card in place. The previous page is deleted and the next one sent; only
    the bot's own listing is ever removed, and the user's command is untouched.
    """
    parts = (query.data or "").split("|")
    if len(parts) != 5 or parts[1] not in ENTITY_TYPES:
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, kind, raw_page, lang, term = parts
    try:
        page = int(raw_page)
    except ValueError:
        await query.answer("This button is out of date.", show_alert=True)
        return

    try:
        matches = _match(await _search(kind, lang), term)
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as err:
        LOGGER.warning("Genshin page turn failed: %s", err)
        await query.answer("The lookup service is not responding.", show_alert=True)
        return

    if not matches:
        await query.answer("Nothing left to show.", show_alert=True)
        return

    shown, page, total = _paginate(matches, page)
    if total == 1:
        await query.answer("That is the only match.", show_alert=True)
        return

    try:
        await query.message.delete()
    except TelegramAPIError:
        LOGGER.debug("Could not clear the previous genshin page", exc_info=True)

    await _send_rich(
        query.message.chat.id,
        _render_list(kind, matches, term, page, lang),
        _list_keyboard(kind, term, page, lang),
        query.message.message_thread_id if query.message.chat.is_forum else None,
    )
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

» */gchar* `<name>` — vision, talents, constellations, passives, ascension
» */gweapon* `<name>` — type, base ATK, substat and passive
» */gartifact* `<name>` — set bonuses
» */gconsumable* `<name>` — food, potions and their effects
» */gmaterial* `<name>` — ascension materials and who uses them
» */genemy* `<name>` — family, faction and drops
» */gdomain* `<name>` — type, location and rewards
» */gnation* `<name>` — archon and ruling body
» */gelement* `<name>` — reactions and what triggers them

➠ Append *-fr* for French: `/gchar albedo-fr`.
➠ Several matches come back as a list you can page through.
➠ Data is the community API at *genshin.jmp.blue*. It serves static game data
  only, so it cannot look up a player account by UID.
"""

__mod_name__ = "Genshin"

# <================================================ HANDLER =================================================>
dp.message.register(genshin_character, Command("gchar", "gcharlist"))
dp.message.register(genshin_weapon, Command("gweapon"))
dp.message.register(genshin_artifact, Command("gartifact", "gset"))
dp.message.register(genshin_consumable, Command("gconsumable", "gfood"))
dp.message.register(genshin_material, Command("gmaterial"))
dp.message.register(genshin_enemy, Command("genemy"))
dp.message.register(genshin_domain, Command("gdomain"))
dp.message.register(genshin_nation, Command("gnation"))
dp.message.register(genshin_element, Command("gelement"))
dp.callback_query.register(genshin_page, F.data.startswith("genshin|"))
dp.callback_query.register(genshin_close, F.data.startswith("genshin_close|"))
# <================================================== END ====================================================>
