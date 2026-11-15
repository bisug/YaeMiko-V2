# <============================================== IMPORTS =========================================================>
import asyncio
import html
import logging
import time
from dataclasses import dataclass

import httpx
from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputRichBlockDivider,
    InputRichBlockList,
    InputRichBlockListItem,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockPullQuotation,
    InputRichBlockSectionHeading,
    InputRichMessage,
    Message,
    RichBlockCaption,
    RichTextBold,
    RichTextCode,
    RichTextItalic,
    RichTextUnderline,
)

from Mikobot import app
from Mikobot.events import on_callback, on_message
from Mikobot.state import state

# <=======================================================================================================>

# <================================================= CONSTANTS =================================================>
API = "https://genshin.jmp.blue"
REQUEST_TIMEOUT = 20
LOGGER = logging.getLogger(__name__)

PAGE_SIZE = 6
ROSTER_TTL = 900

_ROSTER_CACHE: dict[str, tuple[float, list]] = {}
_DETAIL_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_CHARACTER_NAME_CACHE: dict[str, object] = {}

LOOKUP_ERRORS = (httpx.HTTPError, ValueError, KeyError)


class _NotFound(ValueError):
    """The API answered 404: the record is not there."""


VISION_EMOJI = {
    "ANEMO": "🍃",
    "CRYO": "❄️",
    "DENDRO": "🌿",
    "ELECTRO": "⚡",
    "GEO": "🪨",
    "HYDRO": "💧",
    "PYRO": "🔥",
}

ARTIFACT_PIECES = (
    ("flower-of-life", "Flower"),
    ("plume-of-death", "Plume"),
    ("sands-of-eon", "Sands"),
    ("goblet-of-eonothem", "Goblet"),
    ("circlet-of-logos", "Circlet"),
)


@dataclass(frozen=True)
class EntityType:
    name: str
    label: str
    command: str
    emoji: str
    handler: str = ""
    grouped: bool = False
    image: str = ""


