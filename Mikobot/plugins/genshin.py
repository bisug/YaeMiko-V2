# <============================================== IMPORTS =========================================================>
import asyncio
import html
import logging
import time
from dataclasses import dataclass

import httpx
from cachetools import TTLCache
from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from Mikobot import app
from Mikobot.events import on_callback, on_message
from Mikobot.state import state

# <=======================================================================================================>

# <================================================= CONSTANTS =================================================>
API = "https://genshin-api.deve.sh"
REQUEST_TIMEOUT = 15
LOGGER = logging.getLogger(__name__)

PAGE_SIZE = 6
ROSTER_TTL = 900

_ROSTER_CACHE: dict[str, tuple[float, list]] = {}
_DETAIL_CACHE: TTLCache[tuple[str, str], tuple[float, dict]] = TTLCache(
    maxsize=1000, ttl=ROSTER_TTL
)
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
    ("flower", "Flower", "🌸"),
    ("plume", "Plume", "🪶"),
    ("sands", "Sands", "⏳"),
    ("goblet", "Goblet", "🍷"),
    ("circlet", "Circlet", "👑"),
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
        EntityType("materials", "Material", "gmaterial", "🪵", handler="material"),
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


def _lines(text, limit: int = 260) -> str:
    """Flatten a multi-line description into one readable block."""
    return _cut(" ".join(str(text or "").split()), limit)


def html_escape(text: object) -> str:
    """Escapes for plain-HTML notices."""
    return html.escape(str(text or ""))


def _rarity_stars(value) -> str:
    try:
        count = int(value)
        return "⭐" * count if 1 <= count <= 5 else ""
    except TypeError, ValueError:
        return ""


def _format_birthday(value: str | None) -> str | None:
    if not value:
        return None
    val = str(value).strip()
    if val.startswith("0000-"):
        return val[5:]
    return val


async def _fetch(path: str):
    """One GET against the API, returning decoded JSON."""
    response = await state.get(f"{API}/{path}", timeout=REQUEST_TIMEOUT)
    if response.status_code == 404:
        raise _NotFound(path)
    response.raise_for_status()
    return response.json()


async def _fetch_roster(kind: str) -> list:
    """Records for collections, supporting both genshin-api.deve.sh and legacy formats."""
    if kind == "nations":
        try:
            data = await _fetch("characters/nations")
            if isinstance(data, dict) and "nations" in data:
                return [
                    {"id": n.lower(), "key": n.lower(), "name": n}
                    for n in data["nations"]
                ]
        except _NotFound:
            pass
    elif kind == "elements":
        try:
            data = await _fetch("characters/elements")
            if isinstance(data, dict) and "elements" in data:
                return [
                    {
                        "id": e.lower(),
                        "key": e.lower(),
                        "name": e,
                        "key_name": e.upper(),
                    }
                    for e in data["elements"]
                ]
        except _NotFound:
            pass

    try:
        data = await _fetch(f"{kind}?details=true")
    except _NotFound:
        try:
            data = await _fetch(f"{kind}/all")
        except _NotFound:
            return []

    items = []
    if isinstance(data, dict):
        if kind in data and isinstance(data[kind], list):
            items = data[kind]
        else:
            for cat, val in data.items():
                if isinstance(val, dict):
                    for item_id, item_val in val.items():
                        if isinstance(item_val, dict):
                            rec = dict(item_val)
                            rec.setdefault("id", item_id)
                            rec.setdefault("key", item_id)
                            rec["category"] = cat
                            items.append(rec)
    elif isinstance(data, list):
        items = data

    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rec = dict(item)
        slug = rec.get("key") or rec.get("id")
        if not slug:
            continue
        rec["id"] = str(slug)
        rec["key"] = str(slug)
        normalized.append(rec)
    return normalized


async def _search(kind: str) -> list:
    """Every searchable record for a collection, cached for ROSTER_TTL."""
    cached = _ROSTER_CACHE.get(kind)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    records = await _fetch_roster(kind)
    _ROSTER_CACHE[kind] = (time.monotonic() + ROSTER_TTL, records)
    return records


