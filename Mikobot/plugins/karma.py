# https://github.com/Team-ProjectCodeX
# UPDATED BY https://t.me/O_okarma
# https://t.me/ProjectCodeX

import asyncio

from pyrogram import filters

from Database.sql import karma_sql
from Database.sql.karma_sql import (
    alpha_to_int,
    get_karma,
    get_karmas,
    int_to_alpha,
    update_karma,
)
from Database.sql.toggle_sql import is_karma_on, karma_off, karma_on
from Mikobot import OWNER_ID, app
from Mikobot.utils.can_restrict import can_restrict
from Mikobot.utils.errors import capture_err

karma_positive_group = 3
karma_negative_group = 4


@app.on_message(
    filters.text
    & filters.group
    & filters.incoming
    & filters.reply
    & filters.regex(
        r"^(\+|\+\+|\+1|thx|tnx|ty|tq|thank you|thanx|thanks|pro|cool|good|agree|makasih|👍|\+\+ .+)$"
    )
    & ~filters.via_bot
    & ~filters.bot,
    group=karma_positive_group,
)
@capture_err
async def upvote(_, message):
    if not is_karma_on(message.chat.id):
        return
    reply_user = message.reply_to_message.from_user
    current_user = message.from_user
    if not (reply_user and current_user):
        return
    if reply_user.id == OWNER_ID:
        await message.reply_text("The owner cannot receive karma.")
        return
    if reply_user.id == current_user.id:
        return

    chat_id = message.chat.id
    user_id = reply_user.id
    user_mention = reply_user.mention
    current_karma = await asyncio.to_thread(get_karma, chat_id, int_to_alpha(user_id))
    karma = current_karma["karma"] + 1 if current_karma else 1
    new_karma = {"karma": karma}
    await asyncio.to_thread(update_karma, chat_id, int_to_alpha(user_id), new_karma)
    await message.reply_text(
        f"Incremented karma of {user_mention} by 1.\n**Total points:** {karma}"
    )


@app.on_message(
    filters.text
    & filters.group
    & filters.incoming
    & filters.reply
    & filters.regex(r"^(-|--|-1|not cool|disagree|worst|bad|👎|-- .+)$")
    & ~filters.via_bot
    & ~filters.bot,
    group=karma_negative_group,
)
@capture_err
async def downvote(_, message):
    if not is_karma_on(message.chat.id):
        return
    reply_user = message.reply_to_message.from_user
    current_user = message.from_user
    if not (reply_user and current_user):
        return
    if reply_user.id == OWNER_ID:
        await message.reply_text("The owner cannot lose karma.")
        return
    if reply_user.id == current_user.id:
        return

    user_id = reply_user.id
    user_mention = reply_user.mention
    current_karma = await asyncio.to_thread(
        get_karma, message.chat.id, int_to_alpha(user_id)
    )
    karma = current_karma["karma"] - 1 if current_karma else 0
    new_karma = {"karma": karma}
    await asyncio.to_thread(
        update_karma, message.chat.id, int_to_alpha(user_id), new_karma
    )
    await message.reply_text(
        f"Decremented karma of {user_mention} by 1.\n**Total points:** {karma}"
    )


@app.on_message(filters.command("karmastat") & filters.group)
@capture_err
async def karma(_, message):
    if not message.reply_to_message:
        m = await message.reply_text("Analyzing karma...")
        karma = await asyncio.to_thread(get_karmas, message.chat.id)
        if not karma:
            await m.edit_text("No karma in the database for this chat.")
            return
        msg = f"**Karma list for {message.chat.title}:**\n"
        limit = 0
        karma_dicc = {}
        for i in karma:
            user_id = alpha_to_int(i)
            user_karma = karma[i]["karma"]
            karma_dicc[str(user_id)] = user_karma
            karma_arranged = dict(
                sorted(karma_dicc.items(), key=lambda item: item[1], reverse=True)
            )
        if not karma_dicc:
            await m.edit_text("No karma in the database for this chat.")
            return
        for user_idd, karma_count in karma_arranged.items():
            if limit > 9:
                break
            try:
                user = await _.get_users(int(user_idd))
                await asyncio.sleep(0.8)
            except Exception:
                continue
            first_name = user.first_name
            if not first_name:
                continue
            msg += f"`{karma_count}`  {(first_name[0:12] + '...') if len(first_name) > 12 else first_name}\n"
            limit += 1
        await m.edit_text(msg)
    else:
        if not message.reply_to_message.from_user:
            return await message.reply_text(
                "Cannot check karma for anonymous senders or channels."
            )
        user_id = message.reply_to_message.from_user.id
        karma = get_karma(message.chat.id, int_to_alpha(user_id))
        karma = karma["karma"] if karma else 0
        await message.reply_text(f"**Total points:** {karma}")


@app.on_message(filters.command("karma"))
@can_restrict
async def karma_toggle_xd(_, message):
    usage = "**Usage:**\n/karma [ON|OFF]"
    if len(message.command) != 2:
        return await message.reply_text(usage)
    chat_id = message.chat.id
    state = message.text.split(None, 1)[1].strip().lower()

    if state == "on":
        if is_karma_on(chat_id):
            await message.reply_text("Karma system is already enabled.")
        else:
            karma_on(chat_id)
            await message.reply_text("Enabled the karma system.")
    elif state == "off":
        if not is_karma_on(chat_id):
            await message.reply_text("Karma system is already disabled.")
        else:
            karma_off(chat_id)
            await message.reply_text("Disabled the karma system.")
    else:
        await message.reply_text(usage)


__mod_name__ = "Karma"


def __migrate__(old_chat_id, new_chat_id):
    # karma_sql owns both the karma and the couple rows.
    karma_sql.migrate_chat(old_chat_id, new_chat_id)


__help__ = """
Upvote:
Use a keyword such as "+", "+1", or "thanks" in a reply to add karma.

Downvote:
Use a keyword such as "-" or "-1" in a reply to remove karma.

Commands:
/karmastat: Reply to a user to check their karma.
/karmastat: Send without a reply to list the top 10 by karma.
/karma [OFF|ON]: Enable or disable the karma system in this chat.
"""
