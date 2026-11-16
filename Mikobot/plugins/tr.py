import asyncio

from emoji import EMOJI_DATA
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions, Message

from Mikobot.events import on_message
from Mikobot.plugins.anime import (
    LANGUAGES,
    google_translator,
)
from Mikobot.plugins.disable import disableable
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.filters import GROUPS


@on_message(GROUPS, *disableable("echo"), chained=True)
@check_admin(is_user=True)
async def echo(client, message: Message):
    args = (message.text or "").split(None, 1)

    if len(args) < 2:
        return

    if message.reply_to_message:
        await message.reply_to_message.reply_text(
            args[1],
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    else:
        await message.reply_text(
            args[1],
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    await message.delete()


@on_message(*disableable(["tr", "tl"]), chained=True)
async def totranslate(client, message: Message):
    problem_lang_code = []
    for key in LANGUAGES:
        if "-" in key:
            problem_lang_code.append(key)

    try:
        if (
            message.reply_to_message
            and not message.reply_to_message.forum_topic_created
        ):
            args = (message.text or "").split(None, 1)
            if message.reply_to_message.text:
                text = message.reply_to_message.text
            elif message.reply_to_message.caption:
                text = message.reply_to_message.caption
            else:
                # Photo/sticker replies carry neither, which left text unbound
                # and raised NameError.
                await message.reply_text(
                    "There is no text in the message you replied to."
                )
                return

            try:
                source_lang = args[1].split(None, 1)[0]
            except IndexError, AttributeError:
                source_lang = "en"

        else:
            args = (message.text or "").split(None, 2)
            text = args[2]
            source_lang = args[1]

        if source_lang.count("-") == 2:
            for lang in problem_lang_code:
                if lang in source_lang:
                    if source_lang.startswith(lang):
                        dest_lang = source_lang.rsplit("-", 1)[1]
                        source_lang = source_lang.rsplit("-", 1)[0]
                    else:
                        dest_lang = source_lang.split("-", 1)[1]
                        source_lang = source_lang.split("-", 1)[0]
        elif source_lang.count("-") == 1:
            # Without this default, a one-dash locale with no table match
            # (e.g. "de-at") left dest_lang unbound.
            dest_lang = None
            for lang in problem_lang_code:
                if lang in source_lang:
                    dest_lang = source_lang
                    source_lang = None
                    break
            if dest_lang is None:
                dest_lang = source_lang.split("-")[1]
                source_lang = source_lang.split("-")[0]
        else:
            dest_lang = source_lang
            source_lang = None

        exclude_list = EMOJI_DATA.keys()
        for emoji in exclude_list:
            if emoji in text:
                text = text.replace(emoji, "")

        trl = google_translator()
        if source_lang is None:
            detection = await asyncio.to_thread(trl.detect, text)
            trans_str = await asyncio.to_thread(trl.translate, text, lang_tgt=dest_lang)
            return await message.reply_text(
                f"📒 *Translated from* `{detection[0]}` to `{dest_lang}`:\n`{trans_str}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            trans_str = await asyncio.to_thread(
                trl.translate, text, lang_tgt=dest_lang, lang_src=source_lang
            )
            await message.reply_text(
                f"📒 *Translated from* `{source_lang}` to `{dest_lang}`:\n`{trans_str}`",
                parse_mode=ParseMode.MARKDOWN,
            )

    except IndexError:
        await message.reply_text(
            "Reply to messages or write messages from other languages ​​for translating into the intended language\n\n"
            "Example: `/tr en-ta` to translate from English to Tamil\n"
            "Or use: `/tr ta` for automatic detection and translation into Tamil.\n"
            "See [List of Language Codes](https://t.me/Hydra_Updates/80) for a list of language codes.",
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except ValueError:
        await message.reply_text("The intended language is not found!")
    else:
        return


__help__ = """
➠ `/tr` or `/tl` (language code) as reply to a long message

➠ *Example:*

» `/tr en`*:* translates something to English

» `/tr hi-en`*:* translates Hindi to English

» /echo < text >: echoes the message.
"""

__mod_name__ = "TRANSLATOR"
__command_list__ = ["tr", "tl", "echo"]
