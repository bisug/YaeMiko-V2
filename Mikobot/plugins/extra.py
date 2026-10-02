# <============================================== IMPORTS =========================================================>
from time import gmtime, strftime, time

from aiogram import F
from aiogram.enums import ButtonStyle
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from pyrogram import filters
from pyrogram.types import LinkPreviewOptions

from Mikobot import LOGGER, app, bot, dp, store, user_data
from Mikobot.plugins.helper_funcs.chat_status import check_admin
from Mikobot.utils.gate import chain

# <=======================================================================================================>

UPTIME = time()  # Check bot uptime


# <================================================ FUNCTION =======================================================>
@app.on_message(filters.command("id"))
async def _id(client, message):
    chat = message.chat
    your_id = message.from_user.id
    mention_user = message.from_user.mention
    message_id = message.id
    reply = message.reply_to_message

    text = f"**๏ [ᴍᴇssᴀɢᴇ ɪᴅ]({message.link})** » `{message_id}`\n"
    text += f"**๏ [{mention_user}](tg://user?id={your_id})** » `{your_id}`\n"

    if not message.command:
        message.command = message.text.split()

    if not message.command:
        message.command = message.text.split()

    if len(message.command) == 2:
        try:
            split = message.text.split(None, 1)[1].strip()
            user_id = (await client.get_users(split)).id
            user_mention = (await client.get_users(split)).mention
            text += f"**๏ [{user_mention}](tg://user?id={user_id})** » `{user_id}`\n"

        except Exception:
            return await message.reply("**🪄 ᴛʜɪs ᴜsᴇʀ ᴅᴏᴇsɴ'ᴛ ᴇxɪsᴛ.**")

    text += f"**๏ [ᴄʜᴀᴛ ɪᴅ ](https://t.me/{chat.username})** » `{chat.id}`\n\n"

    if (
        not getattr(reply, "empty", True)
        and not message.forward_from_chat
        and not reply.sender_chat
    ):
        text += f"**๏ [ʀᴇᴘʟɪᴇᴅ ᴍᴇssᴀɢᴇ ɪᴅ]({reply.link})** » `{message.reply_to_message.id}`\n"
        text += f"**๏ [ʀᴇᴘʟɪᴇᴅ ᴜsᴇʀ ɪᴅ](tg://user?id={reply.from_user.id})** » `{reply.from_user.id}`\n\n"

    if reply and reply.forward_from_chat:
        text += f"๏ ᴛʜᴇ ғᴏʀᴡᴀʀᴅᴇᴅ ᴄʜᴀɴɴᴇʟ, {reply.forward_from_chat.title}, ʜᴀs ᴀɴ ɪᴅ ᴏғ `{reply.forward_from_chat.id}`\n\n"

    if reply and reply.sender_chat:
        text += f"๏ ID ᴏғ ᴛʜᴇ ʀᴇᴘʟɪᴇᴅ ᴄʜᴀᴛ/ᴄʜᴀɴɴᴇʟ, ɪs `{reply.sender_chat.id}`"

    # Send sticker and text as a reply
    sticker_id = (
        "CAACAgIAAx0EdppwYAABAgotZg5rBL4P05Xjmy80p7DdNdneDmUAAnccAALIWZhJPyYLf3FzPHs0BA"
    )
    await message.reply_sticker(sticker=sticker_id)
    await message.reply(text, link_preview_options=LinkPreviewOptions(is_disabled=True))


# Function to handle the "logs" command
@check_admin(only_dev=True)
async def logs(message: Message):
    with open("Logs.txt", "rb") as f:
        caption = "Here is your log"
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Close", callback_data="close", style=ButtonStyle.PRIMARY)]]
        )
        sent = await bot.send_document(
            document=f,
            filename=f.name,
            caption=caption,
            reply_markup=reply_markup,
            chat_id=message.from_user.id,
        )

        # Store the message ID for later reference
        user_data[message.from_user.id]["log_message_id"] = sent.message_id
        store.save()


# Asynchronous callback query handler for the "close" button
@check_admin(only_dev=True)
async def close_callback(query: CallbackQuery):
    message_id = user_data.get(query.from_user.id, {}).get("log_message_id")
    if message_id:
        try:
            await bot.delete_message(
                chat_id=query.message.chat.id, message_id=message_id
            )
            user_data[query.from_user.id].pop("log_message_id", None)
            store.save()
            await query.answer()
        except Exception:
            await query.answer("Unable to close this log.", show_alert=True)
    else:
        await query.answer("This log has already been closed.")


@app.on_message(filters.command("pyroping"))
async def ping(_, m: Message):
    LOGGER.info(f"{m.from_user.id} used ping cmd in {m.chat.id}")
    start = time()
    replymsg = await m.reply(text="Pinging...")
    delta_ping = time() - start

    up = strftime("%Hh %Mm %Ss", gmtime(time() - UPTIME))
    image_url = "https://telegra.ph/file/e1049f371bbec3f006f3a.jpg"

    # Send the image as a reply
    await replymsg.reply_photo(
        photo=image_url,
        caption=f"<b>Pyro-Pong!</b>\n{delta_ping * 1000:.3f} ms\n\nUptime: <code>{up}</code>",
    )
    await replymsg.delete()


# <=======================================================================================================>


# <================================================ HANDLER =======================================================>
dp.message.register(chain(logs), Command("logs"))
dp.callback_query.register(chain(close_callback), F.data == "close")

# <================================================= HELP ======================================================>
__help__ = """
➠ *Commands*:

» /instadl, /insta <link>: Get instagram contents like reel video or images.

» /pyroping: see pyroping.

» /hyperlink <text> <link> : Creates a markdown hyperlink with the provided text and link.

» /pickwinner <participant1> <participant2> ... : Picks a random winner from the provided list of participants.

» /id: reply to get user id.
"""

__mod_name__ = "EXTRA"
# <================================================ END =======================================================>
