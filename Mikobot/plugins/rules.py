# <============================================== IMPORTS =========================================================>
from html import escape

from pyrogram import filters
from pyrogram.enums import ButtonStyle, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

import Database.sql.rules_sql as sql
from Mikobot import BOT_USERNAME
from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.string_handling import (
    markdown_parser,
    markdown_to_html,
)
from Mikobot.utils.filters import GROUPS

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
async def send_rules(client, message, chat_id, from_pm=False):
    user = message.from_user
    reply_msg = message.reply_to_message
    try:
        chat = await client.get_chat(chat_id)
    except RPCError:
        if from_pm:
            await client.send_message(
                user.id,
                "The rules shortcut for this chat hasn't been set properly! Ask admins to "
                "fix it.\nMaybe they forgot the hyphen in ID",
            )
            return
        else:
            raise

    rules = sql.get_rules(chat_id)
    text = f"The rules for {escape(chat.title)} are:\n\n{markdown_to_html(rules)}"

    if from_pm and rules:
        await client.send_message(
            user.id,
            text,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    elif from_pm:
        await client.send_message(
            user.id,
            "The group admins haven't set any rules for this chat yet. "
            "This probably doesn't mean it's lawless though...!",
        )
    elif rules and reply_msg and not reply_msg.forum_topic_created:
        await reply_msg.reply_text(
            "Please click the button below to see the rules.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="RULES",
                            url=f"t.me/{BOT_USERNAME}?start={chat_id}",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                ],
            ),
        )
    elif rules:
        await message.reply_text(
            "Please click the button below to see the rules.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="RULES",
                            url=f"t.me/{BOT_USERNAME}?start={chat_id}",
                            style=ButtonStyle.PRIMARY,
                        ),
                    ],
                ],
            ),
        )
    else:
        await message.reply_text(
            "The group admins haven't set any rules for this chat yet. "
            "This probably doesn't mean it's lawless though...!",
        )


@on_message(GROUPS & filters.command("rules"), chained=True)
async def get_rules(client, message: Message):
    await send_rules(client, message, message.chat.id)


@on_message(GROUPS & filters.command("setrules"), chained=True)
@check_admin(is_user=True)
async def set_rules(client, message: Message):
    chat_id = message.chat.id
    raw_text = message.text
    args = raw_text.split(None, 1)  # use python's maxsplit to separate cmd and args
    if len(args) == 2:
        txt = args[1]
        offset = len(txt) - len(raw_text)  # set correct offset relative to command
        markdown_rules = markdown_parser(txt, offset=offset)

        sql.set_rules(chat_id, markdown_rules)
        await message.reply_text("Successfully set rules for this group.")


@on_message(GROUPS & filters.command("clearrules"), chained=True)
@check_admin(is_user=True)
async def clear_rules(client, message: Message):
    sql.set_rules(message.chat.id, "")
    await message.reply_text("Successfully cleared rules!")


def __stats__():
    return f"• {sql.num_chats()} chats have rules set."


async def __import_data__(chat_id, data, message):
    # set chat rules
    rules = data.get("info", {}).get("rules", "")
    sql.set_rules(chat_id, rules)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    return f"This chat has had its rules set: `{bool(sql.get_rules(chat_id))}`"


# <=======================================================================================================>


# <================================================= HELP ======================================================>
__help__ = """
➠ /rules: Get the rules for this chat.

➠ *Admins only*:
» /setrules <your rules here>: Set the rules for this chat.

» /clearrules: Clear the rules for this chat.
"""

__mod_name__ = "RULES"
# <================================================== END =====================================================>