async def _search_all(query: str) -> list:
    """Search across all supported collections."""
    query_clean = query.casefold().strip()

    if len(query_clean) >= 2:
        try:
            res = await _fetch(f"search?q={query_clean}")
            if isinstance(res, dict) and "results" in res:
                all_matches = []
                for kind, items in res["results"].items():
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if isinstance(item, dict):
                            rec = dict(item)
                            slug = rec.get("key") or rec.get("id")
                            if slug:
                                rec["id"] = str(slug)
                                rec["key"] = str(slug)
                                rec["_kind"] = kind
                                all_matches.append(rec)
                if all_matches:
                    return all_matches
        except LOOKUP_ERRORS:
            pass

    search_kinds = [
        k
        for k in ENTITY_TYPES
        if k in ("characters", "weapons", "artifacts", "materials", "enemies")
    ]
    tasks = [_search(k) for k in search_kinds]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_matches = []

    for kind, res in zip(search_kinds, results, strict=True):
        if isinstance(res, list):
            matched = _match(res, query)
            for m in matched:
                item = dict(m)
                item["_kind"] = kind
                all_matches.append(item)

    def score(item):
        name = str(item.get("name", "")).casefold()
        ident = str(item.get("key") or item.get("id", "")).casefold()
        if name == query_clean or ident == query_clean:
            return 0
        if name.startswith(query_clean) or ident.startswith(query_clean):
            return 1
        if any(word.startswith(query_clean) for word in name.split()):
            return 2
        if query_clean in name or query_clean in ident:
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

    try:
        detail = await _fetch(f"{kind}/{record_id}")
    except _NotFound:
        entries = await _search(kind)
        detail = next(
            (e for e in entries if str(e.get("key") or e.get("id")) == record_id),
            {},
        )

    if isinstance(detail, dict) and detail:
        detail = dict(detail)
        detail.setdefault("id", record_id)
        detail.setdefault("key", record_id)
        if isinstance(detail.get("characters"), list):
            try:
                names = await _character_names()
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
        ident = str(entry.get("key") or entry.get("id", "")).casefold()
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


def _image_url(entry: dict, kind: str, slot: str = "") -> str | None:
    img = entry.get("img")
    if isinstance(img, str) and img.startswith("http"):
        return img
    if isinstance(img, dict):
        if kind == "characters":
            url = (
                img.get("portrait")
                or img.get("icon-big")
                or img.get("icon")
                or img.get("card")
            )
            if url and isinstance(url, str) and url.startswith("http"):
                return url
        elif kind == "weapons":
            url = img.get("icon") or img.get("full") or img.get("wish")
            if url and isinstance(url, str) and url.startswith("http"):
                return url
        for val in img.values():
            if isinstance(val, str) and val.startswith("http"):
                return val

    if kind == "artifacts":
        pieces = entry.get("pieces")
        if isinstance(pieces, dict):
            piece_data = pieces.get(slot or "flower") or (
                next(iter(pieces.values())) if pieces else None
            )
            if isinstance(piece_data, dict):
                p_img = piece_data.get("img")
                if isinstance(p_img, str) and p_img.startswith("http"):
                    return p_img

    record_id = str(entry.get("key") or entry.get("id", ""))
    entity = ENTITY_TYPES.get(kind)
    if not record_id or entity is None or not entity.image:
        return None
    if entity.image == "pieces":
        piece = slot or ARTIFACT_PIECES[0][0]
        return f"{API}/{kind}/{record_id}/{piece}"
    return f"{API}/{kind}/{record_id}/{entity.image}"


async def _character_names() -> dict:
    global _CHARACTER_NAME_CACHE
    if (
        _CHARACTER_NAME_CACHE
        and _CHARACTER_NAME_CACHE.get("expires", 0) > time.monotonic()
    ):
        return _CHARACTER_NAME_CACHE.get("data", {})
    names = {}
    for record in await _search("characters"):
        rec_id = str(record.get("key") or record.get("id") or "")
        if rec_id:
            names[rec_id] = record.get("name") or rec_id
    _CHARACTER_NAME_CACHE = {"expires": time.monotonic() + ROSTER_TTL, "data": names}
    return names


# <=======================================================================================================>


# <=============================================== RENDERING ===============================================>
def _character_keyboard(char_id: str, active_tab: str) -> InlineKeyboardMarkup:
    """Tab buttons for character cards."""

    def tab_btn(tab_key: str, label: str):
        display = f"• {label} •" if tab_key == active_tab else label
        return InlineKeyboardButton(
            text=display, callback_data=f"gi:tab:{char_id}:{tab_key}"[:64]
        )

    return InlineKeyboardMarkup(
        [
            [tab_btn("bio", "📜 Profile"), tab_btn("talents", "⚔️ Talents")],
            [tab_btn("consts", "⭐ Consts"), tab_btn("ascend", "💎 Ascend")],
            [InlineKeyboardButton(text="✕ Close", callback_data="gi:close:characters")],
        ]
    )


