# <============================================== IMPORTS =========================================================>
import html
import random
from datetime import datetime

import humanize
from pyrogram import filters
from pyrogram.enums import MessageEntityType, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import Message

from Database.sql import afk_sql as sql
from Mikobot.events import on_message
from Mikobot.plugins.disable import disableable, disableable_friendly
from Mikobot.plugins.users import get_user_id
from Mikobot.utils.filters import GROUPS

# <=======================================================================================================>

# kurigram keeps the entity type in an enum, and the mention entities are
# the only ones that point at a user.
MENTION_ENTITIES = (MessageEntityType.TEXT_MENTION, MessageEntityType.MENTION)


# <================================================ FUNCTION =======================================================>
@on_message(*disableable("afk"), chained=True)
async def afk(client, message: Message):
    if not message.text:
        return
    args = message.text.split(None, 1)
    user = message.from_user

    if not user:  # ignore channels
        return

    notice = ""
    if len(args) >= 2:
        reason = args[1]
        if len(reason) > 100:
            reason = reason[:100]
            notice = "\nYour afk reason was shortened to 100 characters."
    else:
        reason = ""

    sql.set_afk(user.id, reason)
    fname = user.first_name
    try:
        if reason:
            await message.reply_text(
                f"➲ {html.escape(fname or str(user.id))} is now away! \n\n➦ Reason: <code>{html.escape(reason)}</code> \n {notice}",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("➲ {} is now away!{}".format(fname, notice))
    except RPCError:
        pass


@on_message(
    disableable_friendly("afk"),
    filters.regex(r"^(?i:(brb|!afk))( .*)?$"),
    chained=True,
)
async def afk_friendly(client, message: Message):
    """The same thing as /afk, but typed as a word rather than a command."""
    await afk(client, message)


@on_message(GROUPS, chained=True)
async def no_longer_afk(client, message: Message):
    user = message.from_user

    if not user:  # ignore channels
        return

    if not sql.is_afk(user.id):
        return

    afk_user = sql.check_afk_status(user.id)
    time = humanize.naturaldelta(datetime.now() - afk_user.time)
    res = sql.rm_afk(user.id)
    if res:
        if message.new_chat_members:  # dont say msg
            return
        firstname = user.first_name
        try:
            options = [
                "➲ {} is here!",
                "➲ {} is back!",
                "➲ {} is now in the chat!",
                "➲ {} is awake!",
                "➲ {} is back online!",
                "➲ {} is finally here!",
                "➲ Welcome back! {}",
            ]
            chosen_option = random.choice(options)
            await message.reply_text(
                chosen_option.format(firstname)
                + f"\n\nYou were AFK for: <code>{time}</code>",
                parse_mode=ParseMode.HTML,
            )
        except RPCError:
            return


@on_message(GROUPS, chained=True)
async def reply_afk(client, message: Message):
    userc = message.from_user
    userc_id = userc.id
    chk_users = []

    # The mention entities are read off the message itself: kurigram keeps
    # the entity type in an enum and the mentioned user on the entity.
    mention = next(
        (ent for ent in (message.entities or []) if ent.type in MENTION_ENTITIES),
        None,
    )
    if mention is not None:
        if mention.type == MessageEntityType.TEXT_MENTION:
            mentioned = mention.user
            if mentioned is None:
                return
            user_id = mentioned.id
            fst_name = mentioned.first_name

            if user_id in chk_users:
                return
            chk_users.append(user_id)
            # This branch used to fall through to the end of the if/elif/else
            # without answering, so a mention of someone without a @username
            # resolved the user and then reported nothing.
            await check_afk(message, user_id, fst_name, userc_id)
        else:
            text = (message.text or "")[
                mention.offset : mention.offset + mention.length
            ]
            user_id = await get_user_id(text)
            if not user_id:
                return

            if user_id in chk_users:
                return
            chk_users.append(user_id)

            fst_name = text.lstrip("@")
            await check_afk(message, user_id, fst_name, userc_id)

    elif message.reply_to_message:
        # A channel post or a service message has no from_user, and reading
        # .id off it raised AttributeError on every reply to one.
        replied_user = message.reply_to_message.from_user
        if replied_user is None:
            return
        user_id = replied_user.id
        fst_name = replied_user.first_name
        await check_afk(message, user_id, fst_name, userc_id)


async def check_afk(
    message: Message,
    user_id: int,
    fst_name: str,
    userc_id: int,
):
    if sql.is_afk(user_id):
        user = sql.check_afk_status(user_id)

        if int(userc_id) == int(user_id):
            return

        time = humanize.naturaldelta(datetime.now() - user.time)

        if not user.reason:
            res = "➲ {} is afk.\n\n➦ Last seen {} ago.".format(
                fst_name,
                time,
            )
            await message.reply_text(res)
        else:
            res = (
                "➲ {} is afk.\n\n➦ Reason: <code>{}</code>\n➦ Last seen {} ago.".format(
                    html.escape(fst_name),
                    html.escape(user.reason),
                    time,
                )
            )
            await message.reply_text(res, parse_mode=ParseMode.HTML)


# <=================================================== HELP ====================================================>


__help__ = """
» /afk <reason>*:* mark yourself as AFK (away from keyboard).

» brb , !afk <reason>*:* same as the afk command - but not a command.

» /bye [Reason > Optional] - Tell others that you are AFK (Away From Keyboard).

» /bye [reply to media] - AFK with media.

» /byedel - Enable auto delete AFK message in group (Only for group admin). Default is **Enable**.

➠ *When marked as AFK, any mentions will be replied to with a message to say you're not available!*
"""

__mod_name__ = "AFK"
__command_list__ = ["afk"]
# <================================================ END =======================================================>
