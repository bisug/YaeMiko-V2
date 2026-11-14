"""Leftover check for the aiogram to kurigram port.

Prints every place that still looks like aiogram. Run it after the port to
see what is left:

    python scripts/audit_port.py
"""

import re
import sys
from pathlib import Path

CHECKS = {
    "aiogram import": re.compile(r"^\s*(from|import)\s+aiogram"),
    "dp usage": re.compile(r"\bdp\.\w+\.register"),
    "bot usage": re.compile(r"\bbot\.\w+\("),
    "CommandObject": re.compile(r"\bCommandObject\b"),
    "magic filter": re.compile(r"\bF\.\w"),
    "aiogram error": re.compile(r"\bTelegram\w*Error\b"),
    "chat type string": re.compile(
        r"\.type\s*(==|!=)\s*[\"'](private|group|supergroup|channel)[\"']"
    ),
    "photo list": re.compile(r"\.photo\s*\["),
    "chat member flags": re.compile(r"member\.can_\w+"),
    "aiogram chat": re.compile(r"chat\.get_(member|administrators)\("),
}


def main() -> None:
    roots = sys.argv[1:] or ["Mikobot", "Infamous", "Database"]
    findings = 0
    for root in roots:
        for path in sorted(Path(root).rglob("*.py")):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                for label, pattern in CHECKS.items():
                    if pattern.search(line):
                        print(f"{path}:{number}: {label}: {line.strip()}")
                        findings += 1
    print(f"\n{findings} leftovers")


if __name__ == "__main__":
    main()
