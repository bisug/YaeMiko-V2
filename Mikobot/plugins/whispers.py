# SOURCE https://github.com/Team-ProjectCodeX
# CREATED BY https://t.me/O_okarma
# PROVIDED BY https://t.me/ProjectCodeX

# Inline mode must be enabled in BotFather for whispers to work.

from uuid import uuid4

from pyrogram import filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from Database.sql.whispers_sql import add_whisper, del_whisper, get_whisper
from Mikobot import BOT_USERNAME
from Mikobot.events import on_callback, on_inline_query


@on_inline_query(chained=True)
async def mainwhisper(client, query: InlineQuery):
    if not query.query:
        return await query.answer(
            [],
            switch_pm_text="Provide a username or ID.",
            switch_pm_parameter="ghelp_whisper",
        )

    user, message = parse_user_message(query.query)
    if len(message) > 200:
        return await query.answer(
            [],
            switch_pm_text="Whisper messages are limited to 200 characters.",
            switch_pm_parameter="ghelp_whisper",
        )

    usertype = "username" if user.startswith("@") else "id"

    display_user = user
    target_id = int(user) if user.isdigit() else None
    if target_id is not None:
        try:
            chat = await client.get_chat(target_id)
            display_user = f"@{chat.username}" if chat.username else chat.first_name
        except Exception:
            pass

    whisperData = {
        "user": query.from_user.id,
        "withuser": target_id if target_id is not None else display_user,
        "usertype": usertype,
        "type": "inline",
        "message": message,
    }
    whisperId = uuid4().hex

    add_whisper(whisperId, whisperData)

    answers = [
        InlineQueryResultArticle(
            id=whisperId,
            title=f"Send a whisper to {user}.",
            description="Only the recipient can see it.",
            input_message_content=InputTextMessageContent(
                message_text=f"A whisper for {user}\nOnly the recipient can see it."
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="Show whisper",
                            callback_data=f"whisper_{whisperId}",
                            style=ButtonStyle.PRIMARY,
                        )
                    ]
                ]
            ),
        )
    ]

    await query.answer(results=answers, cache_time=0)


@on_callback(filters.regex(r"^whisper_"), chained=True)
async def showWhisper(client, callback_query: CallbackQuery):
    whisperId = callback_query.data.split("_")[-1]
    whisper = get_whisper(whisperId)

    if not whisper:
        await callback_query.answer("This whisper is no longer valid.", show_alert=True)
        return

    userType = whisper["usertype"]
    from_user_id = callback_query.from_user.id

    is_sender = from_user_id == whisper["user"]
    if (
        is_sender
        or (
            userType == "username"
            and callback_query.from_user.username
            and callback_query.from_user.username.lower()
            == whisper["withuser"].replace("@", "").lower()
        )
        or userType == "id"
        and str(from_user_id) == str(whisper["withuser"])
    ):
        await callback_query.answer(whisper["message"], show_alert=True)
    else:
        await callback_query.answer("This whisper is not for you.", show_alert=True)
        return

    if not is_sender:
        del_whisper(whisperId)


def parse_user_message(query_text):
    text = query_text.split(" ")
    user = text[0]
    first = True
    message = ""

    if not user.startswith("@") and not user.isdigit():
        user = text[-1]
        first = False

    if first:
        message = " ".join(text[1:])
    else:
        text.pop()
        message = " ".join(text)

    return user, message


__help__ = f"""
Send a message only the recipient can see.

Example:

@{BOT_USERNAME} your message @username
@{BOT_USERNAME} @username your message
"""

__mod_name__ = "Whispers"
__command_list__ = []