ENTITY_TYPES = {
    t.name: t
    for t in (
        EntityType(
            "characters",
            "Character",
            "gchar",
            "🧝",
            handler="character",
            image="portrait",
        ),
        EntityType("weapons", "Weapon", "gweapon", "⚔️", handler="weapon", image="icon"),
        EntityType(
            "artifacts",
            "Artifact Set",
            "gartifact",
            "💍",
            handler="artifact",
            image="pieces",
        ),
        EntityType(
            "consumables",
            "Consumable",
            "gconsumable",
            "🍲",
            handler="consumable",
            grouped=True,
        ),
        EntityType(
            "materials", "Material", "gmaterial", "🪵", handler="material", grouped=True
        ),
        EntityType("enemies", "Enemy", "genemy", "👹", handler="enemy", image="icon"),
        EntityType("domains", "Domain", "gdomain", "🏛️", handler="domain"),
        EntityType("nations", "Nation", "gnation", "🗺️", handler="nation", image="icon"),
        EntityType(
            "elements", "Element", "gelement", "⚗️", handler="element", image="icon"
        ),
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


def html_escape(text: str) -> str:
    """Escapes for plain-HTML notices."""
    return html.escape(str(text))


def _rarity_stars(value) -> str:
    try:
        count = int(value)
        return "⭐" * count if 1 <= count <= 5 else ""
    except TypeError, ValueError:
        return ""


async def _fetch(path: str):
    """One GET against the API, returning decoded JSON."""
    response = await state.get(f"{API}/{path}", timeout=REQUEST_TIMEOUT)
    if response.status_code == 404:
        raise _NotFound(path)
    response.raise_for_status()
    return response.json()


async def _fetch_flat(kind: str) -> list:
    """Records for collections that are a plain list of objects."""
    try:
        data = await _fetch(f"{kind}/all")
    except _NotFound:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{kind}/all did not return a list")
    return [e for e in data if isinstance(e, dict) and e.get("id")]


async def _fetch_grouped(kind: str) -> dict:
    """Flatten collections that arrive as a list of categories."""
    try:
        data = await _fetch(f"{kind}/all")
    except _NotFound:
        return {}
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


async def _search(kind: str) -> list:
    """Every searchable record for a collection, cached for ROSTER_TTL."""
    cached = _ROSTER_CACHE.get(kind)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    entity = ENTITY_TYPES[kind]
    if not entity.grouped:
        records = await _fetch_flat(kind)
    else:
        flat = []
        for category, items in (await _fetch_grouped(kind)).items():
            for item_id, record in items.items():
                record = dict(record)
                record.setdefault("id", item_id)
                record["category"] = category
                flat.append(record)
        records = flat

    _ROSTER_CACHE[kind] = (time.monotonic() + ROSTER_TTL, records)
    return records


_SEARCH_ALL_CACHE: tuple[float, list] | None = None


async def _search_all(query: str) -> list:
    """Search across all 9 collections."""
    tasks = [_search(k) for k in ENTITY_TYPES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_matches = []

    for kind, res in zip(ENTITY_TYPES.keys(), results, strict=True):
        if isinstance(res, list):
            matched = _match(res, query)
            for m in matched:
                item = dict(m)
                item["_kind"] = kind
                all_matches.append(item)

    query_folded = query.casefold().strip()

    def score(item):
        name = str(item.get("name", "")).casefold()
        ident = str(item.get("id", "")).casefold()
        if name == query_folded or ident == query_folded:
            return 0
        if name.startswith(query_folded) or ident.startswith(query_folded):
            return 1
        if any(word.startswith(query_folded) for word in name.split()):
            return 2
        if query_folded in name or query_folded in ident:
            return 3
        return 4

    all_matches.sort(key=score)
    return all_matches


async def _fetch_detail(kind: str, record_id: str) -> dict:
    """Fetch and cache detailed record."""
    key = (kind, record_id)
    cached = _DETAIL_CACHE.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    detail = await _fetch(f"{kind}/{record_id}")
    if isinstance(detail, dict):
        if isinstance(detail.get("characters"), list):
            try:
                names = await _character_names()
                detail = dict(detail)
                detail["characters"] = [
                    names.get(str(c), str(c)) for c in detail["characters"]
                ]
            except LOOKUP_ERRORS:
                LOGGER.debug("Could not resolve character names", exc_info=True)
        _DETAIL_CACHE[key] = (time.monotonic() + ROSTER_TTL, detail)
        return detail
    return {}


def _strip_spaces(text: str) -> str:
    """Drop spaces and hyphens for flexible slug matching."""
    return text.replace(" ", "").replace("-", "")


def _match(entries: list, query: str) -> list:
    """Rank entries by match quality."""
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
        squashed = _strip_spaces(query)
        if squashed and (
            _strip_spaces(name).startswith(squashed)
            or _strip_spaces(ident).startswith(squashed)
        ):
            return 4
        return 9

    scored = sorted(
        (
            (rank(entry), str(entry.get("name", "")).casefold(), entry)
            for entry in entries
        ),
        key=lambda item: (item[0], item[1]),
    )
    return [entry for score, _, entry in scored if score < 9]


def _paginate(items: list, page: int):
    total = max(1, -(-len(items) // PAGE_SIZE))
    page = min(max(1, page), total)
    start = (page - 1) * PAGE_SIZE
    return items[start : start + PAGE_SIZE], page, total


# Rich text formatting helpers
def _t(value) -> str:
    return _lines(value, 900)


def _bold(value) -> list:
    return [RichTextBold(text=_t(value))]


def _italic(value) -> list:
    return [RichTextItalic(text=_t(value))]


def _code(value) -> list:
    return [RichTextCode(text=_t(value))]


def _field(label: str, value) -> list | None:
    if value in (None, "", [], {}):
        return None
    return [
        RichTextUnderline(text=f"{label}: "),
        _t(value),
        "  ",
    ]


def _bullet(label: str, value) -> InputRichBlockListItem | None:
    if value in (None, "", [], {}):
        return None
    return InputRichBlockListItem(
        blocks=[
            InputRichBlockParagraph(
                text=[RichTextUnderline(text=f"{label} — "), _t(value)]
            )
        ],
    )


def _list_item(label: str, blocks: list) -> InputRichBlockListItem:
    if not label or not blocks:
        return InputRichBlockListItem(blocks=blocks)
    first, *rest = blocks
    runs = getattr(first, "text", None)
    if not isinstance(runs, list):
        return InputRichBlockListItem(blocks=blocks)
    return InputRichBlockListItem(
        blocks=[
            InputRichBlockParagraph(text=[RichTextUnderline(text=f"{label} "), *runs]),
            *rest,
        ]
    )


def _image_url(kind: str, record_id: str, slot: str = "") -> str | None:
    entity = ENTITY_TYPES.get(kind)
    if entity is None or not entity.image:
        return None
    if entity.image == "pieces":
        piece = slot or ARTIFACT_PIECES[0][0]
        return f"{API}/{kind}/{record_id}/{piece}"
    return f"{API}/{kind}/{record_id}/{entity.image}"


# <=======================================================================================================>


# <=============================================== RENDERING ===============================================>
def _heading(text: str, size: int = 2):
    return InputRichBlockSectionHeading(text=text, size=size)


def _para(runs):
    return InputRichBlockParagraph(text=runs)


def _divider():
    return InputRichBlockDivider()


def _quote(runs):
    return InputRichBlockPullQuotation(text=runs)


def _rarity_line(record: dict) -> list | None:
    value = record.get("rarity", record.get("max_rarity"))
    stars = _rarity_stars(value)
    if not stars:
        return None
    return [RichTextBold(text=stars)]


def _runlist(items) -> list:
    return [run for group in items if group for run in group]


def _photo_block(entry: dict, kind: str):
    record_id = str(entry.get("id", "") or "")
    if not record_id:
        return None
    url = _image_url(kind, record_id)
    if not url:
        return None
    return InputRichBlockPhoto(
        photo=InputMediaPhoto(media=url),
        caption=RichBlockCaption(text=str(entry.get("name", ""))),
    )


async def _character_names() -> dict:
    global _CHARACTER_NAME_CACHE
    if (
        _CHARACTER_NAME_CACHE
        and _CHARACTER_NAME_CACHE.get("expires", 0) > time.monotonic()
    ):
        return _CHARACTER_NAME_CACHE.get("data", {})
    names = {}
    for record in await _search("characters"):
        names[record["id"]] = record.get("name") or record["id"]
    _CHARACTER_NAME_CACHE = {"expires": time.monotonic() + ROSTER_TTL, "data": names}
    return names


def _name_blocks(entry: dict, emoji: str, kind: str = "") -> list:
    photo = _photo_block(entry, kind) if kind else None
    return [
        photo,
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
        _list_item(
            str(r.get("unlock") or r.get("level") or ""),
            [_para(_bold(r.get("name"))), _para(_italic(r.get("description")))],
        )
        for r in kept
    ]
    return [_heading(heading, 3), InputRichBlockList(items=items)]


def _character_keyboard(char_id: str, active_tab: str) -> InlineKeyboardMarkup:
    """Tab buttons for character cards."""

    def tab_btn(tab_key: str, label: str):
        display = f"• {label} •" if tab_key == active_tab else label
        return InlineKeyboardButton(
            text=display, callback_data=f"gchar_tab|{char_id}|{tab_key}"[:64]
        )

    return InlineKeyboardMarkup(
        [
            [tab_btn("bio", "📜 Profile"), tab_btn("talents", "⚔️ Talents")],
            [tab_btn("consts", "⭐ Consts"), tab_btn("ascend", "💎 Ascend")],
            [InlineKeyboardButton(text="✕ Close", callback_data="gclose|characters")],
        ]
    )


def _card_close(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="✕ Close", callback_data=f"gclose|{kind}")]]
    )


def _render_character(
    entry: dict, tab: str = "bio"
) -> tuple[list, InlineKeyboardMarkup]:
    char_id = str(entry.get("id", ""))
    emoji = VISION_EMOJI.get(str(entry.get("vision_key", "")).upper(), "")
    name = entry.get("name", "?")

    blocks = []
    photo = _photo_block(entry, "characters")
    if photo:
        blocks.append(photo)

    if tab == "bio":
        blocks += [
            _heading(f"{emoji} {name}", 2),
            _para(_rarity_line(entry) or _t(name)),
            _divider(),
            _field_para(
                [
                    _field("Title", entry.get("title")),
                    _field("Vision", entry.get("vision")),
                    _field("Weapon", entry.get("weapon")),
                    _field("Gender", entry.get("gender")),
                    _field("Nation", entry.get("nation")),
                    _field("Affiliation", entry.get("affiliation")),
                    _field("Constellation", entry.get("constellation")),
                    _field("Birthday", entry.get("birthday")),
                    _field("Released", entry.get("release")),
                ]
            ),
        ]
        if entry.get("description"):
            blocks.append(_quote(_italic(entry["description"])))

    elif tab == "talents":
        blocks += [
            _heading(f"{emoji} {name} · Talents", 2),
            _divider(),
        ]
        talents = _talent_list(entry.get("skillTalents") or [], "Combat Talents")
        passives = _talent_list(entry.get("passiveTalents") or [], "Passive Talents")
        if talents:
            blocks += talents
        if passives:
            blocks += passives
        if not talents and not passives:
            blocks.append(_para([RichTextItalic(text="No talent data available.")]))

    elif tab == "consts":
        blocks += [
            _heading(f"{emoji} {name} · Constellations", 2),
            _divider(),
        ]
        consts = [c for c in (entry.get("constellations") or []) if isinstance(c, dict)]
        if consts:
            blocks.append(
                InputRichBlockList(
                    items=[
                        _list_item(
                            f"C{c.get('level', '')}",
                            [
                                _para(_bold(c.get("name"))),
                                _para(_italic(c.get("description"))),
                            ],
                        )
                        for c in consts
                        if c.get("name")
                    ]
                )
            )
        else:
            blocks.append(
                _para([RichTextItalic(text="No constellation data available.")])
            )

    elif tab == "ascend":
        blocks += [
            _heading(f"{emoji} {name} · Ascension", 2),
            _divider(),
        ]
        materials = entry.get("ascension_materials")
        found = False
        if isinstance(materials, dict):
            for tier, costs in materials.items():
                if not isinstance(costs, list):
                    continue
                summary = ", ".join(
                    f"{c.get('name')} x{c.get('value')}"
                    for c in costs
                    if isinstance(c, dict) and c.get("name")
                )
                if summary:
                    found = True
                    blocks.append(
                        _para(
                            [
                                RichTextUnderline(text=f"{tier.title()}: "),
                                _t(summary),
                            ]
                        )
                    )
        if not found:
            blocks.append(
                _para([RichTextItalic(text="No ascension material data available.")])
            )

    markup = _character_keyboard(char_id, tab)
    return [b for b in blocks if b is not None], markup


def _render_weapon(entry: dict) -> list:
    blocks = _name_blocks(entry, "⚔️", "weapons")
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
        blocks.append(_heading(f"Passive: {entry['passiveName']}", 3))
        if entry.get("passiveDesc"):
            blocks.append(_para(_italic(entry["passiveDesc"])))
    return [b for b in blocks if b is not None]


def _render_artifact(entry: dict) -> list:
    blocks = _name_blocks(entry, "💍", "artifacts")
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
    return [b for b in blocks if b is not None]


def _render_nation(entry: dict) -> list:
    blocks = _name_blocks(entry, "🗺️", "nations")
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
        _photo_block(entry, "elements"),
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
            runs.append(". ")
            runs.append(_italic(reaction["description"]))
        items.append(InputRichBlockListItem(blocks=[_para(runs)]))
    if items:
        blocks.append(InputRichBlockList(items=items))
    return [b for b in blocks if b is not None]


def _render_enemy(entry: dict) -> list:
    blocks = [
        _photo_block(entry, "enemies"),
        _heading(f"👹 {entry.get('name', '?')}", 2),
        _divider(),
    ]
    blocks.append(
        _field_para(
            [
                _field("Type", entry.get("type")),
                _field("Family", entry.get("family")),
                _field("Faction", entry.get("faction")),
                _field("Region", entry.get("region")),
                _field("Elements", ", ".join(entry.get("elements") or []) or None),
                _field("Mora", entry.get("mora-gained")),
            ]
        )
    )
    description = entry.get("description")
    if description and description != "N/A":
        blocks.append(_quote(_italic(description)))

    drops = [
        d for d in (entry.get("drops") or []) if isinstance(d, dict) and d.get("name")
    ]
    if drops:
        blocks.append(_heading("Drops", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    _list_item(
                        _rarity_stars(d.get("rarity")) or "", [_para(_t(d.get("name")))]
                    )
                    for d in drops
                ]
            )
        )

    artifacts = [
        a
        for a in (entry.get("artifacts") or [])
        if isinstance(a, dict) and a.get("name")
    ]
    if artifacts:
        blocks.append(_heading("Artifact sets", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    _list_item(
                        str(a.get("rarity") or ""),
                        [
                            _para(_bold(a.get("name"))),
                            _para(_italic(str(a.get("set", "")).strip() or "—")),
                        ],
                    )
                    for a in artifacts
                ]
            )
        )

    elemental = [
        e
        for e in (entry.get("elemental-description") or [])
        if isinstance(e, dict) and e.get("description")
    ]
    if elemental:
        blocks.append(_heading("Elemental lore", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    _list_item(
                        VISION_EMOJI.get(str(e.get("element", "")).upper(), ""),
                        [_para(_italic(e["description"]))],
                    )
                    for e in elemental
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
                _field(
                    "Recommended",
                    ", ".join(entry.get("recommendedElements") or []) or None,
                ),
            ]
        )
    )
    if entry.get("description"):
        blocks.append(_quote(_italic(entry["description"])))

    rewards = [
        r for r in (entry.get("rewards") or []) if isinstance(r, dict) and r.get("name")
    ]
    if rewards:
        blocks.append(_heading("Rewards", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    _list_item(str(r.get("level") or ""), [_para(_t(r.get("name")))])
                    for r in rewards
                ]
            )
        )

    tiers = [r for r in (entry.get("requirements") or []) if isinstance(r, dict)]
    if tiers:
        blocks.append(_heading("Unlock tiers", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    _list_item(
                        f"AR {r.get('adventureRank', '—')}",
                        [
                            _para(
                                [
                                    _bold("Level "),
                                    _t(str(r.get("recommendedLevel", "—"))),
                                ]
                            ),
                            *[
                                _para(_italic(str(disorder)))
                                for disorder in r.get("leyLineDisorder") or []
                                if str(disorder).strip()
                                and str(disorder).strip() != "None"
                            ],
                        ],
                    )
                    for r in tiers
                ]
            )
        )
    return [b for b in blocks if b is not None]


