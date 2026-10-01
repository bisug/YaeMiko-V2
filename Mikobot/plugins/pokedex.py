import html
import math
from urllib.parse import quote

from aiogram import F
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from httpx import HTTPError

from Mikobot import dp
from Mikobot.state import state
from Mikobot.utils.gate import chain

POKEAPI = "https://pokeapi.co/api/v2"
MOVES_PER_PAGE = 20
CALLBACK_PREFIX = "pk"


async def _get_json(url: str, params: dict | None = None) -> dict:
    response = await state.get(url, params=params)
    response.raise_for_status()
    return response.json()


async def get_pokemon(name_or_id: str) -> dict:
    identifier = quote(str(name_or_id).strip().lower(), safe="")
    return await _get_json(f"{POKEAPI}/pokemon/{identifier}")


async def get_pokemon_details(pokemon: dict) -> tuple[dict, dict | None]:
    species = await _get_json(pokemon["species"]["url"])
    evolution_url = species.get("evolution_chain", {}).get("url")
    evolution = await _get_json(evolution_url) if evolution_url else None
    return species, evolution


def _display_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.replace("-", " ").split())


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def _english_text(entries: list[dict], text_key: str) -> str:
    for entry in entries:
        if entry.get("language", {}).get("name") == "en":
            return html.unescape(str(entry.get(text_key) or "")).replace("\n", " ").strip()
    return ""


def _flavor_text(species: dict) -> str:
    return _english_text(species.get("flavor_text_entries", []), "flavor_text")


def _gender_text(species: dict) -> str:
    rate = species.get("gender_rate")
    if rate == -1:
        return "Unknown"
    female = rate * 100 / 8
    return f"{female:.1f}% female / {100 - female:.1f}% male"


def _evolution_text(chain: dict) -> str:
    def flatten(node: dict) -> list[dict]:
        children = [child for child in node.get("evolves_to", []) if child]
        return [node, *(child for item in children for child in flatten(item))]

    path = flatten(chain.get("chain", {}))
    if not path:
        return "No evolution data available."
    return " → ".join(
        _escape(_display_name(item["species"]["name"])) for item in path
    )


def _keyboard(
    pokemon_id: int, view: str = "info", page: int = 0, pages: int = 1
) -> InlineKeyboardMarkup:
    prefix = f"{CALLBACK_PREFIX}:{pokemon_id}"
    if view == "moves":
        buttons = []
        if page > 0:
            buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Previous", callback_data=f"{prefix}:moves:{page - 1}"
                , style=ButtonStyle.PRIMARY)
            )
        buttons.append(
            InlineKeyboardButton(
                text=f"Page {page + 1}/{pages}", callback_data=f"{prefix}:info:{page}"
            , style=ButtonStyle.PRIMARY)
        )
        if page + 1 < pages:
            buttons.append(
                InlineKeyboardButton(
                    text="Next ➡️", callback_data=f"{prefix}:moves:{page + 1}"
                , style=ButtonStyle.PRIMARY)
            )
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Overview", callback_data=f"{prefix}:info:0", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="Stats", callback_data=f"{prefix}:stats:0", style=ButtonStyle.PRIMARY),
            ],
            [
                InlineKeyboardButton(text="Moves", callback_data=f"{prefix}:moves:0", style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(
                    text="Evolution", callback_data=f"{prefix}:evolution:0"
                , style=ButtonStyle.PRIMARY),
            ],
        ]
    )


def _overview(pokemon: dict, species: dict) -> tuple[str, str]:
    name = _display_name(pokemon["name"])
    genus = _english_text(species.get("genera", []), "genus") or "Unknown"
    flavor = _flavor_text(species) or "No description available."
    image = (
        pokemon.get("sprites", {})
        .get("other", {})
        .get("official-artwork", {})
        .get("front_default")
        or pokemon.get("sprites", {}).get("front_default")
    )
    abilities = ", ".join(
        f"{_escape(item['ability']['name'].replace('-', ' '))}"
        f"{' (hidden)' if item['is_hidden'] else ''}"
        for item in pokemon.get("abilities", [])
    )
    types = ", ".join(
        _escape(item["type"]["name"]) for item in pokemon.get("types", [])
    )
    habitat = species.get("habitat") or {}
    text = (
        f"<b>{_escape(name)}</b> <code>#{pokemon['id']:04d}</code>\n"
        f"<b>Genus:</b> {_escape(genus)}\n"
        f"<b>Types:</b> {types}\n"
        f"<b>Abilities:</b> {abilities}\n"
        f"<b>Height:</b> {pokemon['height'] / 10:.1f} m\n"
        f"<b>Weight:</b> {pokemon['weight'] / 10:.1f} kg\n"
        f"<b>Base EXP:</b> {pokemon.get('base_experience') or 'Unknown'}\n"
        f"<b>Habitat:</b> {_escape(habitat.get('name', 'unknown'))}\n"
        f"<b>Gender:</b> {_gender_text(species)}\n\n"
        f"{_escape(flavor[:700])}\n\nData: PokéAPI"
    )
    return text, image


