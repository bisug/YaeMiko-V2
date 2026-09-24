# <============================================== IMPORTS =========================================================>
from time import gmtime, strftime, time

from pyrogram import filters
from pyrogram.types import Message
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from Mikobot import LOGGER, app, function
from Mikobot.plugins.helper_funcs.chat_status import check_admin

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
            return await message.reply_text("**🪄 ᴛʜɪs ᴜsᴇʀ ᴅᴏᴇsɴ'ᴛ ᴇxɪsᴛ.**")

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
    await message.reply_text(text, disable_web_page_preview=True)


# Function to handle the "logs" command
@check_admin(only_dev=True)
async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with open("Logs.txt", "rb") as f:
        caption = "Here is your log"
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Close", callback_data="close")]]
        )
        message = await context.bot.send_document(
            document=f,
            filename=f.name,
            caption=caption,
            reply_markup=reply_markup,
            chat_id=user.id,
        )

        # Store the message ID for later reference
        context.user_data["log_message_id"] = message.message_id


# Asynchronous callback query handler for the "close" button
@check_admin(only_dev=True)
async def close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    message_id = context.user_data.get("log_message_id")
    if message_id:
        await context.bot.delete_message(
            chat_id=query.message.chat_id, message_id=message_id
        )


@app.on_message(filters.command("pyroping"))
async def ping(_, m: Message):
    LOGGER.info(f"{m.from_user.id} used ping cmd in {m.chat.id}")
    start = time()
    replymsg = await m.reply_text(text="Pinging...", do_quote=True)
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
function(CommandHandler("logs", logs, block=False))
function(CallbackQueryHandler(close_callback, pattern="^close$", block=False))

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
