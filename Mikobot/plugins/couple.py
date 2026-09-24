# <============================================== IMPORTS =========================================================>
import random
from datetime import datetime, timedelta

from pyrogram import filters

from Database.mongodb.karma_mongo import get_couple, save_couple
from Mikobot import app

# <=======================================================================================================>

# List of additional images
ADDITIONAL_IMAGES = [
    "https://telegra.ph/file/7ef6006ed6e452a6fd871.jpg",
    "https://telegra.ph/file/16ede7c046f35e699ed3c.jpg",
    "https://telegra.ph/file/f16b555b2a66853cc594e.jpg",
]


# <================================================ FUNCTION =======================================================>
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
•➵💞࿐ 𝐇𝐚𝐩𝐩𝐲 𝐜𝐨𝐮𝐩𝐥𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐝𝐚𝐲
╭──────────────
┊•➢ {} + ( PGM🎀😶 (https://t.me/Chalnayaaaaaarr) + 花火 (https://t.me/zd_sr07) + ゼロツー (https://t.me/wewewe_x) ) = 💞
╰───•➢♡
╭──────────────
┊•➢ 𝗡𝗲𝘄 𝗰𝗼𝘂𝗽𝗹𝗲 𝗼𝗳 𝘁𝗵𝗲 𝗱𝗮𝘆 𝗺𝗮𝘆𝗯𝗲
┊ 𝗰𝗵𝗼𝘀𝗲𝗻 𝗮𝘁 12AM {}
╰───•➢♡
"""
CAP = """
•➵💞࿐ 𝐇𝐚𝐩𝐩𝐲 𝐜𝐨𝐮𝐩𝐥𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐝𝐚𝐲
╭──────────────
┊•➢ {} + {} = 💞
╰───•➢♡
╭──────────────
┊•➢ 𝗡𝗲𝘄 𝗰𝗼𝘂𝗽𝗹𝗲 𝗼𝗳 𝘁𝗵𝗲 𝗱𝗮𝘆 𝗺𝗮𝘆𝗯𝗲
┊ 𝗰𝗵𝗼𝘀𝗲𝗻 𝗮𝘁 12AM {}
╰───•➢♡
"""

CAP2 = """
•➵💞࿐ 𝐇𝐚𝐩𝐩𝐲 𝐜𝐨𝐮𝐩𝐥𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐝𝐚𝐲
╭──────────────
┊{} (tg://openmessage?user_id={}) + {} (tg://openmessage?user_id={}) = 💞\n
╰───•➢♡
╭──────────────
┊•➢ 𝗡𝗲𝘄 𝗰𝗼𝘂𝗽𝗹𝗲 𝗼𝗳 𝘁𝗵𝗲 𝗱𝗮𝘆 𝗺𝗮𝘆𝗯𝗲
┊ 𝗰𝗵𝗼𝘀𝗲𝗻 𝗮𝘁 12AM {}
╰───•➢♡
"""


@app.on_message(filters.command(["couple", "couples", "shipping"]) & ~filters.private)
async def nibba_nibbi(_, message):
    COUPLES_PIC = random.choice(ADDITIONAL_IMAGES)  # Move inside the command function
    if not message.from_user or message.from_user.is_bot:
        return
    try:
        chat_id = message.chat.id
        is_selected = await get_couple(chat_id, today)
        if not is_selected:
            list_of_users = []
            async for member in _.get_chat_members(message.chat.id, limit=100):
                if member.user and not member.user.is_bot:
                    list_of_users.append(member.user.id)
            if len(list_of_users) < 2:
                return await message.reply_text("Not enough users in the group.")
            c1_id, c2_id = random.sample(list_of_users, 2)
            c1_mention = (await _.get_users(c1_id)).mention
            c2_mention = (await _.get_users(c2_id)).mention
            await _.send_photo(
                message.chat.id,
                photo=COUPLES_PIC,
                caption=CAP.format(c1_mention, c2_mention, tomorrow),
            )
            await save_couple(chat_id, today, {"c1_id": c1_id, "c2_id": c2_id})
        else:
            c1_id = int(is_selected["c1_id"])
            c2_id = int(is_selected["c2_id"])
            c1 = await _.get_users(c1_id)
            c2 = await _.get_users(c2_id)
            couple_selection_message = CAP2.format(
                c1.first_name or "User", c1_id, c2.first_name or "User", c2_id, tomorrow
            )
            await _.send_photo(
                message.chat.id, photo=COUPLES_PIC, caption=couple_selection_message
            )
    except Exception:
        await message.reply_text("Unable to select a couple right now. Please try again later.")


# <=================================================== HELP ====================================================>
__help__ = """
💘 *Choose couples in your chat*

➦ /couple, /couples, /shipping *:* Choose 2 users and send their names as couples in your chat.
"""

__mod_name__ = "COUPLE"
# <================================================ END =======================================================>
