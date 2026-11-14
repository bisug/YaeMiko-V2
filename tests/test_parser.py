from __future__ import annotations

import pytest
from pyrogram import enums, raw
from pyrogram.parser.parser import Parser

from Mikobot import app
from Mikobot.plugins.helper_funcs.string_handling import markdown_to_html
from Mikobot.utils.parser import (
    SmartParser,
    escape_markdown,
    mention_html,
    mention_markdown,
    smart_format_to_html,
)


def test_escape_and_mentions():
    assert escape_markdown("hello_world*") == r"hello\_world\*"
    assert (
        mention_html(12345, "User<>&")
        == '<a href="tg://user?id=12345">User&lt;&gt;&amp;</a>'
    )
    assert mention_markdown(12345, "User*") == r"[User\*](tg://user?id=12345)"


def test_smart_format_markdown_v1_and_v2():
    # Bold
    assert smart_format_to_html("*single bold*") == "<b>single bold</b>"
    assert smart_format_to_html("**double bold**") == "<b>double bold</b>"

    # Italic
    assert smart_format_to_html("_single italic_") == "<i>single italic</i>"
    assert (
        smart_format_to_html("identifier_with_underscores")
        == "identifier_with_underscores"
    )

    # Underline
    assert smart_format_to_html("__v2 underline__") == "<u>v2 underline</u>"
    assert smart_format_to_html("--kurigram underline--") == "<u>kurigram underline</u>"

    # Strikethrough
    assert smart_format_to_html("~v2 strike~") == "<s>v2 strike</s>"
    assert smart_format_to_html("~~double strike~~") == "<s>double strike</s>"

    # Spoilers
    assert smart_format_to_html("||secret||") == "<tg-spoiler>secret</tg-spoiler>"


def test_smart_format_blockquotes():
    quote = "> Line 1\n> Line 2"
    assert smart_format_to_html(quote) == "<blockquote>Line 1\nLine 2</blockquote>"

    expandable = "**> Expandable quote ||"
    assert (
        smart_format_to_html(expandable)
        == "<blockquote expandable>Expandable quote</blockquote>"
    )


def test_smart_format_code_and_pre():
    # Asterisks and tags inside inline code must be preserved verbatim
    inline = "`*not bold* and <b>not html</b>`"
    assert (
        smart_format_to_html(inline)
        == "<code>*not bold* and &lt;b&gt;not html&lt;/b&gt;</code>"
    )

    # Pre blocks with and without language
    pre = "```python\nprint('hello')\n*stars*\n```"
    expected = '<pre language="python">print(&#x27;hello&#x27;)\n*stars*\n</pre>'
    assert smart_format_to_html(pre) == expected


def test_smart_format_escaped_characters():
    escaped = r"Not \*bold\* and not \_italic\_, price \$5\.00\! 1\+1\=2"
    assert (
        smart_format_to_html(escaped)
        == "Not *bold* and not _italic_, price $5.00! 1+1=2"
    )


def test_smart_format_brackets_and_comparisons():
    # Bare brackets and comparisons should never be swallowed or deleted
    cmd = "Usage: /ban <user_id> [time]"
    assert smart_format_to_html(cmd) == "Usage: /ban &lt;user_id&gt; [time]"

    math = "Compare: 5 < 10 & 20 > 15"
    assert smart_format_to_html(math) == "Compare: 5 &lt; 10 &amp; 20 &gt; 15"


def test_smart_format_links_and_mentions():
    link = "[Telegram](https://telegram.org)"
    assert smart_format_to_html(link) == '<a href="https://telegram.org">Telegram</a>'

    mention = "[Alice](tg://user?id=12345678)"
    assert smart_format_to_html(mention) == '<a href="tg://user?id=12345678">Alice</a>'

    custom_emoji = "![👍](tg://emoji?id=5368324170671202286)"
    assert (
        smart_format_to_html(custom_emoji)
        == '<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji>'
    )


def test_smart_format_mixed_html_and_markdown():
    mixed = '<b>HTML Bold</b> and *MD Bold* with <a href="https://t.me">link</a>'
    assert (
        smart_format_to_html(mixed)
        == '<b>HTML Bold</b> and <b>MD Bold</b> with <a href="https://t.me">link</a>'
    )


def test_markdown_to_html_helper():
    text = "*bold* and _italic_ and `code`"
    assert (
        markdown_to_html(text) == "<b>bold</b> and <i>italic</i> and <code>code</code>"
    )


@pytest.mark.asyncio
async def test_smart_parser_entities():
    parser = SmartParser(None)

    # Empty text
    empty_res = await parser.parse("")
    assert empty_res["message"] == ""
    assert empty_res["entities"] is None

    # ParseMode.DISABLED returns plain text unchanged without entities
    disabled_res = await parser.parse("*raw text*", enums.ParseMode.DISABLED)
    assert disabled_res["message"] == "*raw text*"
    assert disabled_res["entities"] is None

    # Markdown V1 single bold
    bold_res = await parser.parse("*bold text*", enums.ParseMode.MARKDOWN)
    assert bold_res["message"] == "bold text"
    assert len(bold_res["entities"]) == 1
    assert isinstance(bold_res["entities"][0], raw.types.MessageEntityBold)

    # Markdown V2 underline and spoiler
    v2_res = await parser.parse(
        "__underline__ and ||spoiler||", enums.ParseMode.DEFAULT
    )
    assert v2_res["message"] == "underline and spoiler"
    assert len(v2_res["entities"]) == 2
    assert isinstance(v2_res["entities"][0], raw.types.MessageEntityUnderline)
    assert isinstance(v2_res["entities"][1], raw.types.MessageEntitySpoiler)

    # User mention via tg://user?id=
    mention_res = await parser.parse("[Bob](tg://user?id=987654)", enums.ParseMode.HTML)
    assert mention_res["message"] == "Bob"
    assert len(mention_res["entities"]) == 1
    assert isinstance(
        mention_res["entities"][0], raw.types.InputMessageEntityMentionName
    )
    assert mention_res["entities"][0].user_id == 987654


@pytest.mark.asyncio
async def test_app_client_parser_hook():
    # app.parser must be hooked to SmartParser
    assert isinstance(app.parser, SmartParser)

    # Any Client instance Parser.parse call uses smart parsing
    p = Parser(None)
    res = await p.parse("*bold from p.parse*")
    assert res["message"] == "bold from p.parse"
    assert len(res["entities"]) == 1
    assert isinstance(res["entities"][0], raw.types.MessageEntityBold)
