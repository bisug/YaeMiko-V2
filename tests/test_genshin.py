from __future__ import annotations

from unittest.mock import AsyncMock, patch

from Mikobot.plugins import genshin

IMG = "https://pub-1ad.r2.dev"


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
            "portrait": f"{IMG}/albedo/portrait.png",
            "icon": f"{IMG}/albedo/icon.png",
        },
    }
    assert genshin._image_url(char_entry, "characters") == f"{IMG}/albedo/portrait.png"

    # Material with direct string url
    mat_entry = {
        "key": "cecilia",
        "img": f"{IMG}/materials/cecilia/icon.png",
    }
    assert (
        genshin._image_url(mat_entry, "materials")
        == f"{IMG}/materials/cecilia/icon.png"
    )

    # Artifact with pieces dict
    art_entry = {
        "key": "emblem",
        "pieces": {"flower": {"img": f"{IMG}/artifacts/emblem/flower.png"}},
    }
    assert (
        genshin._image_url(art_entry, "artifacts")
        == f"{IMG}/artifacts/emblem/flower.png"
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
        "img": {"portrait": f"{IMG}/albedo/portrait.png"},
    }

    # Bio tab
    text, markup, img_url = genshin._render_character(payload, "bio")
    assert "Albedo" in text
    assert "Kreideprinz" in text
    assert "Geo" in text
    assert markup
    assert img_url == f"{IMG}/albedo/portrait.png"

    # Talents tab
    text, _, _ = genshin._render_character(payload, "talents")
    assert "Solar Isotoma" in text
    assert "Combat Talents" in text

    # Ascend tab
    text, _, _ = genshin._render_character(payload, "ascend")
    assert "Cecilia x3" in text
    assert "20,000" in text


def test_render_weapon():
    payload = {
        "name": "Staff of Homa",
        "type": "Polearm",
        "rarity": 5,
        "base_atk": 45.9,
        "sub_stat": "CRIT DMG",
        "passive_name": "Reckless Cinnabar",
        "passive_desc": "HP increased by 20%.",
        "img": {"icon": f"{IMG}/weapons/staff-of-homa/icon.png"},
    }
    text, markup, img_url = genshin._render_weapon(payload)
    assert "Staff of Homa" in text
    assert "Reckless Cinnabar" in text
    assert markup
    assert img_url


def test_render_artifact():
    payload = {
        "name": "Emblem of Severed Fate",
        "rarity": 5,
        "bonus": {"2pc": "Energy Recharge +20%", "4pc": "Burst DMG up"},
        "pieces": {"flower": {"img": f"{IMG}/flower.png"}},
    }
    text, markup, img_url = genshin._render_artifact(payload)
    assert "Emblem of Severed Fate" in text
    assert "Energy Recharge +20%" in text
    assert markup
    assert img_url


def test_render_material():
    payload = {
        "name": "Cecilia",
        "rarity": 1,
        "category": "local-specialty",
        "region": "Mondstadt",
        "description": "A beautiful flower.",
        "used_by": {"characters": ["albedo", "venti"]},
        "img": f"{IMG}/cecilia.png",
    }
    text, markup, img_url = genshin._render_material(payload)
    assert "Cecilia" in text
    assert "Albedo" in text
    assert markup
    assert img_url


def test_render_enemy():
    payload = {
        "name": "Hilichurl",
        "type": "Common Monsters",
        "drops": [{"name": "Damaged Mask", "rarity": 1}],
        "img": f"{IMG}/hilichurl.png",
    }
    text, markup, img_url = genshin._render_enemy(payload)
    assert "Hilichurl" in text
    assert "Damaged Mask" in text
    assert markup


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
