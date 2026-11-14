# <============================================== IMPORTS =========================================================>
import html
import logging
import re
from re import sub

from pyrogram import enums
from pyrogram.parser.parser import Parser

LOGGER = logging.getLogger(__name__)

# <=======================================================================================================>

VALID_HTML_TAGS = re.compile(
    r"</?(?:b|strong|i|em|u|ins|s|del|strike|blockquote|code|pre|spoiler|tg-spoiler)(?:\s+[^>]*?)?>|"
    r'<span\s+class="[^"]*"\s*>|</span>|'
    r"<a\s+[^>]*?>|</a>|"
    r"<(?:emoji|tg-emoji)\s+[^>]*?>|</(?:emoji|tg-emoji)>|"
    r"<tg-time\s+[^>]*?>|</tg-time>",
    re.IGNORECASE,
)

V2_ESCAPED_CHARS = re.compile(r"\\([^a-zA-Z0-9\s])")


# <================================================ FUNCTIONS =======================================================>
def escape_markdown(text: str) -> str:
    """Escape markdown data."""
    escape_chars = r"\*_`\["
    return sub(r"([%s])" % escape_chars, r"\\\1", text)


def mention_html(user_id: int, name: str) -> str:
    """Mention user in html format. The name is escaped; callers pass it raw."""
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def mention_markdown(user_id: int, name: str) -> str:
    """Mention user in markdown format. Escapes the name; callers pass it raw."""
    return f"[{escape_markdown(name)}](tg://user?id={user_id})"


def smart_format_to_html(text: str) -> str:
    """Convert mixed Markdown (V1, V2, Kurigram) and HTML into clean Telegram HTML."""
    if not text:
        return text

    tokens: dict[str, str] = {}

    def protect(val: str) -> str:
        key = f"\x00tok_{len(tokens)}\x00"
        tokens[key] = val
        return key

    # 1. Protect code blocks (```lang\ncode```) and inline code (`code`)
    def protect_pre(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = m.group(2)
        if lang:
            return protect(
                f'<pre language="{html.escape(lang)}">{html.escape(code)}</pre>'
            )
        return protect(f"<pre>{html.escape(code)}</pre>")

    text = re.sub(r"```(?:([a-zA-Z0-9_+-]+)\n)?([\s\S]*?)```", protect_pre, text)
    text = re.sub(
        r"`([^`\n]+)`",
        lambda m: protect(f"<code>{html.escape(m.group(1))}</code>"),
        text,
    )

    # 2. Protect existing valid HTML tags
    text = VALID_HTML_TAGS.sub(lambda m: protect(m.group(0)), text)

    # 3. Protect backslash-escaped characters (V2 escapable chars)
    text = V2_ESCAPED_CHARS.sub(lambda m: protect(html.escape(m.group(1))), text)

    # 4. Handle Expandable Blockquotes (**> ... ||) and regular blockquotes (> ...)
    def parse_blockquotes(txt: str) -> str:
        lines = txt.split("\n")
        res_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("**>") and line.endswith("||"):
                inner = line[3:-2].strip()
                res_lines.append(
                    protect(f"<blockquote expandable>{html.escape(inner)}</blockquote>")
                )
                i += 1
            elif line.startswith(">"):
                q_lines = []
                while i < len(lines) and lines[i].startswith(">"):
                    q_lines.append(lines[i][1:].lstrip())
                    i += 1
                inner = "\n".join(q_lines)
                res_lines.append(
                    protect(f"<blockquote>{html.escape(inner)}</blockquote>")
                )
            else:
                res_lines.append(line)
                i += 1
        return "\n".join(res_lines)

    text = parse_blockquotes(text)

    # 5. Escape raw HTML chars (&, <, >) outside protected tokens
    text = html.escape(text)

    # 6. Custom Emoji: ![👍](tg://emoji?id=123)
    def parse_custom_emoji(m: re.Match) -> str:
        alt = m.group(1)
        emoji_id = m.group(2)
        return protect(f'<tg-emoji emoji-id="{emoji_id}">{alt}</tg-emoji>')

    text = re.sub(r"!\[(.*?)\]\(tg://emoji\?id=(\d+)\)", parse_custom_emoji, text)

    # 7. Markdown links: [text](url)
    def parse_md_link(m: re.Match) -> str:
        link_text = m.group(1)
        url = m.group(2)
        return protect(f'<a href="{html.escape(url, quote=True)}">{link_text}</a>')

    text = re.sub(
        r"\[([^\]]+)\]\(((?:https?://|tg://|mailto:)[^\s)]+)\)",
        parse_md_link,
        text,
    )

    # 8. Spoilers: ||spoiler|| (Markdown V2 & Kurigram)
    text = re.sub(
        r"\|\|(?=\S)(.+?)(?<=\S)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text, flags=re.S
    )

    # 9. Underline: __underline__ (Markdown V2) and --underline-- (Kurigram)
    text = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<u>\1</u>", text)
    text = re.sub(r"--(?=\S)(.+?)(?<=\S)--", r"<u>\1</u>", text)

    # 10. Bold: **bold** (Kurigram) and *bold* (Markdown V1/V2)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*\n\s][^*\n]*?[^*\n\s]|\S)\*(?!\*)", r"<b>\1</b>", text)

    # 11. Italic: _italic_ (Markdown V1/V2)
    text = re.sub(
        r"(?<![a-zA-Z0-9_])_([^_\n\s][^_\n]*?[^_\n\s]|\S)_(?![a-zA-Z0-9_])",
        r"<i>\1</i>",
        text,
    )

    # 12. Strikethrough: ~~strike~~ (Kurigram/Markdown V2) and ~strike~ (Markdown V2)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<s>\1</s>", text)
    text = re.sub(r"(?<!~)~([^~\n\s][^~\n]*?[^~\n\s]|\S)~(?!~)", r"<s>\1</s>", text)

    # 13. Restore tokens
    for key, val in tokens.items():
        text = text.replace(key, val)

    return text


class SmartParser(Parser):
    """Kurigram Parser extension supporting Markdown V1, V2, and HTML simultaneously."""

    async def parse(self, text: str, mode: enums.ParseMode | None = None) -> dict:
        text = str(text or "").strip()
        if not text:
            return {"message": "", "entities": None}

        if mode is None:
            if self.client:
                mode = getattr(self.client, "parse_mode", enums.ParseMode.DEFAULT)
            else:
                mode = enums.ParseMode.DEFAULT

        if mode == enums.ParseMode.DISABLED:
            return {"message": text, "entities": None}

        formatted = smart_format_to_html(text)
        return await self.html.parse(formatted)


def install_smart_parser(client=None) -> None:
    """Globally install SmartParser in Kurigram."""

    async def _smart_parse(
        self: Parser, text: str, mode: enums.ParseMode | None = None
    ) -> dict:
        text = str(text or "").strip()
        if not text:
            return {"message": "", "entities": None}

        if mode is None:
            if self.client:
                mode = getattr(self.client, "parse_mode", enums.ParseMode.DEFAULT)
            else:
                mode = enums.ParseMode.DEFAULT

        if mode == enums.ParseMode.DISABLED:
            return {"message": text, "entities": None}

        formatted = smart_format_to_html(text)
        return await self.html.parse(formatted)

    Parser.parse = _smart_parse

    if client is not None:
        client.parser = SmartParser(client)


# <================================================ END =======================================================>