def _stats_text(pokemon: dict) -> str:
    lines = [f"<b>{_escape(_display_name(pokemon['name']))} base stats</b>"]
    total = 0
    for item in pokemon.get("stats", []):
        value = item.get("base_stat", 0)
        total += value
        label = _display_name(item.get("stat", {}).get("name", "unknown"))
        bar = "█" * math.ceil(value / 25)
        lines.append(f"<b>{_escape(label)}:</b> {value} <code>{bar}</code>")
    lines.append(f"\n<b>Total:</b> {total}")
    return "\n".join(lines)


def _moves_text(pokemon: dict, page: int) -> tuple[str, int]:
    moves = [_display_name(item["move"]["name"]) for item in pokemon.get("moves", [])]
    pages = max(1, math.ceil(len(moves) / MOVES_PER_PAGE))
    page = min(max(page, 0), pages - 1)
    selected = moves[page * MOVES_PER_PAGE : (page + 1) * MOVES_PER_PAGE]
    text = (
        f"<b>{_escape(_display_name(pokemon['name']))} moves</b> "
        f"({len(moves)} total)\n\n"
        + "\n".join(f"• {_escape(move)}" for move in selected)
    )
    return text, pages


async def _render(
    pokemon: dict, view: str, page: int = 0, pages: int = 1
) -> tuple[str, InlineKeyboardMarkup]:
    if view == "stats":
        text = _stats_text(pokemon)
    elif view == "moves":
        text, pages = _moves_text(pokemon, page)
    elif view == "evolution":
        _, evolution = await get_pokemon_details(pokemon)
        text = (
            f"<b>{_escape(_display_name(pokemon['name']))} evolution</b>\n\n"
            f"{_evolution_text(evolution) if evolution else 'No evolution data available.'}"
        )
    else:
        species, _ = await get_pokemon_details(pokemon)
        text, _ = _overview(pokemon, species)
    return text, _keyboard(pokemon["id"], view, page, pages)


async def pokedex(message: Message, command: CommandObject) -> None:
    if not command.args:
        await message.answer("Usage: <code>/pokedex &lt;name or ID&gt;</code>")
        return
    try:
        pokemon = await get_pokemon(" ".join(command.args))
        species, _ = await get_pokemon_details(pokemon)
        text, image = _overview(pokemon, species)
        if image:
            await message.answer_photo(photo=image, caption=text, parse_mode=ParseMode.HTML, reply_markup=_keyboard(pokemon["id"]))
        else:
            await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=_keyboard(pokemon["id"]))
    except HTTPError as error:
        if error.response.status_code == 404:
            await message.answer("Pokémon not found. Check the name or National Pokédex ID.")
        else:
            await message.answer("PokéAPI is unavailable. Please try again later.")
    except (ValueError, KeyError, TypeError):
        await message.answer("PokéAPI returned incomplete data. Please try again later.")


async def callback_query_handler(query: CallbackQuery) -> None:
    if not query.data.startswith(f"{CALLBACK_PREFIX}:"):
        return
    try:
        _, pokemon_id, view, page_text = query.data.split(":", 3)
        pokemon = await get_pokemon(int(pokemon_id))
        text, keyboard = await _render(pokemon, view, int(page_text))
        # A photo message is edited through its caption, a text one directly.
        if query.message.photo:
            await query.message.edit_caption(
                text, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        else:
            await query.message.edit_text(
                text, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        await query.answer()
    except HTTPError:
        await query.answer("PokéAPI is unavailable. Please try again later.", show_alert=True)
    except (ValueError, KeyError, TypeError):
        await query.answer("PokéAPI returned incomplete data.", show_alert=True)


# <================================================ HANDLER =======================================================>
# Add the command and callback query handlers to the dispatcher
dp.message.register(chain(pokedex), Command("pokedex"))
dp.callback_query.register(
    chain(callback_query_handler),
    F.data.regexp(rf"^{CALLBACK_PREFIX}:[0-9]+:(info|stats|moves|evolution):[0-9]+$"),
)

# <================================================ HANDLER =======================================================>
__help__ = """

🍥 <b>POKÉDEX</b>

➠ <b>Commands:</b>
» /pokedex &lt;name or ID&gt; — Pokémon overview, stats, moves, species data, and evolution chain
"""

__mod_name__ = "POKEDEX"
# <================================================ END =======================================================>