def _render_grouped(entry: dict, kind: str) -> list:
    """Consumables and materials renderer."""
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
    crafting = (
        [c for c in crafting if isinstance(c, dict) and c.get("item")]
        if isinstance(crafting, list)
        else []
    )
    if crafting:
        blocks.append(_heading("Crafting", 3))
        blocks.append(
            InputRichBlockList(
                items=[
                    InputRichBlockListItem(
                        blocks=[
                            _para([_t(f"{c['item']} "), _code(f"x{c.get('quantity')}")])
                        ],
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
    "characters": lambda e: _render_character(e, "bio"),
    "weapons": lambda e: (_render_weapon(e), _card_close("weapons")),
    "artifacts": lambda e: (_render_artifact(e), _card_close("artifacts")),
    "nations": lambda e: (_render_nation(e), _card_close("nations")),
    "elements": lambda e: (_render_element(e), _card_close("elements")),
    "enemies": lambda e: (_render_enemy(e), _card_close("enemies")),
    "domains": lambda e: (_render_domain(e), _card_close("domains")),
    "consumables": lambda e: (
        _render_grouped(e, "consumables"),
        _card_close("consumables"),
    ),
    "materials": lambda e: (_render_grouped(e, "materials"), _card_close("materials")),
}


def _format_list_text(
    title: str, query: str, total_count: int, page: int, total_pages: int
) -> str:
    """HTML message for search lists so edits happen in-place without flicker."""
    return (
        f'<b>{title}</b> · <i>{total_count} match(es) for "{html_escape(query)}"</i>\n'
        f"Page {page} of {total_pages}\n\n"
        f"<i>Tap an item to view details:</i>"
    )


def _list_keyboard(
    kind: str, query: str, page: int, total_pages: int, items_on_page: list
) -> InlineKeyboardMarkup:
    """Item selection buttons and page controls."""
    item_buttons = []
    for item in items_on_page:
        item_id = str(item.get("id", ""))
        item_name = str(item.get("name", item_id))
        item_kind = item.get("_kind", kind)

        if item_kind == "characters":
            vision_k = str(item.get("vision_key", "")).upper()
            icon = VISION_EMOJI.get(vision_k, "🧝")
        else:
            icon = ENTITY_TYPES.get(item_kind, EntityType("", "", "", "•")).emoji

        stars = _rarity_stars(item.get("rarity", item.get("max_rarity")))
        star_str = f" {stars}" if stars else ""
        label = _cut(f"{icon} {item_name}{star_str}", 36)
        item_buttons.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"gview|{item_kind}|{item_id}"[:64]
                )
            ]
        )

    nav_row = []
    if total_pages > 1:
        prev_page = page - 1 if page > 1 else total_pages
        next_page = page + 1 if page < total_pages else 1

        def pg_cb(target_pg: int) -> str:
            head = f"gpage|{kind}|{target_pg}|"
            room = max(0, 64 - len(head.encode()))
            return head + query.encode()[:room].decode(errors="ignore")

        nav_row.append(InlineKeyboardButton(text="◁", callback_data=pg_cb(prev_page)))
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page}/{total_pages}", callback_data=f"gnop|{kind}"
            )
        )
        nav_row.append(InlineKeyboardButton(text="▷", callback_data=pg_cb(next_page)))

    close_btn = [InlineKeyboardButton(text="✕ Close", callback_data=f"gclose|{kind}")]

    keyboard = item_buttons
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(close_btn)
    return InlineKeyboardMarkup(keyboard)


