from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest

from Mikobot.plugins import genshin


def test_rarity_stars():
    assert genshin._rarity_stars(5) == "⭐⭐⭐⭐⭐"
    assert genshin._rarity_stars("4") == "⭐⭐⭐⭐"
    assert genshin._rarity_stars(0) == ""
    assert genshin._rarity_stars("abc") == ""


def test_format_birthday():
    assert genshin._format_birthday("0000-09-13") == "09-13"
    assert genshin._format_birthday("09-13") == "09-13"
    assert genshin._format_birthday(None) is None


def test_match_slugs_and_names():
    entries = [
        {"key": "hu-tao", "name": "Hu Tao"},
        {"key": "albedo", "name": "Albedo"},
        {"key": "alhaitham", "name": "Alhaitham"},
    ]
    # Exact match
    res = genshin._match(entries, "albedo")
    assert len(res) == 1
    assert res[0]["key"] == "albedo"

    # Space-less match
    res = genshin._match(entries, "hutao")
    assert len(res) == 1
    assert res[0]["key"] == "hu-tao"

    # Partial prefix match
    res = genshin._match(entries, "al")
    assert len(res) == 2
    assert {r["key"] for r in res} == {"albedo", "alhaitham"}


def test_image_url_extraction():
    # Character with dict images
    char_entry = {
        "key": "albedo",
        "img": {
            "portrait": "https://pub-1ad.r2.dev/albedo/portrait.png",
            "icon": "https://pub-1ad.r2.dev/albedo/icon.png",
        },
    }
    assert (
        genshin._image_url(char_entry, "characters")
        == "https://pub-1ad.r2.dev/albedo/portrait.png"
    )

    # Material with direct string url
    mat_entry = {
        "key": "cecilia",
        "img": "https://pub-1ad.r2.dev/materials/cecilia/icon.png",
    }
    assert (
        genshin._image_url(mat_entry, "materials")
        == "https://pub-1ad.r2.dev/materials/cecilia/icon.png"
    )

    # Artifact with pieces dict
    art_entry = {
        "key": "emblem",
        "pieces": {
            "flower": {"img": "https://pub-1ad.r2.dev/artifacts/emblem/flower.png"}
        },
    }
    assert (
        genshin._image_url(art_entry, "artifacts")
        == "https://pub-1ad.r2.dev/artifacts/emblem/flower.png"
    )


def test_render_character():
    payload = {
        "name": "Albedo",
        "title": "Kreideprinz",
        "vision": "Geo",
        "weapon": "Sword",
        "nation": "Mondstadt",
        "rarity": 5,
        "birthday": "0000-09-13",
        "description": "Chief Alchemist",
        "skillTalents": [
            {
                "name": "Solar Isotoma",
                "unlock": "Elemental Skill",
                "description": "Deals Geo DMG",
            }
        ],
        "ascension_costs": [
            {
                "phase": 1,
                "max_level": 40,
                "mora": 20000,
                "materials": [
                    {"slug": "cecilia", "quantity": 3},
                ],
            }
        ],
        "img": {"portrait": "https://pub-1ad.r2.dev/albedo/portrait.png"},
    }

    # Bio tab
    blocks, markup = genshin._render_character(payload, "bio")
    assert blocks
    assert markup

    # Talents tab
    blocks, _ = genshin._render_character(payload, "talents")
    assert any("Solar Isotoma" in str(getattr(b, "text", "")) or "Combat Talents" in str(getattr(b, "text", "")) for b in blocks)

    # Ascend tab
    blocks, _ = genshin._render_character(payload, "ascend")
    assert any("Cecilia x3" in str(getattr(b, "text", "")) or "Mora x20,000" in str(getattr(b, "text", "")) for b in blocks)


def test_render_weapon():
    payload = {
        "name": "Staff of Homa",
        "type": "Polearm",
        "rarity": 5,
        "base_atk": 45.9,
        "sub_stat": "CRIT DMG",
        "passive_name": "Reckless Cinnabar",
        "passive_desc": "HP increased by 20%.",
        "img": {"icon": "https://pub-1ad.r2.dev/weapons/staff-of-homa/icon.png"},
    }
    blocks = genshin._render_weapon(payload)
    assert blocks


def test_render_artifact():
    payload = {
        "name": "Emblem of Severed Fate",
        "rarity": 5,
        "bonus": {"2pc": "Energy Recharge +20%", "4pc": "Burst DMG up"},
        "pieces": {"flower": {"img": "https://pub-1ad.r2.dev/flower.png"}},
    }
    blocks = genshin._render_artifact(payload)
    assert blocks


def test_render_grouped_material():
    payload = {
        "name": "Cecilia",
        "rarity": 1,
        "category": "local-specialty",
        "region": "Mondstadt",
        "description": "A beautiful flower.",
        "used_by": {"characters": ["albedo", "venti"]},
        "img": "https://pub-1ad.r2.dev/cecilia.png",
    }
    blocks = genshin._render_grouped(payload, "materials")
    assert blocks


@pytest.mark.asyncio
async def test_fetch_roster_parsing():
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "characters": [
            {"key": "albedo", "name": "Albedo", "rarity": 5},
            {"key": "amber", "name": "Amber", "rarity": 4},
        ]
    }

    with patch.object(genshin.state, "get", new=AsyncMock(return_value=mock_resp)):
        records = await genshin._fetch_roster("characters")
        assert len(records) == 2
        assert records[0]["id"] == "albedo"
        assert records[0]["key"] == "albedo"
