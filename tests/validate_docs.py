"""Validate the documentation.

Runs as a script from CI and is imported by tests/test_regressions.py, so the
same checks cover both gates. No third party dependency: the XML parse uses
the standard library, and links are checked on disk rather than over the
network, so this works offline and in a sandbox.
"""

import ast
import re
import subprocess
import sys
import xml.dom.minidom
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/CONFIGURATION.md",
    "docs/DEPLOYMENT.md",
    "docs/PLUGINS.md",
    "docs/SYSTEM-REQUIREMENTS.md",
]

LINK = re.compile(r"!?\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
ASSET = re.compile(r'(?:src|srcset)="([^"]+)"')
HTML_ANCHOR = re.compile(r'<a\s[^>]*href="#([a-z0-9-]+)"')
EXTERNAL = ("http://", "https://", "mailto:")


def _slugify(heading):
    """Match the GitHub anchor algorithm closely enough for local headings."""
    text = re.sub(r"`", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^a-z0-9\s-]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())


def root_files():
    """Every tracked text file, excluding caches and the Git directory."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    return [ROOT / name for name in tracked]


def check_relative_targets(errors):
    """Every relative link and image target must exist on disk."""
    for relative in DOCS:
        path = ROOT / relative
        if not path.exists():
            errors.append(f"{relative}: file is missing")
            continue
        text = path.read_text(encoding="utf-8")
        targets = [m.group(1) for m in LINK.finditer(text)]
        targets += [
            m.group(1).split(",")[0].strip().split()[0] for m in ASSET.finditer(text)
        ]
        for target in targets:
            if not target or target.startswith(EXTERNAL) or target.startswith("#"):
                continue
            if not (path.parent / target).exists():
                errors.append(f"{relative}: target {target!r} does not exist")


def check_anchors(errors):
    """Every in-page anchor must match a heading in the same file.

    Both Markdown links and raw HTML anchors are checked, because the README
    navigation bar is built from <a href="#..."> tags.
    """
    for relative in DOCS:
        path = ROOT / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        anchors = set(re.findall(r"\]\(#([a-z0-9-]+)\)", text))
        anchors |= set(HTML_ANCHOR.findall(text))
        headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
        available = {_slugify(heading) for heading in headings}
        for anchor in sorted(anchors - available):
            errors.append(f"{relative}: anchor #{anchor} has no matching heading")


def check_svg_assets(errors):
    """Every SVG must be well formed XML, or GitHub renders nothing."""
    for svg in sorted(ROOT.glob("docs/assets/*.svg")):
        try:
            xml.dom.minidom.parse(str(svg))
        except Exception as exc:  # noqa: BLE001, reported as a gate failure
            errors.append(f"{svg.relative_to(ROOT)}: invalid XML, {exc}")


def check_repository_tree_is_documented(errors):
    """The README layout block must list every docs page and every blueprint."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    expected = [
        "docs/ARCHITECTURE.md",
        "docs/CONFIGURATION.md",
        "docs/DEPLOYMENT.md",
        "docs/PLUGINS.md",
        "docs/SYSTEM-REQUIREMENTS.md",
        "app.json",
        "render.yaml",
        "railway.json",
        "Dockerfile",
        "heroku.yml",
        "Procfile",
    ]
    for name in expected:
        if name not in readme:
            errors.append(f"README.md: {name} is not mentioned in the layout block")


def check_fork_attribution(errors):
    """The fork notice and the upstream link must survive link rewrites."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "forked from" not in readme.lower():
        errors.append("README.md: the maintained fork notice is missing")
    if "github.com/Infamous-Hydra/YaeMiko" not in readme:
        errors.append("README.md: upstream Infamous-Hydra/YaeMiko must stay credited")
    for relative in ("app.json", "Mikobot/__init__.py", "Mikobot/__main__.py"):
        if "bisug/YaeMiko-V2" not in (ROOT / relative).read_text(encoding="utf-8"):
            errors.append(f"{relative}: repository link should point at bisug/YaeMiko-V2")


def check_no_dead_assets(errors):
    """Every tracked binary asset must be referenced by code or documentation.

    A font or image that nothing loads is dead weight in every clone and in
    the container image, so the reference check runs in CI.
    """
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    assets = [
        name
        for name in tracked
        if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".ttf", ".webp"}
    ]
    haystack = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in root_files()
        if path.suffix in {".py", ".md", ".yml", ".yaml", ".json", ".txt"}
    )
    for asset in assets:
        name = Path(asset).name
        # Match the filename on a non word boundary, otherwise a short name
        # would also match the tail of a longer URL path in a Telegraph link.
        pattern = re.compile(rf"(?:^|[^\w.]){re.escape(name)}(?:$|[^\w])", re.MULTILINE)
        if not pattern.search(haystack):
            errors.append(
                f"{asset}: binary asset is never referenced, it is dead weight in every clone"
            )


def check_no_duplicate_helper_modules(errors):
    """A helper module must not duplicate another module's public functions."""
    signatures = {}
    for path in sorted((ROOT / "Mikobot/utils").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signatures.setdefault(node.name, []).append(path.relative_to(ROOT).as_posix())
    for name, owners in sorted(signatures.items()):
        if len(owners) > 1:
            errors.append(
                f"duplicate helper {name!r} defined in {', '.join(sorted(owners))}"
            )


def main():
    errors = []
    checks = (
        check_relative_targets,
        check_anchors,
        check_svg_assets,
        check_repository_tree_is_documented,
        check_fork_attribution,
        check_no_dead_assets,
        check_no_duplicate_helper_modules,
    )
    for check in checks:
        check(errors)
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print(f"documentation ok ({len(DOCS)} pages, {len(list(ROOT.glob('docs/assets/*.svg')))} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
