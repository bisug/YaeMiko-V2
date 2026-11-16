from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.errors import MessageNotModified

from Mikobot.plugins import pokedex


def test_display_name():
    assert pokedex._display_name("pikachu") == "Pikachu"
    assert pokedex._display_name("ho-oh") == "Ho Oh"
    assert pokedex._display_name("iron-treads") == "Iron Treads"


def test_escape():
    assert pokedex._escape("<test>&") == "&lt;test&gt;&amp;"
    assert pokedex._escape(None) == ""


def test_evolution_text():
    chain = {
        "chain": {
            "species": {"name": "pichu"},
            "evolves_to": [
                {
                    "species": {"name": "pikachu"},
                    "evolves_to": [{"species": {"name": "raichu"}, "evolves_to": []}],
                }
            ],
        }
    }
    res = pokedex._evolution_text(chain)
    assert res == "Pichu → Pikachu → Raichu"

    assert pokedex._evolution_text({}) == "No evolution data available."


def test_keyboard_layout():
    # Overview tab active
    kb_info = pokedex._keyboard(25, "info")
    buttons_info = kb_info.inline_keyboard
    assert buttons_info[0][0].text == "• Overview •"
    assert buttons_info[0][1].text == "Stats"
    assert buttons_info[0][0].callback_data == "pk:25:info:0"
    assert buttons_info[0][1].callback_data == "pk:25:stats:0"

    # Stats tab active
    kb_stats = pokedex._keyboard(25, "stats")
    buttons_stats = kb_stats.inline_keyboard
    assert buttons_stats[0][0].text == "Overview"
    assert buttons_stats[0][1].text == "• Stats •"

    # Moves pagination
    kb_moves = pokedex._keyboard(25, "moves", page=1, pages=3)
    rows_moves = kb_moves.inline_keyboard
    assert len(rows_moves) == 2
    # Prev, Page, Next
    assert len(rows_moves[0]) == 3
    assert rows_moves[0][0].text == "⬅️ Previous"
    assert rows_moves[0][0].callback_data == "pk:25:moves:0"
    assert rows_moves[0][1].text == "Page 2/3"
    assert rows_moves[0][2].text == "Next ➡️"
    assert rows_moves[0][2].callback_data == "pk:25:moves:2"
    # Back to overview button
    assert rows_moves[1][0].text == "« Back to Overview"
    assert rows_moves[1][0].callback_data == "pk:25:info:0"


def test_stats_text():
    sample_pokemon = {
        "name": "pikachu",
        "stats": [
            {"base_stat": 35, "stat": {"name": "hp"}},
            {"base_stat": 55, "stat": {"name": "attack"}},
        ],
    }
    txt = pokedex._stats_text(sample_pokemon)
    assert "Pikachu base stats" in txt
    assert "Hp:" in txt
    assert "Attack:" in txt
    assert "<b>Total:</b> 90" in txt


def test_moves_text():
    sample_pokemon = {
        "name": "pikachu",
        "moves": [{"move": {"name": f"move-{i}"}} for i in range(25)],
    }
    # Page 0 should have 20 moves
    txt, pages = pokedex._moves_text(sample_pokemon, 0)
    assert pages == 2
    assert "Move 0" in txt
    assert "Move 19" in txt
    assert "Move 20" not in txt

    # Page 1 should have remaining 5 moves
    txt, pages = pokedex._moves_text(sample_pokemon, 1)
    assert pages == 2
    assert "Move 20" in txt
    assert "Move 24" in txt


@pytest.mark.asyncio
async def test_pokemon_caching():
    pokedex._POKEMON_CACHE.clear()
    mock_data = {"id": 25, "name": "pikachu"}

    with patch.object(
        pokedex, "_get_json", new=AsyncMock(return_value=mock_data)
    ) as mock_get:
        p1 = await pokedex.get_pokemon("pikachu")
        assert p1["id"] == 25
        assert mock_get.call_count == 1

        # Second call with id or name should hit cache
        p2 = await pokedex.get_pokemon(25)
        assert p2["name"] == "pikachu"
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_callback_handles_message_not_modified():
    query = MagicMock()
    query.data = "pk:25:info:0"
    query.message = MagicMock()
    query.message.photo = MagicMock()
    query.message.edit_caption = AsyncMock(side_effect=MessageNotModified)
    query.answer = AsyncMock()

    sample_pokemon = {
        "id": 25,
        "name": "pikachu",
        "height": 4,
        "weight": 60,
        "species": {"url": "https://pokeapi.co/api/v2/pokemon-species/25/"},
    }
    sample_species = {
        "genera": [{"language": {"name": "en"}, "genus": "Mouse Pokémon"}],
        "flavor_text_entries": [
            {"language": {"name": "en"}, "flavor_text": "When it smashes its cheeks..."}
        ],
    }

    with (
        patch.object(
            pokedex, "get_pokemon", new=AsyncMock(return_value=sample_pokemon)
        ),
        patch.object(
            pokedex,
            "get_pokemon_details",
            new=AsyncMock(return_value=(sample_species, None)),
        ),
    ):
        # Should not raise MessageNotModified
        await pokedex.callback_query_handler(MagicMock(), query)
        query.message.edit_caption.assert_awaited_once()
        query.answer.assert_awaited_once()