# <=======================================================================================================>


# <================================================== SENDING ================================================>
async def _send_rich(
    chat_id: int, blocks: list, reply_markup=None, thread_id: int = None
):
    """Send a rich message, falling back to plain text if unsupported."""
    rich = InputRichMessage(blocks=blocks)
    try:
        return await app.send_rich_message(
            chat_id,
            rich,
            reply_markup=reply_markup,
            message_thread_id=thread_id,
        )
    except RPCError as err:
        LOGGER.debug("Rich message unavailable (%s), falling back to text", err)
        try:
            return await app.send_message(
                chat_id,
                _blocks_to_text(blocks),
                reply_markup=reply_markup,
                message_thread_id=thread_id,
            )
        except RPCError:
            LOGGER.debug("Could not deliver a genshin result", exc_info=True)
            return None


def _blocks_to_text(blocks: list) -> str:
    lines = []
    for block in blocks:
        if isinstance(block, InputRichBlockDivider):
            lines.append("———")
            continue
        photo = getattr(block, "photo", None)
        if photo is not None:
            media = getattr(photo, "media", None)
            if isinstance(media, str):
                lines.append(media)
            continue
        text = getattr(block, "text", None)
        if text is not None:
            lines.append(_flatten(text))
            continue
        items = getattr(block, "items", None)
        if items is not None:
            for item in items:
                inner = " ".join(
                    part
                    for part in (
                        _flatten(getattr(b, "text", ""))
                        for b in getattr(item, "blocks", [])
                    )
                    if part
                )
                if inner:
                    lines.append(inner)
            continue
    return "\n".join(x for x in lines if x)


