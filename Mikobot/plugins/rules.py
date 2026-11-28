import asyncio
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
import Database.sql.toggle_sql as toggle_sql
from Mikobot import BOT_USERNAME
from Mikobot.events import on_message
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.plugins.helper_funcs.string_handling import (
    markdown_parser,
    markdown_to_html,
)
from Mikobot.utils.filters import GROUPS


def _rules_markup(chat_id):
    label = sql.get_rules_button(chat_id) or "Rules"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    url=f"t.me/{BOT_USERNAME}?start={chat_id}",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
        ],
    )


async def _rules_button_reply(message, chat_id):
    reply_msg = message.reply_to_message
    if reply_msg and not reply_msg.forum_topic_created:
        await reply_msg.reply_text(
            "Please click the button below to see the rules.",
            reply_markup=_rules_markup(chat_id),
        )
    else:
        await message.reply_text(
            "Please click the button below to see the rules.",
            reply_markup=_rules_markup(chat_id),
        )


async def _cleanup_action(sent):
    from Mikobot.plugins.parity_misc import schedule_cleanup

    await schedule_cleanup(sent, "action")


async def send_rules(client, message, chat_id, from_pm=False):
    user = message.from_user
    try:
        chat = await client.get_chat(chat_id)
    except RPCError:
        if from_pm:
            await client.send_message(
                user.id,
                "The rules shortcut for this chat is not set. Ask an admin to fix it.",
            )
            return
        else:
            raise

    rules = sql.get_rules(chat_id)
    text = f"The rules for {escape(chat.title)} are:\n\n{markdown_to_html(rules)}"

    if from_pm:
        try:
            if rules:
                await client.send_message(
                    user.id,
                    text,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            else:
                await client.send_message(
                    user.id,
                    "No rules have been set for this chat.",
                )
        except RPCError:
            # A blocked bot cannot be reached in PM; answer in the chat instead.
            if rules:
                await _rules_button_reply(message, chat_id)
            else:
                await message.reply_text("No rules have been set for this chat.")
        return

    if rules:
        await _rules_button_reply(message, chat_id)
    else:
        await message.reply_text(
            "No rules have been set for this chat.",
        )


@on_message(GROUPS & filters.command("rules"), chained=True)
async def get_rules(client, message: Message):
    private = await asyncio.to_thread(
        toggle_sql.is_toggle_on,
        message.chat.id,
        toggle_sql.PRIVATE_RULES,
    )
    if private:
        await send_rules(client, message, message.chat.id, from_pm=True)
    else:
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
        sent = await message.reply_text("Successfully set rules for this group.")
        await _cleanup_action(sent)


@on_message(GROUPS & filters.command(["clearrules", "resetrules"]), chained=True)
@check_admin(is_user=True)
async def clear_rules(client, message: Message):
    sql.set_rules(message.chat.id, "")
    sent = await message.reply_text("Rules cleared.")
    await _cleanup_action(sent)


@on_message(GROUPS & filters.command("privaterules"), chained=True)
@check_admin(is_user=True)
async def private_rules(client, message: Message):
    from Mikobot.plugins.parity_misc import handle_toggle

    await handle_toggle(
        client,
        message,
        toggle_sql.PRIVATE_RULES,
        "Private rules",
    )


@on_message(GROUPS & filters.command("setrulesbutton"), chained=True)
@check_admin(is_user=True)
async def set_rules_button(client, message: Message):
    args = message.command[1:] if message.command else []
    if not args:
        await message.reply_text("Provide a label for the rules button.")
        return
    label = " ".join(args).strip()
    if not label:
        await message.reply_text("Provide a label for the rules button.")
        return
    sql.set_rules_button(message.chat.id, label)
    sent = await message.reply_text(f"Rules button label set to `{label}`.")
    await _cleanup_action(sent)


@on_message(GROUPS & filters.command("resetrulesbutton"), chained=True)
@check_admin(is_user=True)
async def reset_rules_button(client, message: Message):
    sql.reset_rules_button(message.chat.id)
    sent = await message.reply_text("Rules button label reset to default.")
    await _cleanup_action(sent)


def __stats__():
    return f"• {sql.num_chats()} chats have rules set."


async def __import_data__(chat_id, data, message):
    rules = data.get("info", {}).get("rules", "")
    sql.set_rules(chat_id, rules)


def __migrate__(old_chat_id, new_chat_id):
    sql.migrate_chat(old_chat_id, new_chat_id)


def __chat_settings__(chat_id, user_id):
    return f"This chat has had its rules set: `{bool(sql.get_rules(chat_id))}`"


__help__ = """
/rules: Get the rules for this chat.

Admin only:
/setrules <rules>: Set the rules for this chat.
/clearrules, /resetrules: Clear the rules for this chat.
/privaterules <on|off|status>: Send rules in private instead of the group.
/setrulesbutton <text>: Set the label of the rules button.
/resetrulesbutton: Restore the default rules button label.
"""

__mod_name__ = "Rules"
