# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

import random
import re

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions, Message

from Mikobot.events import on_message


@on_message(filters.command("pickwinner"))
async def pick_winner(client, message: Message):
    participants = message.command[1:]

    if participants:
        winner = random.choice(participants)

        await message.reply_text(f"🎉 The winner is: {winner}")
    else:
        await message.reply_text("Please provide a list of participants.")


@on_message(filters.command("hyperlink"))
async def hyperlink_command(client, message: Message):
    args = message.command[1:]
    if len(args) >= 2:
        text = " ".join(args[:-1])
        link = args[-1]
        hyperlink = f"[{text}]({link})"
        await message.reply_text(
            text=hyperlink,
            parse_mode=ParseMode.MARKDOWN,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    else:
        match = re.search(r"/hyperlink ([^\s]+) (.+)", message.text)
        if match:
            text = match.group(1)
            link = match.group(2)
            hyperlink = f"[{text}]({link})"
            await message.reply_text(
                text=hyperlink,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            await message.reply_text(
                "❌ Invalid format! Please use the format: /hyperlink <text> <link>."
            )