def _card_close(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text="✕ Close", callback_data=f"gi:close:{kind}")]]
    )


def _render_character(
    entry: dict, tab: str = "bio"
) -> tuple[str, InlineKeyboardMarkup, str | None]:
    char_id = str(entry.get("key") or entry.get("id", ""))
    vision_key = str(entry.get("vision_key") or entry.get("vision", "")).upper()
    emoji = VISION_EMOJI.get(vision_key, "🧝")
    name = html_escape(entry.get("name", "Unknown"))
    stars = _rarity_stars(entry.get("rarity", 5))
    star_str = f" {stars}" if stars else ""
    title = html_escape(entry.get("title", ""))
    img_url = _image_url(entry, "characters")

    lines = [f"{emoji} <b>{name}</b>{star_str}"]
    if title:
        lines.append(f"<i>{title}</i>")
    lines.append("")

    if tab == "bio":
        lines.append("<b>Profile</b>")
        fields = [
            ("Vision", f"{html_escape(entry.get('vision', ''))} {emoji}".strip()),
            ("Weapon", html_escape(entry.get("weapon", ""))),
            ("Nation", html_escape(entry.get("nation", ""))),
            ("Affiliation", html_escape(entry.get("affiliation", ""))),
            ("Constellation", html_escape(entry.get("constellation", ""))),
            ("Birthday", _format_birthday(entry.get("birthday"))),
            ("Gender", html_escape(entry.get("gender", ""))),
        ]
        for label, val in fields:
            if val:
                lines.append(f"• <b>{label}:</b> {val}")

        desc = entry.get("description")
        if desc:
            lines.append("")
            lines.append("<b>Description</b>")
            lines.append(f"<blockquote>{html_escape(_cut(desc, 600))}</blockquote>")

    elif tab == "talents":
        lines.append("⚔️ <b>Combat Talents</b>")
        skills = [
            s
            for s in (entry.get("skillTalents") or [])
            if isinstance(s, dict) and s.get("name")
        ]
        if skills:
            for s in skills:
                s_name = html_escape(s.get("name", ""))
                s_unlock = html_escape(s.get("unlock", ""))
                s_desc = html_escape(_lines(s.get("description", ""), 300))
                tag = f" <code>[{s_unlock}]</code>" if s_unlock else ""
                lines.append(f"\n🔹 <b>{s_name}</b>{tag}")
                if s_desc:
                    lines.append(f"<blockquote>{s_desc}</blockquote>")
        else:
            lines.append("<i>No combat talents available.</i>")

        passives = [
            p
            for p in (entry.get("passiveTalents") or [])
            if isinstance(p, dict) and p.get("name")
        ]
        if passives:
            lines.append("\n✨ <b>Passive Talents</b>")
            for p in passives:
                p_name = html_escape(p.get("name", ""))
                p_unlock = html_escape(p.get("unlock", ""))
                p_desc = html_escape(_lines(p.get("description", ""), 250))
                tag = f" <code>[{p_unlock}]</code>" if p_unlock else ""
                lines.append(f"\n🔸 <b>{p_name}</b>{tag}")
                if p_desc:
                    lines.append(f"<blockquote>{p_desc}</blockquote>")

    elif tab == "consts":
        lines.append("⭐ <b>Constellations</b>\n")
        consts = [
            c
            for c in (entry.get("constellations") or [])
            if isinstance(c, dict) and c.get("name")
        ]
        if consts:
            for c in consts:
                c_name = html_escape(c.get("name", ""))
                c_lvl = c.get("level", "")
                c_desc = html_escape(_lines(c.get("description", ""), 280))
                lines.append(f"<b>C{c_lvl}: {c_name}</b>")
                if c_desc:
                    lines.append(f"<blockquote>{c_desc}</blockquote>")
        else:
            lines.append("<i>No constellation data available.</i>")

    elif tab == "ascend":
        lines.append("💎 <b>Ascension Costs</b>\n")
        costs = entry.get("ascension_costs")
        materials = entry.get("ascension_materials")
        found = False
        if isinstance(costs, list):
            for c in costs:
                if not isinstance(c, dict):
                    continue
                mat_list = c.get("materials") or []
                mat_parts = [
                    f"• {html_escape(m.get('name') or str(m.get('slug', '')).replace('-', ' ').title())} x{m.get('quantity', 0)}"
                    for m in mat_list
                    if isinstance(m, dict) and (m.get("slug") or m.get("name"))
                ]
                if c.get("mora"):
                    mat_parts.append(f"• 💰 Mora: {c['mora']:,}")
                if mat_parts:
                    found = True
                    phase_label = f"<b>Phase {c.get('phase', '')}</b> (Max Lv. {c.get('max_level', '')})"
                    lines.append(phase_label)
                    lines.extend(mat_parts)
                    lines.append("")
        elif isinstance(materials, dict):
            for tier, tier_costs in materials.items():
                if not isinstance(tier_costs, list):
                    continue
                items_str = ", ".join(
                    f"{html_escape(c.get('name'))} x{c.get('value')}"
                    for c in tier_costs
                    if isinstance(c, dict) and c.get("name")
                )
                if items_str:
                    found = True
                    lines.append(f"• <b>{html_escape(tier.title())}:</b> {items_str}")
        if not found:
            lines.append("<i>No ascension material data available.</i>")

    markup = _character_keyboard(char_id, tab)
    return "\n".join(lines).strip(), markup, img_url


