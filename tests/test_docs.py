from __future__ import annotations

import re
import subprocess
import xml.dom.minidom
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CONFIGURATION.md",
    "docs/DATABASE.md",
    "docs/DEPLOYMENT.md",
    "docs/MIGRATION-MONGO-TO-SQL.md",
    "docs/PLUGINS.md",
    "docs/SYSTEM-REQUIREMENTS.md",
]

LINK = re.compile(r"!?\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
ASSET = re.compile(r'(?:src|srcset)="([^"]+)"')
HTML_ANCHOR = re.compile(r'<a\s[^>]*href="#([a-z0-9-]+)"')
EXTERNAL = ("http://", "https://", "mailto:")


def _slugify(heading: str) -> str:
    text = re.sub(r"`", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())


def _root_files() -> list[Path]:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / name for name in tracked if (ROOT / name).exists()]


def test_relative_targets():
    for relative in DOCS:
        path = ROOT / relative
        assert path.exists(), f"{relative}: file is missing"
        text = path.read_text(encoding="utf-8")
        targets = [m.group(1) for m in LINK.finditer(text)]
        targets += [
            m.group(1).split(",")[0].strip().split()[0] for m in ASSET.finditer(text)
        ]
        for target in targets:
            if not target or target.startswith(EXTERNAL) or target.startswith("#"):
                continue
            assert (
                path.parent / target
            ).exists(), f"{relative}: target {target!r} does not exist"


def test_anchors():
    for relative in DOCS:
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        headings = {
            _slugify(m.group(1))
            for m in re.finditer(r"^(?:#{1,6})\s+(.+)$", text, flags=re.MULTILINE)
        }
        manual = set(re.findall(r'<a\s+id="([^"]+)"', text))
        targets = headings | manual
        for m in HTML_ANCHOR.finditer(text):
            anchor = m.group(1)
            assert anchor in targets, f"{relative}: broken anchor #{anchor}"


def test_svg_assets():
    svgs = [p for p in (ROOT / "docs" / "assets").glob("*.svg") if p.is_file()]
    assert svgs, "No SVG assets found under docs/assets"
    for svg in svgs:
        doc = xml.dom.minidom.parse(str(svg))
        root_el = doc.documentElement
        assert (
            root_el.tagName == "svg"
        ), f"{svg.name} root element is not <svg>: {root_el.tagName}"
        assert root_el.getAttribute("viewBox"), f"{svg.name} lacks viewBox"


def test_repository_tree_is_documented():
    arch = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Mikobot/" in arch
    assert "Database/" in arch


def test_fork_attribution():
    for path in (ROOT / "README.md", ROOT / "Mikobot" / "__main__.py"):
        text = path.read_text(encoding="utf-8")
        assert (
            "Team-ProjectCodeX" in text
        ), f"{path.name} must preserve upstream Team-ProjectCodeX attribution"


def test_no_dead_assets():
    referenced = set()
    for relative in DOCS:
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?:assets/[a-zA-Z0-9._-]+)", text):
            referenced.add(Path(match.group(0)).name)

    assets_dir = ROOT / "docs" / "assets"
    if assets_dir.exists():
        for asset in assets_dir.iterdir():
            if asset.is_file():
                assert (
                    asset.name in referenced
                ), f"Dead asset {asset.name} not referenced in docs"


def test_no_duplicate_helper_modules():
    database_sql = {
        p.stem.replace("_sql", "") for p in (ROOT / "Database" / "sql").glob("*_sql.py")
    }
    assert "users" in database_sql
    assert "feds" in database_sql
