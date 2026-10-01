import asyncio
import html
import re

from aiogram import F
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import Database.sql.kuki_sql as sql
from Mikobot import bot, dp
from Mikobot.plugins.ai import get_ai_response
from Mikobot.plugins.log_channel import gloggable
from Mikobot.utils.gate import chain

# <=======================================================================================================>

# The original answered through api.brainshop.ai, an unauthenticated third-party
# echo service that no longer exists. This reuses the Gemini client that
# Mikobot.plugins.ai already wraps, so no new dependency is introduced.

# <================================================ FUNCTION =======================================================>
@gloggable
async def kukirm(query: CallbackQuery):
    match = re.fullmatch(r"rm_chat", query.data or "")
    if not match:
        return ""
    chat = query.message.chat
    was_enabled = sql.is_kuki(chat.id)
    sql.rem_kuki(chat.id)
    if was_enabled:
        return (
            f"<b>{html.escape(chat.title or str(chat.id))}:</b>\n"
            f"AI_DISABLED\n"
        )
    await query.message.edit_text("Chatbot disabled.", parse_mode=ParseMode.HTML)
    return ""


@gloggable
async def kukiadd(query: CallbackQuery):
    match = re.fullmatch(r"add_chat", query.data or "")
    if not match:
        return ""
    chat = query.message.chat
    already = sql.is_kuki(chat.id)
    sql.set_kuki(chat.id)
    if not already:
        await query.message.edit_text("Chatbot enabled.", parse_mode=ParseMode.HTML)
        return ""
    return (
        f"<b>{html.escape(chat.title or str(chat.id))}:</b>\n"
        f"AI_ENABLE\n"
    )


async def kuki(message: Message, command):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Enable", callback_data="add_chat", style=ButtonStyle.PRIMARY
                ),
                InlineKeyboardButton(
                    text="Disable", callback_data="rm_chat", style=ButtonStyle.DANGER
                ),
            ]
        ]
    )
    await message.reply(
        "Choose an option",
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )


async def chatbot(message: Message):
    # Skips commands and replies to itself, so the bot cannot feed its own
    # output back into the model and loop.
    text = message.text
    if not text or text.lower() == "kuki" or text.startswith(("#", "!", "/")):
        return
    reply = message.reply_to_message
    if reply and reply.from_user and reply.from_user.id == bot.id:
        return
    if not sql.is_kuki(message.chat.id):
        return

    await bot.send_chat_action(message.chat.id, action="typing")
    answer = await get_ai_response(text)
    await asyncio.sleep(0.3)
    await message.reply(answer, parse_mode=ParseMode.HTML)


async def list_all_chats(message: Message):
    chats = sql.get_all_kuki_chats()
    if not chats:
        return await message.reply("No chats have the chatbot enabled.")
    text = "<b>Neko Enabled Chats</b>\n"
    for chat_id in chats:
        try:
            info = await bot.get_chat(int(chat_id))
        except TelegramAPIError as exc:
            if "chat not found" in str(exc).lower():
                sql.rem_kuki(chat_id)
                continue
            raise
        text += f"• <code>{html.escape(info.title or info.first_name)}</code>\n"
    await message.reply(text, parse_mode=ParseMode.HTML)


# <=================================================== HELP ====================================================>

__help__ = """
➠ *Admins only command*:

» /chatbot: shows chatbot panel.
» /allchats: lists every chat with the chatbot enabled.
"""
__mod_name__ = "CHATBOT"


# <================================================ HANDLER =======================================================>
dp.message.register(chain(kuki), Command("chatbot"))
dp.message.register(chain(list_all_chats), Command("allchats"), F.chat.type == "private")
dp.callback_query.register(chain(kukiadd), F.data == "add_chat")
dp.callback_query.register(chain(kukirm), F.data == "rm_chat")
dp.message.register(chain(chatbot), F.text, ~F.text.startswith(("#", "!", "/")))
# <================================================ END =======================================================>