def _render_weapon(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    name = html_escape(entry.get("name", "Unknown"))
    stars = _rarity_stars(entry.get("rarity", 5))
    star_str = f" {stars}" if stars else ""
    img_url = _image_url(entry, "weapons")

    lines = [f"⚔️ <b>{name}</b>{star_str}\n"]

    w_type = entry.get("type")
    base_atk = entry.get("base_atk", entry.get("baseAttack"))
    sub_stat = entry.get("sub_stat", entry.get("subStat"))
    loc = entry.get("location")

    lines.append("<b>Details</b>")
    if w_type:
        lines.append(f"• <b>Type:</b> {html_escape(w_type)}")
    if base_atk:
        lines.append(f"• <b>Base ATK:</b> {html_escape(base_atk)}")
    if sub_stat:
        lines.append(f"• <b>Substat:</b> {html_escape(sub_stat)}")
    if loc:
        lines.append(f"• <b>Source:</b> {html_escape(loc)}")

    p_name = entry.get("passive_name") or entry.get("passiveName")
    p_desc = entry.get("passive_desc") or entry.get("passiveDesc")
    if p_name:
        lines.append(f"\n<b>Passive: {html_escape(p_name)}</b>")
        if p_desc:
            lines.append(f"<blockquote>{html_escape(_cut(p_desc, 500))}</blockquote>")

    desc = entry.get("description")
    if desc:
        lines.append(f"\n<i>{html_escape(_lines(desc, 300))}</i>")

    return "\n".join(lines).strip(), _card_close("weapons"), img_url


def _render_artifact(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    name = html_escape(entry.get("name", "Unknown"))
    stars = _rarity_stars(entry.get("rarity", 5))
    star_str = f" {stars}" if stars else ""
    img_url = _image_url(entry, "artifacts")

    lines = [f"💍 <b>{name}</b>{star_str}\n"]

    bonus = entry.get("bonus")
    lines.append("<b>Set Bonuses</b>")
    if isinstance(bonus, dict) and bonus:
        for k, v in sorted(bonus.items()):
            label = k.upper().replace("PC", "-Piece")
            lines.append(f"• <b>{label}:</b> {html_escape(v)}")
    else:
        for k in ("2-piece", "4-piece", "1-piece"):
            val = entry.get(f"{k}_bonus")
            if val:
                lines.append(f"• <b>{k.title()}:</b> {html_escape(val)}")

    pieces = entry.get("pieces")
    if isinstance(pieces, dict) and pieces:
        lines.append("\n<b>Artifact Pieces</b>")
        piece_icons = {
            "flower": "🌸",
            "plume": "🪶",
            "sands": "⏳",
            "goblet": "🍷",
            "circlet": "👑",
        }
        for k, p_data in pieces.items():
            if isinstance(p_data, dict) and p_data.get("name"):
                icon = piece_icons.get(k, "•")
                p_label = k.title()
                p_name = html_escape(p_data["name"])
                lines.append(f"{icon} <b>{p_label}:</b> {p_name}")

    return "\n".join(lines).strip(), _card_close("artifacts"), img_url


def _render_material(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    name = html_escape(entry.get("name", "Unknown"))
    stars = _rarity_stars(entry.get("rarity"))
    star_str = f" {stars}" if stars else ""
    img_url = _image_url(entry, "materials")

    lines = [f"🪵 <b>{name}</b>{star_str}\n"]

    category = str(entry.get("category", "")).replace("-", " ").title()
    source = entry.get("source") or entry.get("region")
    if isinstance(source, dict):
        source = ", ".join(f"{k.title()}: {v}" for k, v in source.items() if v)

    lines.append("<b>Details</b>")
    if category:
        lines.append(f"• <b>Category:</b> {html_escape(category)}")
    if entry.get("type"):
        lines.append(f"• <b>Type:</b> {html_escape(entry['type'])}")
    if source:
        lines.append(f"• <b>Source:</b> {html_escape(str(source))}")

    users = entry.get("characters")
    if not users and isinstance(entry.get("used_by"), dict):
        users = entry["used_by"].get("characters")
    if isinstance(users, list) and users:
        user_names = [str(u).replace("-", " ").title() for u in users]
        lines.append(f"• <b>Used By:</b> {html_escape(', '.join(user_names))}")

    if entry.get("effect"):
        lines.append(f"\n<b>Effect:</b> {html_escape(entry['effect'])}")

    desc = entry.get("description")
    if desc:
        lines.append(f"\n<blockquote>{html_escape(_cut(desc, 500))}</blockquote>")

    return "\n".join(lines).strip(), _card_close("materials"), img_url


def _render_enemy(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    name = html_escape(entry.get("name", "Unknown"))
    img_url = _image_url(entry, "enemies")

    lines = [f"👹 <b>{name}</b>\n"]
    lines.append("<b>Details</b>")
    if entry.get("type"):
        lines.append(f"• <b>Type:</b> {html_escape(entry['type'])}")
    if entry.get("family"):
        lines.append(f"• <b>Family:</b> {html_escape(entry['family'])}")
    if entry.get("faction"):
        lines.append(f"• <b>Faction:</b> {html_escape(entry['faction'])}")
    if entry.get("region"):
        lines.append(f"• <b>Region:</b> {html_escape(entry['region'])}")

    elements = entry.get("elements")
    if isinstance(elements, list) and elements:
        elem_parts = [
            f"{e} {VISION_EMOJI.get(e.upper(), '')}".strip() for e in elements
        ]
        lines.append(f"• <b>Elements:</b> {html_escape(', '.join(elem_parts))}")

    drops = [
        d
        for d in (entry.get("drops") or [])
        if isinstance(d, dict) and (d.get("name") or d.get("slug"))
    ]
    if drops:
        lines.append("\n<b>Drops</b>")
        for d in drops:
            d_name = html_escape(
                d.get("name") or str(d.get("slug", "")).replace("-", " ").title()
            )
            d_stars = _rarity_stars(d.get("rarity"))
            d_star_str = f" ({d_stars})" if d_stars else ""
            lines.append(f"• {d_name}{d_star_str}")

    desc = entry.get("description")
    if desc and desc != "N/A":
        lines.append(f"\n<blockquote>{html_escape(_cut(desc, 500))}</blockquote>")

    return "\n".join(lines).strip(), _card_close("enemies"), img_url


def _render_nation(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    name = html_escape(entry.get("name", "Unknown"))
    img_url = _image_url(entry, "nations")
    lines = [f"🗺️ <b>{name}</b>\n"]
    lines.append("<b>Details</b>")
    if entry.get("element"):
        lines.append(f"• <b>Element:</b> {html_escape(entry['element'])}")
    if entry.get("archon"):
        lines.append(f"• <b>Archon:</b> {html_escape(entry['archon'])}")
    if entry.get("controllingEntity"):
        lines.append(f"• <b>Ruling Body:</b> {html_escape(entry['controllingEntity'])}")
    return "\n".join(lines).strip(), _card_close("nations"), img_url


def _render_element(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    key = str(entry.get("key") or entry.get("id") or "").upper()
    emoji = VISION_EMOJI.get(key, "⚗️")
    name = html_escape(entry.get("name", "Unknown"))
    img_url = _image_url(entry, "elements")
    lines = [f"{emoji} <b>{name}</b>\n"]
    reactions = [r for r in (entry.get("reactions") or []) if isinstance(r, dict)]
    if reactions:
        lines.append("<b>Reactions</b>")
        for r in reactions:
            r_name = html_escape(r.get("name", "?"))
            against = ", ".join(r.get("elements") or [])
            r_desc = html_escape(r.get("description", ""))
            against_str = f" <i>(with {against})</i>" if against else ""
            lines.append(f"• <b>{r_name}</b>{against_str}")
            if r_desc:
                lines.append(f"  <blockquote>{r_desc}</blockquote>")
    return "\n".join(lines).strip(), _card_close("elements"), img_url


def _render_domain(entry: dict) -> tuple[str, InlineKeyboardMarkup, str | None]:
    name = html_escape(entry.get("name", "Unknown"))
    lines = [f"🏛️ <b>{name}</b>\n"]
    lines.append("<b>Details</b>")
    if entry.get("type"):
        lines.append(f"• <b>Type:</b> {html_escape(entry['type'])}")
    if entry.get("nation"):
        lines.append(f"• <b>Nation:</b> {html_escape(entry['nation'])}")
    if entry.get("location"):
        lines.append(f"• <b>Location:</b> {html_escape(entry['location'])}")
    desc = entry.get("description")
    if desc:
        lines.append(f"\n<blockquote>{html_escape(_cut(desc, 500))}</blockquote>")
    return "\n".join(lines).strip(), _card_close("domains"), None


RENDERERS = {
    "characters": lambda e: _render_character(e, "bio"),
    "weapons": _render_weapon,
    "artifacts": _render_artifact,
    "materials": _render_material,
    "enemies": _render_enemy,
    "nations": _render_nation,
    "elements": _render_element,
    "domains": _render_domain,
    "consumables": _render_material,
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
        item_id = str(item.get("key") or item.get("id", ""))
        item_name = str(item.get("name", item_id))
        item_kind = item.get("_kind", kind)

        if item_kind == "characters":
            vision_k = str(item.get("vision_key") or item.get("vision") or "").upper()
            icon = VISION_EMOJI.get(vision_k, "🧝")
        else:
            icon = ENTITY_TYPES.get(item_kind, EntityType("", "", "", "•")).emoji

        stars = _rarity_stars(item.get("rarity", item.get("max_rarity")))
        star_str = f" {stars}" if stars else ""
        label = _cut(f"{icon} {item_name}{star_str}", 36)
        item_buttons.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"gi:view:{item_kind}:{item_id}"[:64]
                )
            ]
        )

    nav_row = []
    if total_pages > 1:
        prev_page = page - 1 if page > 1 else total_pages
        next_page = page + 1 if page < total_pages else 1

        def pg_cb(target_pg: int) -> str:
            head = f"gi:page:{kind}:{target_pg}:"
            room = max(0, 64 - len(head.encode()))
            return head + query.encode()[:room].decode(errors="ignore")

        nav_row.append(InlineKeyboardButton(text="◁", callback_data=pg_cb(prev_page)))
        nav_row.append(
            InlineKeyboardButton(
                text=f"{page}/{total_pages}", callback_data=f"gi:nop:{kind}"
            )
        )
        nav_row.append(InlineKeyboardButton(text="▷", callback_data=pg_cb(next_page)))

    close_btn = [InlineKeyboardButton(text="✕ Close", callback_data=f"gi:close:{kind}")]

    keyboard = item_buttons
    if nav_row:
        keyboard.append(nav_row)
    keyboard.append(close_btn)
    return InlineKeyboardMarkup(keyboard)


# <=======================================================================================================>


# <================================================== SENDING ================================================>
async def _send_card(
    chat_id: int,
    text: str,
    image_url: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    thread_id: int | None = None,
):
    """Deliver a card: as a photo with caption if an image URL exists, else HTML text."""
    if image_url:
        try:
            return await app.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=text,
                reply_markup=reply_markup,
                message_thread_id=thread_id,
                parse_mode=ParseMode.HTML,
            )
        except RPCError as err:
            LOGGER.debug("Photo send failed (%s), falling back to text", err)

    try:
        return await app.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=thread_id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except RPCError:
        LOGGER.debug("Could not deliver genshin message", exc_info=True)
        return None


async def _replace(status: Message, text: str):
    try:
        await status.edit_text(text, parse_mode=ParseMode.HTML)
    except RPCError:
        try:
            await status.reply_text(text, parse_mode=ParseMode.HTML)
        except RPCError:
            LOGGER.debug("Could not deliver a genshin notice", exc_info=True)


# <=======================================================================================================>


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
            disable_web_page_preview=True,
        )
        try:
            await status.delete()
        except RPCError:
            pass
    else:
        record = matches[0]
        kind = record.get("_kind", "characters")
        rec_id = str(record.get("key") or record.get("id") or "")
        try:
            detail = await _fetch_detail(kind, rec_id)
            if detail:
                record = detail
        except LOOKUP_ERRORS:
            pass
        text, markup, img_url = RENDERERS[kind](record)
        sent = await _send_card(message.chat.id, text, img_url, markup, thread_id)
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
            disable_web_page_preview=True,
        )
        try:
            await status.delete()
        except RPCError:
            pass
    else:
        record = matches[0]
        rec_id = str(record.get("key") or record.get("id") or "")
        try:
            detail = await _fetch_detail(kind, rec_id)
            if detail:
                record = detail
        except LOOKUP_ERRORS:
            pass
        text, markup, img_url = RENDERERS[kind](record)
        sent = await _send_card(message.chat.id, text, img_url, markup, thread_id)
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
@on_callback(filters.regex(r"^gi:view:"), chained=True)
async def genshin_view_item(client, query: CallbackQuery):
    """Open item details card directly when tapped from list."""
    parts = (query.data or "").split(":", 3)
    if len(parts) != 4 or parts[2] not in ENTITY_TYPES:
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, _, kind, item_id = parts
    await query.answer()

    record = await _fetch_detail(kind, item_id)
    if not record:
        entries = await _search(kind)
        record = next(
            (e for e in entries if str(e.get("key") or e.get("id")) == item_id),
            None,
        )

    if not record:
        await query.answer("Item details not found.", show_alert=True)
        return

    text, markup, img_url = RENDERERS[kind](record)
    thread_id = query.message.message_thread_id if query.message.chat.is_forum else None

    try:
        await query.message.delete()
    except RPCError:
        pass

    await _send_card(query.message.chat.id, text, img_url, markup, thread_id)


@on_callback(filters.regex(r"^gi:tab:"), chained=True)
async def genshin_character_tab(client, query: CallbackQuery):
    """Switch character card tab in-place instantly."""
    parts = (query.data or "").split(":", 3)
    if len(parts) != 4:
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, _, char_id, tab = parts
    # Acknowledge immediately to dismiss any loading spinner
    await query.answer()

    record = await _fetch_detail("characters", char_id)
    if not record:
        await query.answer("Character details not found.", show_alert=True)
        return

    text, markup, _ = _render_character(record, tab)
    msg = query.message
    try:
        if msg.photo:
            await msg.edit_caption(
                caption=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.edit_text(
                text=text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except RPCError as err:
        LOGGER.debug("Character tab in-place edit failed: %s", err)


@on_callback(filters.regex(r"^gi:page:"), chained=True)
async def genshin_page(client, query: CallbackQuery):
    """Advance search list in-place without deleting message."""
    parts = (query.data or "").split(":", 4)
    if len(parts) != 5 or (parts[2] not in ENTITY_TYPES and parts[2] != "all"):
        await query.answer("This button is out of date.", show_alert=True)
        return

    _, _, kind, raw_page, term = parts
    try:
        page = int(raw_page)
    except ValueError:
        await query.answer("This button is out of date.", show_alert=True)
        return

    await query.answer()

    if kind == "all":
        matches = await _search_all(term)
        title = "⛩ Genshin Search"
    else:
        matches = _match(await _search(kind), term)
        title = f"{ENTITY_TYPES[kind].emoji} {ENTITY_TYPES[kind].label}s"

    if not matches:
        return

    shown, page, total = _paginate(matches, page)
    text = _format_list_text(title, term, len(matches), page, total)
    markup = _list_keyboard(kind, term, page, total, shown)

    try:
        await query.message.edit_text(
            text=text,
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except RPCError:
        pass


@on_callback(filters.regex(r"^gi:nop:"), chained=True)
async def genshin_noop(client, query: CallbackQuery):
    await query.answer()


@on_callback(filters.regex(r"^gi:close:"), chained=True)
async def genshin_close(client, query: CallbackQuery):
    try:
        await query.message.delete()
    except RPCError:
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except RPCError:
            pass
    await query.answer()


@on_callback(
    filters.regex(r"^(?:gview|gchar_tab|gpage|gnop|gclose|genshin)(?:\||:)"),
    chained=True,
)
async def genshin_legacy_cb(client, query: CallbackQuery):
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
