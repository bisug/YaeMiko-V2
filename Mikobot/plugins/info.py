# <============================================== IMPORTS =========================================================>
import os
import re
from html import escape
from random import choice

from aiogram.enums import ButtonStyle, ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from Database.sql.approve_sql import is_approved
from Infamous.karma import START_IMG
from Mikobot import BOT_NAME, DEV_USERS, DRAGONS, INFOPIC, OWNER_ID, bot, dp
from Mikobot.plugins.helper_funcs.chat_status import support_plus
from Mikobot.plugins.users import get_user_id
from Mikobot.utils.consts import ChatID
from Mikobot.utils.gate import chain
from Mikobot.utils.parser import mention_html

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
async def info(message: Message, command: CommandObject):
    chat = message.chat
    args = command.args.split() if command.args else []

    def reply_with_text(text):
        return message.answer(text, parse_mode=ParseMode.HTML)

    head = ""
    premium = False

    reply = await reply_with_text("<code>Getting information...</code>")

    user_id = None
    user_name = None

    if len(args) >= 1:
        if args[0][0] == "@":
            user_name = args[0]
            user_id = await get_user_id(user_name)

        if not user_id:
            try:
                chat_obj = await bot.get_chat(user_name)
                userid = chat_obj.id
            except TelegramAPIError:
                await reply_with_text(
                    "I can't get information about this user/channel/group."
                )
                return
        else:
            userid = user_id
    elif len(args) >= 1 and args[0].lstrip("-").isdigit():
        userid = int(args[0])
    elif message.reply_to_message and not message.reply_to_message.forum_topic_created:
        if message.reply_to_message.sender_chat:
            userid = message.reply_to_message.sender_chat.id
        elif message.reply_to_message.from_user:
            if message.reply_to_message.from_user.id == ChatID.FAKE_CHANNEL:
                userid = message.reply_to_message.chat.id
            else:
                userid = message.reply_to_message.from_user.id
                premium = message.reply_to_message.from_user.is_premium
    elif not message.reply_to_message and not args:
        if message.from_user.id == ChatID.FAKE_CHANNEL:
            userid = message.sender_chat.id
        else:
            userid = message.from_user.id
            premium = message.from_user.is_premium

    try:
        chat_obj = await bot.get_chat(userid)
    except (TelegramAPIError, UnboundLocalError):
        await reply_with_text("I can't get information about this user/channel/group.")
        return

    if chat_obj.type == ChatType.PRIVATE:
        if chat_obj.username:
            head = f"⇨【 <b>USER INFORMATION</b> 】⇦\n\n"
            if chat_obj.username.endswith("bot"):
                head = f"⇨【 <b>BOT INFORMATION</b> 】⇦\n\n"

        head += f"➲ <b>ID:</b> <code>{chat_obj.id}</code>"
        head += f"\n➲ <b>First Name:</b> {chat_obj.first_name}"
        if chat_obj.last_name:
            head += f"\n➲ <b>Last Name:</b> {chat_obj.last_name}"
        if chat_obj.username:
            head += f"\n➲ <b>Username:</b> @{chat_obj.username}"
        head += f"\n➲ <b>Permalink:</b> {mention_html(chat_obj.id, 'link')}"

        if chat_obj.username and not chat_obj.username.endswith("bot"):
            head += f"\n\n💎 <b>Premium User:</b> {premium}"

        if chat_obj.bio:
            head += f"\n\n<b>➲ Bio:</b> {chat_obj.bio}"

        chat_member = await bot.get_chat_member(chat.id, chat_obj.id)
        if chat_member.status == ChatMemberStatus.ADMINISTRATOR:
            head += f"\n➲ <b>Presence:</b> {chat_member.status}"
            if chat_member.custom_title:
                head += f"\n➲ <b>Admin Title:</b> {chat_member.custom_title}"
        else:
            head += f"\n➲ <b>Presence:</b> {chat_member.status}"

        if is_approved(chat.id, chat_obj.id):
            head += f"\n➲ <b>Approved:</b> This user is approved in this chat."

        from Mikobot.__main__ import USER_INFO

        disaster_level_present = False

        if chat_obj.id == OWNER_ID:
            head += "\n\n👑 <b>The disaster level of this person is My Owner.</b>"
            disaster_level_present = True
        elif chat_obj.id in DEV_USERS:
            head += "\n\n🐉 <b>This user is a member of Infamous Hydra.</b>"
            disaster_level_present = True
        elif chat_obj.id in DRAGONS:
            head += "\n\n🐲 <b>The disaster level of this person is Dragon.</b>"
            disaster_level_present = True
        if disaster_level_present:
            head += " [?]"

        for mod in USER_INFO:
            try:
                mod_info = mod.__user_info__(chat_obj.id).strip()
            except TypeError:
                mod_info = mod.__user_info__(chat_obj.id, chat.id).strip()

            head += "\n\n" + mod_info if mod_info else ""

    if chat_obj.type == ChatType.SENDER:
        head = f"📨 Sender Chat Information:\n"
        await reply_with_text("Found sender chat, getting information...")
        head += f"<b>ID:</b> <code>{chat_obj.id}</code>"
        if chat_obj.title:
            head += f"\n🏷️ <b>Title:</b> {chat_obj.title}"
        if chat_obj.username:
            head += f"\n📧 <b>Username:</b> @{chat_obj.username}"
        head += f"\n🔗 Permalink: {mention_html(chat_obj.id, 'link')}"
        if chat_obj.description:
            head += f"\n📝 <b>Description:</b> {chat_obj.description}"

    elif chat_obj.type == ChatType.CHANNEL:
        head = f"Channel Information:\n"
        await reply_with_text("Found channel, getting information...")
        head += f"<b>ID:</b> <code>{chat_obj.id}</code>"
        if chat_obj.title:
            head += f"\n<b>Title:</b> {chat_obj.title}"
        if chat_obj.username:
            head += f"\n<b>Username:</b> @{chat_obj.username}"
        head += f"\nPermalink: {mention_html(chat_obj.id, 'link')}"
        if chat_obj.description:
            head += f"\n<b>Description:</b> {chat_obj.description}"
        if chat_obj.linked_chat_id:
            head += f"\n<b>Linked Chat ID:</b> <code>{chat_obj.linked_chat_id}</code>"

    elif chat_obj.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        head = f"Group Information:\n"
        await reply_with_text("Found group, getting information...")
        head += f"<b>ID:</b> <code>{chat_obj.id}</code>"
        if chat_obj.title:
            head += f"\n<b>Title:</b> {chat_obj.title}"
        if chat_obj.username:
            head += f"\n<b>Username:</b> @{chat_obj.username}"
        head += f"\nPermalink: {mention_html(chat_obj.id, 'link')}"
        if chat_obj.description:
            head += f"\n<b>Description:</b> {chat_obj.description}"

    if INFOPIC:
        try:
            if chat_obj.photo:
                await bot.download(
                    chat_obj.photo[-1].file_id, destination=f"{chat_obj.id}.png"
                )
                await message.answer_photo(
                    photo=open(f"{chat_obj.id}.png", "rb"),
                    caption=(head),
                    parse_mode=ParseMode.HTML,
                )
                await reply.delete()
                os.remove(f"{chat_obj.id}.png")
            else:
                await reply_with_text(escape(head))
        except (TelegramAPIError, OSError):
            # The photo path can fail on download, on the caption's HTML, or on
            # the temp file. Falling back to the text form still answers.
            await reply_with_text(escape(head))


@support_plus
async def stats(message: Message):
    from Mikobot.__main__ import STATS

    stats = f"📊 <b>{escape(BOT_NAME)}'s Statistics:</b>\n\n" + "\n".join(
        [mod.__stats__() for mod in STATS]
    )
    result = re.sub(r"(\d+)", r"<code>\1</code>", stats)

    keyboard = [
        [
            InlineKeyboardButton(
                text="㊋ Infamous • Hydra",
                url="https://t.me/Infamous_Hydra",
                style=ButtonStyle.PRIMARY,
            ),
        ]
    ]

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    await message.answer_photo(
        photo=str(choice(START_IMG)),
        caption=result,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


# <=================================================== HELP ====================================================>


__help__ = """
*Overall information about user:*

» /info : Fetch user information.

» /uinfo : Fetch user information in banner.
"""

# <================================================ HANDLER =======================================================>
dp.message.register(chain(stats), Command(commands=["stats", "gstats"]))
dp.message.register(chain(info), Command(commands=("info", "book")))

__mod_name__ = "INFO"
__command_list__ = ["info"]
# <================================================ END =======================================================>
