# <============================================== IMPORTS =========================================================>
from collections.abc import Callable
from functools import wraps

from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import RPCError
from pyrogram.types import Message

from Mikobot import DEV_USERS, app

# <=======================================================================================================>


# <================================================ FUNCTION =======================================================>
def has_restrict_rights(member) -> bool:
    """Whether a chat member may restrict other members.

    kurigram leaves ``ChatMember.privileges`` unset for a chat owner and
    for the admins of a basic group, so reading through it raised
    AttributeError. The owner outranks an administrator and holds every
    right, and a basic group has no per-right granularity at all: every
    admin there may ban. Only a supergroup admin carries an explicit
    rights object, and only its own flag decides.
    """
    if member is None:
        return False

    status = getattr(member, "status", None)
    if status == ChatMemberStatus.OWNER:
        return True

    if status != ChatMemberStatus.ADMINISTRATOR:
        return False

    privileges = getattr(member, "privileges", None)
    if privileges is None:
        return True

    return bool(privileges.can_restrict_members)


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
            return await message.reply("» I can't check your permissions in this chat.")

        if check.status not in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]:
            return await message.reply(
                "» You're not an admin, Please stay in your limits."
            )

        if has_restrict_rights(check):
            return await func(_, message)

        return await message.reply(
            "`You don't have permissions to restrict users in this chat.`"
        )

    return non_admin


# <================================================ END =======================================================>
