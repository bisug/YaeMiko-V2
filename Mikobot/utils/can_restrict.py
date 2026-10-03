# <============================================== IMPORTS =========================================================>
from collections.abc import Callable
from functools import wraps

from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import RPCError
from pyrogram.types import Message

from Mikobot import DEV_USERS, app

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def can_restrict(func: Callable) -> Callable:
    @wraps(func)
    async def non_admin(_, message: Message):
        sender = message.from_user
        if sender is None:
            return

        if sender.id in DEV_USERS:
            return await func(_, message)

        # One lookup, not two: the original code called get_chat_member here
        # and then again for .privileges, costing a second round trip per
        # guarded command on a path that runs before every /purge, /dwelcome
        # and /setmataa.
        try:
            check = await app.get_chat_member(message.chat.id, sender.id)
        except RPCError:
            return await message.reply(
                "» I can't check your permissions in this chat."
            )

        if check.status not in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
            return await message.reply(
                "» You're not an admin, Please stay in your limits."
            )

        # kurigram leaves .privileges unset for a chat owner
        # (chat_member.py builds ChatMember(status=OWNER) with no rights), so
        # reading through it raised AttributeError and turned every owner-run
        # restricted command into a traceback. The owner outranks an
        # administrator, so the rights check applies to admins alone.
        if check.status == ChatMemberStatus.OWNER:
            return await func(_, message)

        admin = check.privileges
        if admin is not None and admin.can_restrict_members:
            return await func(_, message)

        return await message.reply(
            "`You don't have permissions to restrict users in this chat.`"
        )

    return non_admin


# <================================================ END =======================================================>