def _flatten(node) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (list, tuple)):
        return "".join(_flatten(part) for part in node)
    inner = getattr(node, "text", None)
    return _flatten(inner) if inner is not None else ""


async def _replace(status: Message, text: str):
    try:
        await status.edit_text(text, parse_mode=ParseMode.HTML)
    except RPCError:
        try:
            await status.reply_text(text, parse_mode=ParseMode.HTML)
        except RPCError:
            LOGGER.debug("Could not deliver a genshin notice", exc_info=True)


# <================================================= COMMANDS ================================================>
async def _universal_lookup(message: Message, query: str):
    status = await message.reply_text(
        f"Looking up <b>{html_escape(query)}</b>…", parse_mode=ParseMode.HTML
    )
    try:
        matches = await _search_all(query)
    except LOOKUP_ERRORS as err:
        LOGGER.warning("Genshin universal search failed: %s", err)
        await _replace(status, "The lookup service is not responding right now.")
        return

    if not matches:
        await _replace(
            status,
            f"No Genshin data found for <b>{html_escape(query)}</b>.\n"
            "Check the spelling, or try part of the name.",
        )
        return

    thread_id = message.message_thread_id if message.chat.is_forum else None
    if len(matches) > 1:
        shown, page, total = _paginate(matches, 1)
        text = _format_list_text("⛩ Genshin Search", query, len(matches), page, total)
        markup = _list_keyboard("all", query, 1, total, shown)
        await message.reply_text(
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            message_thread_id=thread_id,
        )
        try:
            await status.delete()
        except RPCError:
            pass
    else:
        record = matches[0]
        kind = record.get("_kind", "characters")
        entity = ENTITY_TYPES[kind]
        if not entity.grouped:
            try:
                detail = await _fetch_detail(kind, record["id"])
                if detail:
                    record = detail
            except LOOKUP_ERRORS:
                pass
        blocks, markup = RENDERERS[kind](record)
        sent = await _send_rich(message.chat.id, blocks, markup, thread_id)
        if sent is not None:
            try:
                await status.delete()
            except RPCError:
                pass


