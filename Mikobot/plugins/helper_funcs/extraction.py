# <============================================== IMPORTS =========================================================>
from typing import List, Optional

from aiogram.types import Message

from Mikobot.plugins.helper_funcs.string_handling import entities_map
from Mikobot.plugins.users import get_user_id

# <=======================================================================================================>

TEXT_MENTION = "text_mention"


# <================================================ FUNCTION =======================================================>
async def id_from_reply(message: Message):
    prev_message = message.reply_to_message
    if not prev_message or prev_message.forum_topic_created:
        return None, None
    user_id = prev_message.from_user.id
    # if user id is from channel bot, then fetch channel id from sender_chat
    if user_id == 136817688:
        user_id = message.reply_to_message.sender_chat.id
    res = message.text.split(None, 1)
    if len(res) < 2:
        return user_id, ""
    return user_id, res[1]


async def extract_user(
    message: Message,
    args: List[str],
) -> Optional[int]:
    return (await extract_user_and_text(message, args))[0]


async def _resolve_target(message: Message, args: List[str]) -> tuple:
    """Shared body of the extractors: resolve (user_id, text) from message or args.

    Returns (None, None) both when the target cannot be resolved and when a
    @username is unknown; the callers add their own wording to that case.
    """
    prev_message = message.reply_to_message
    split_text = message.text.split(None, 1)

    if len(split_text) < 2:
        return await id_from_reply(message)  # only option possible

    text_to_parse = split_text[1]
    text = ""

    entities = list(entities_map(message, [TEXT_MENTION]))
    ent = entities[0] if entities else None
    # if entity offset matches (command end/text start) then all good
    if entities and ent and ent.offset == len(message.text) - len(text_to_parse):
        user_id = ent.user.id
        text = message.text[ent.offset + ent.length :]
    elif len(args) >= 1 and args[0][0] == "@":
        user_id = await get_user_id(args[0])
        if not user_id:
            return None, None
        res = message.text.split(None, 2)
        if len(res) >= 3:
            text = res[2]
    elif len(args) >= 1 and args[0].isdigit():
        user_id = int(args[0])
        res = message.text.split(None, 2)
        if len(res) >= 3:
            text = res[2]
    elif prev_message:
        user_id, text = await id_from_reply(message)
    else:
        return None, None

    return user_id, text


async def extract_user_and_text(
    message: Message,
    args: List[str],
) -> tuple:
    result = await _resolve_target(message, args)
    if result == (None, None) and len(args) >= 1 and args[0][0] == "@":
        await message.answer(
            "No idea who this user is. You'll be able to interact with them if "
            "you reply to that person's message instead, or forward one of that user's messages.",
        )
    return result


async def extract_text(message) -> str:
    return (
        message.text
        or message.caption
        or (message.sticker.emoji if message.sticker else None)
    )


async def extract_unt_fedban(
    message: Message, args: List[str]
) -> tuple:
    result = await _resolve_target(message, args)
    if result == (None, None) and len(args) >= 1 and args[0][0] == "@":
        await message.answer(
            "I don't have that user in my db.  "
            "You'll be able to interact with them if you reply to that person's message instead, or forward one of that user's messages.",
        )
    return result


async def extract_user_fban(
    message: Message,
    args: List[str],
) -> Optional[int]:
    return (await extract_unt_fedban(message, args))[0]


# <================================================ END =======================================================>
