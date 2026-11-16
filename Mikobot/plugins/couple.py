import asyncio
import random
from datetime import datetime, timedelta

from pyrogram import filters

from Database.sql.karma_sql import get_couple, save_couple
from Mikobot import app

ADDITIONAL_IMAGES = [
    "https://telegra.ph/file/7ef6006ed6e452a6fd871.jpg",
    "https://telegra.ph/file/16ede7c046f35e699ed3c.jpg",
    "https://telegra.ph/file/f16b555b2a66853cc594e.jpg",
]


def dt():
    now = datetime.now()
    dt_string = now.strftime("%d/%m/%Y %H:%M")
    dt_list = dt_string.split(" ")
    return dt_list


def dt_tom():
    return (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y %H:%M").split(" ")[0]


tomorrow = dt_tom()
today = datetime.now().strftime("%d/%m/%Y")

C = """
Couple of the day:
{} + PGM (https://t.me/Chalnayaaaaaarr) + 花火 (https://t.me/zd_sr07) + ゼロツー (https://t.me/wewewe_x) = 💞
New couple of the day, chosen at 12AM: {}
"""
CAP = """
Couple of the day:
{} + {} = 💞
New couple of the day, chosen at 12AM: {}
"""

CAP2 = """
Couple of the day:
{} (tg://openmessage?user_id={}) + {} (tg://openmessage?user_id={}) = 💞
New couple of the day, chosen at 12AM: {}
"""


@app.on_message(filters.command(["couple", "couples", "shipping"]) & ~filters.private)
async def nibba_nibbi(_, message):
    COUPLES_PIC = random.choice(ADDITIONAL_IMAGES)
    if not message.from_user or message.from_user.is_bot:
        return
    try:
        chat_id = message.chat.id
        is_selected = await asyncio.to_thread(get_couple, chat_id, today)
        if not is_selected:
            list_of_users = []
            async for member in _.get_chat_members(message.chat.id, limit=100):
                if member.user and not member.user.is_bot:
                    list_of_users.append(member.user.id)
            if len(list_of_users) < 2:
                return await message.reply_text("Not enough users in the group.")
            c1_id, c2_id = random.sample(list_of_users, 2)
            users = await _.get_users([c1_id, c2_id])
            # Kurigram keeps a None placeholder for ids it could not resolve,
            # so a missing member would raise on .mention.
            if users[0] is None or users[1] is None:
                return await message.reply_text(
                    "I could not resolve both users. Please try again later."
                )
            c1_mention, c2_mention = users[0].mention, users[1].mention
            await _.send_photo(
                message.chat.id,
                photo=COUPLES_PIC,
                caption=CAP.format(c1_mention, c2_mention, tomorrow),
            )
            await asyncio.to_thread(
                save_couple, chat_id, today, {"c1_id": c1_id, "c2_id": c2_id}
            )
        else:
            c1_id = int(is_selected["c1_id"])
            c2_id = int(is_selected["c2_id"])
            users = await _.get_users([c1_id, c2_id])
            if users[0] is None or users[1] is None:
                return await message.reply_text(
                    "I could not resolve both users. Please try again later."
                )
            c1, c2 = users[0], users[1]
            couple_selection_message = CAP2.format(
                c1.first_name or "User", c1_id, c2.first_name or "User", c2_id, tomorrow
            )
            await _.send_photo(
                message.chat.id, photo=COUPLES_PIC, caption=couple_selection_message
            )
    except Exception:
        await message.reply_text(
            "Unable to select a couple right now. Please try again later."
        )


__help__ = """
Commands:
/couple: Choose two users and post them as a couple in the chat.
/couples: Same as /couple.
/shipping: Same as /couple.
"""

__mod_name__ = "Couple"