async def _lookup(message: Message, kind: str):
    entity = ENTITY_TYPES[kind]
    parts = (message.text or "").split(None, 1)
    query = parts[1].strip() if len(parts) > 1 else ""

    if not query:
        await message.reply_text(
            f"{entity.emoji} <b>Genshin {entity.label}</b>\n\n"
            f"Please provide a name to search.\n"
            f"<b>Example:</b> <code>/{entity.command} albedo</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    status = await message.reply_text(
        f"Looking up <b>{html_escape(query)}</b>…", parse_mode=ParseMode.HTML
    )
    try:
        entries = await _search(kind)
    except LOOKUP_ERRORS as err:
        LOGGER.warning("Genshin %s lookup failed: %s", kind, err)
        await _replace(status, "The lookup service is not responding right now.")
        return

    if not entries:
        await _replace(status, f"No {entity.label.lower()} data available.")
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
        shown, page, total = _paginate(matches, 1)
        text = _format_list_text(
            f"{entity.emoji} {entity.label}s", query, len(matches), page, total
        )
        markup = _list_keyboard(kind, query, 1, total, shown)
        await message.reply_text(
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            message_thread_id=thread_id,
        )
        try:
            await status.delete()
        except RPCError:
            pass
    else:
        record = matches[0]
        if not entity.grouped:
            try:
                detail = await _fetch_detail(kind, record["id"])
                if detail:
                    record = detail
            except LOOKUP_ERRORS:
                pass
        blocks, markup = RENDERERS[kind](record)
        sent = await _send_rich(message.chat.id, blocks, markup, thread_id)
        if sent is not None:
            try:
                await status.delete()
            except RPCError:
                pass


