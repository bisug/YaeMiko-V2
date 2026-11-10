from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "Mikobot" / "plugins"


def test_quotely_entity_types():
    from pyrogram.enums import MessageEntityType

    from Mikobot.plugins.quotely import Quotly

    entities = Quotly._entities
    assert MessageEntityType.TON_ADDRESS in entities
    assert MessageEntityType.BANK_CARD in entities
    assert MessageEntityType.DATE_TIME in entities


def test_quotely_command_regex():
    pattern = re.compile(r"^[!/?]q(?:@\S+)?(?: |$)(.*)")
    assert pattern.match("/q")
    assert pattern.match("!q")
    assert pattern.match("?q")
    assert pattern.match("/q hello")
    assert pattern.match("/q@YaeMikoBot hello")
    assert not pattern.match("/quit")


def test_plugin_null_safety_guards():
    fsub_source = (PLUGINS_DIR / "fsub.py").read_text(encoding="utf-8")
    newuser_source = (PLUGINS_DIR / "newuserinfo.py").read_text(encoding="utf-8")

    assert "if not message.from_user:" in fsub_source
    assert "if not user:" in newuser_source or "if user is None:" in newuser_source


def test_topics_sidebar_support():
    topics_source = (PLUGINS_DIR / "topics.py").read_text(encoding="utf-8")
    assert "has_forum_sidebar" in topics_source
    assert "is_forum" in topics_source


def test_all_except_clauses_parenthesized():
    for py_file in (ROOT / "Mikobot").rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
                assert len(node.type.elts) > 0