@on_message(filters.command(["genshin", "gi"]), chained=True)
async def genshin_universal(client, message: Message):
    parts = (message.text or "").split(None, 1)
    if len(parts) <= 1 or not parts[1].strip():
        await message.reply_text(
            "⛩ <b>Genshin Impact Lookup</b>\n\n"
            "Search anything: characters, weapons, artifacts, materials, enemies, etc.\n\n"
            "<b>Usage:</b> <code>/gi &lt;name&gt;</code> or <code>/genshin &lt;name&gt;</code>\n"
            "<b>Example:</b> <code>/gi albedo</code>\n\n"
            "<b>Direct Category Commands:</b>\n"
            "🧝 <code>/gchar</code> — characters\n"
            "⚔️ <code>/gweapon</code> — weapons\n"
            "💍 <code>/gartifact</code> — artifact sets\n"
            "🍲 <code>/gconsumable</code> — consumables\n"
            "🪵 <code>/gmaterial</code> — materials\n"
            "👹 <code>/genemy</code> — enemies\n"
            "🏛️ <code>/gdomain</code> — domains\n"
            "🗺️ <code>/gnation</code> — nations\n"
            "⚗️ <code>/gelement</code> — elements",
            parse_mode=ParseMode.HTML,
        )
        return
    await _universal_lookup(message, parts[1].strip())


@on_message(filters.command(["gchar", "gcharlist"]), chained=True)
async def genshin_character(client, message: Message):
    await _lookup(message, "characters")


@on_message(filters.command("gweapon"), chained=True)
async def genshin_weapon(client, message: Message):
    await _lookup(message, "weapons")


@on_message(filters.command(["gartifact", "gset"]), chained=True)
async def genshin_artifact(client, message: Message):
    await _lookup(message, "artifacts")


@on_message(filters.command(["gconsumable", "gfood"]), chained=True)
async def genshin_consumable(client, message: Message):
    await _lookup(message, "consumables")


@on_message(filters.command("gmaterial"), chained=True)
async def genshin_material(client, message: Message):
    await _lookup(message, "materials")


@on_message(filters.command("genemy"), chained=True)
async def genshin_enemy(client, message: Message):
    await _lookup(message, "enemies")


@on_message(filters.command("gdomain"), chained=True)
async def genshin_domain(client, message: Message):
    await _lookup(message, "domains")


@on_message(filters.command("gnation"), chained=True)
async def genshin_nation(client, message: Message):
    await _lookup(message, "nations")


@on_message(filters.command("gelement"), chained=True)
async def genshin_element(client, message: Message):
    await _lookup(message, "elements")


# <================================================= CALLBACKS ================================================>
@on_callback(filters.regex(r"^gview\|"), chained=True)
async def genshin_view_item(client, query: CallbackQuery):
    """Open item details card directly when tapped from list."""
    parts = (query.data or "").split("|", 2)
    if len(parts) != 3 or parts[1] not in ENTITY_TYPES:
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, kind, item_id = parts
    entity = ENTITY_TYPES[kind]

    try:
        if not entity.grouped:
            record = await _fetch_detail(kind, item_id)
        else:
            entries = await _search(kind)
            record = next((e for e in entries if str(e.get("id")) == item_id), None)
    except LOOKUP_ERRORS as err:
        LOGGER.warning("Genshin view item failed: %s", err)
        await query.answer("Could not load item details.", show_alert=True)
        return

    if not record:
        await query.answer("Item details not found.", show_alert=True)
        return

    blocks, markup = RENDERERS[kind](record)
    thread_id = query.message.message_thread_id if query.message.chat.is_forum else None

    try:
        await query.message.delete()
    except RPCError:
        pass

    await _send_rich(query.message.chat.id, blocks, markup, thread_id)
    await query.answer()


@on_callback(filters.regex(r"^gchar_tab\|"), chained=True)
async def genshin_character_tab(client, query: CallbackQuery):
    """Switch character card tab (Profile, Talents, Constellations, Ascension)."""
    parts = (query.data or "").split("|", 2)
    if len(parts) != 3:
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, char_id, tab = parts
    try:
        record = await _fetch_detail("characters", char_id)
    except LOOKUP_ERRORS as err:
        LOGGER.warning("Genshin character tab fetch failed: %s", err)
        await query.answer("Could not load character details.", show_alert=True)
        return

    if not record:
        await query.answer("Character details not found.", show_alert=True)
        return

    blocks, markup = _render_character(record, tab)
    thread_id = query.message.message_thread_id if query.message.chat.is_forum else None

    try:
        await query.message.delete()
    except RPCError:
        pass

    await _send_rich(query.message.chat.id, blocks, markup, thread_id)
    await query.answer()


@on_callback(filters.regex(r"^gpage\|"), chained=True)
async def genshin_page(client, query: CallbackQuery):
    """Advance search list in-place without deleting message."""
    parts = (query.data or "").split("|", 3)
    if len(parts) != 4 or (parts[1] not in ENTITY_TYPES and parts[1] != "all"):
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, kind, raw_page, term = parts
    try:
        page = int(raw_page)
    except ValueError:
        await query.answer("This button is out of date.", show_alert=True)
        return

    try:
        if kind == "all":
            matches = await _search_all(term)
            title = "⛩ Genshin Search"
        else:
            matches = _match(await _search(kind), term)
            title = f"{ENTITY_TYPES[kind].emoji} {ENTITY_TYPES[kind].label}s"
    except LOOKUP_ERRORS as err:
        LOGGER.warning("Genshin page turn failed: %s", err)
        await query.answer("The lookup service is not responding.", show_alert=True)
        return

    if not matches:
        await query.answer("Nothing left to show.", show_alert=True)
        return

    shown, page, total = _paginate(matches, page)
    text = _format_list_text(title, term, len(matches), page, total)
    markup = _list_keyboard(kind, term, page, total, shown)

    try:
        await query.message.edit_text(
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
    except RPCError:
        LOGGER.debug("Could not edit genshin page in place", exc_info=True)
    await query.answer()


@on_callback(filters.regex(r"^gnop\|"), chained=True)
async def genshin_noop(client, query: CallbackQuery):
    await query.answer()


@on_callback(filters.regex(r"^(?:gclose|genshin_close)\|"), chained=True)
async def genshin_close(client, query: CallbackQuery):
    try:
        await query.message.delete()
    except RPCError:
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except RPCError:
            pass
    await query.answer()


@on_callback(filters.regex(r"^genshin\|"), chained=True)
async def genshin_legacy_page(client, query: CallbackQuery):
    await query.answer(
        "This button is out of date. Please search again.", show_alert=True
    )


# <================================================= HELP ====================================================
__help__ = """
⛩ *Genshin Impact Lookup*

» */gi* or */genshin* `<name>` — universal search across all categories
» */gchar* `<name>` — characters, talents, constellations & ascension
» */gweapon* `<name>` — type, base ATK, substat and passive
» */gartifact* `<name>` — set bonuses
» */gconsumable* `<name>` — food, potions and effects
» */gmaterial* `<name>` — ascension materials and who uses them
» */genemy* `<name>` — family, faction and drops
» */gdomain* `<name>` — type, location and rewards
» */gnation* `<name>` — archon and ruling body
» */gelement* `<name>` — reactions and descriptions

➠ Search results feature interactive tap-to-view buttons and instant page navigation.
➠ Character profiles include tabbed navigation for Talents, Constellations, and Ascension.
"""

__mod_name__ = "Genshin"

# <================================================== END ====================================================>
