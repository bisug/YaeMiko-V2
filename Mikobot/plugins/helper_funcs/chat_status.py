# <============================================== IMPORTS =========================================================>
from threading import RLock
from time import perf_counter

from cachetools import TTLCache
from pyrogram.enums import ChatMemberStatus, ChatMembersFilter, ChatType
from pyrogram.errors import RPCError

from Mikobot import DEL_CMDS, DEV_USERS, DRAGONS, SUPPORT_CHAT, app
from Mikobot.utils.gate import requirement

# DEV_USERS, DRAGONS, DEL_CMDS and SUPPORT_CHAT are read off this module by
# the gate at request time, so they are re-exported rather than unused.
__all__ = [
    "ADMIN_CACHE",
    "DEL_CMDS",
    "DEV_USERS",
    "DRAGONS",
    "SUPPORT_CHAT",
    "can_delete",
    "check_admin",
    "connection_status",
    "dev_plus",
    "granted",
    "is_admin",
    "is_bot_admin",
    "is_owner",
    "is_sudo_plus",
    "is_support_plus",
    "is_user_admin",
    "is_user_ban_protected",
    "is_user_in_chat",
    "is_whitelist_plus",
    "sudo_plus",
    "support_plus",
    "user_not_admin",
    "whitelist_plus",
]

# <=======================================================================================================>

# stores admemes in memory for 10 min.
ADMIN_CACHE = TTLCache(maxsize=10_000, ttl=60 * 10, timer=perf_counter)
THREAD_LOCK = RLock()

ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


def is_admin(member) -> bool:
    return getattr(member, "status", None) in ADMIN_STATUSES


def is_owner(member) -> bool:
    return getattr(member, "status", None) == ChatMemberStatus.OWNER


def granted(member, permission: str) -> bool:
    """Whether a chat member holds an administrator right.

    kurigram keeps the administrator rights in a separate ``privileges`` object
    rather than flattening them onto the member, and it leaves that object
    unset for the chat owner, who holds every right anyway.
    """
    if member is None:
        return False
    if getattr(member, "status", None) == ChatMemberStatus.OWNER:
        return True
    privileges = getattr(member, "privileges", None)
    if privileges is None:
        return False
    return bool(getattr(privileges, permission, False))


# <================================================ FUNCTION =======================================================>
def check_admin(
    permission: str = None,
    is_bot: bool = False,
    is_user: bool = False,
    is_both: bool = False,
    only_owner: bool = False,
    only_sudo: bool = False,
    only_dev: bool = False,
    no_reply: object = False,
) -> object:
    """Gate a handler on chat permissions, enforced by the gate in utils/gate.py.

    Args:
        permission (str, optional): permission type to check. Defaults to None.
        is_bot (bool, optional): if bot can perform the action. Defaults to False.
        is_user (bool, optional): if user can perform the action. Defaults to False.
        is_both (bool, optional): if both user and bot can perform the action. Defaults to False.
        only_owner (bool, optional): if only owner can perform the action. Defaults to False.
        only_sudo (bool, optional): if only sudo users can perform the operation. Defaults to False.
        only_dev (bool, optional): if only dev users can perform the operation. Defaults to False.
        no_reply (boot, optional): if should not reply. Defaults to False.
    """
    return requirement(
        kind="admin",
        permission=permission,
        is_bot=is_bot,
        is_user=is_user,
        is_both=is_both,
        only_owner=only_owner,
        only_sudo=only_sudo,
        only_dev=only_dev,
        no_reply=no_reply,
    )


def _is_elevated(chat, user_id: int, member=None) -> bool:
    return user_id in DRAGONS or user_id in DEV_USERS


# The three gate kinds below share one check and differ only in the refusal
# GateMiddleware sends, which it owns. The names stay because gate.py
# dispatches on the kind, not the predicate.
is_whitelist_plus = is_support_plus = is_sudo_plus = _is_elevated


async def is_user_admin(chat, user_id: int, member=None) -> bool:
    if (
        getattr(chat, "type", None) in (ChatType.PRIVATE, ChatType.BOT)
        or user_id in DRAGONS
        or user_id in DEV_USERS
        or user_id in [777000, 1087968824]
    ):  # Count telegram and Group Anonymous as admin
        return True
    if not member:
        with THREAD_LOCK:
            # try to fetch from cache first.
            try:
                return user_id in ADMIN_CACHE[chat.id]
            except KeyError:
                # keyerror happend means cache is deleted,
                # so query telegram again and return user status
                # while saving it in cache for future usage...
                try:
                    chat_admins = await app.get_chat_members(
                        chat.id, filter=ChatMembersFilter.ADMINISTRATORS
                    )
                except RPCError:
                    return False
                admin_list = []
                async for admin in chat_admins:
                    if admin.user is not None:
                        admin_list.append(admin.user.id)
                ADMIN_CACHE[chat.id] = admin_list

                return user_id in admin_list
    return is_admin(member)


async def is_bot_admin(chat, bot_id: int, bot_member=None) -> bool:
    if getattr(chat, "type", None) == "private":
        return True

    if not bot_member:
        bot_member = await app.get_chat_member(chat.id, bot_id)

    return is_admin(bot_member)


async def can_delete(chat, bot_id: int) -> bool:
    chat_member = await app.get_chat_member(chat.id, bot_id)
    return granted(chat_member, "can_delete_messages")


async def is_user_ban_protected(chat, user_id: int, member=None) -> bool:
    if (
        getattr(chat, "type", None) in (ChatType.PRIVATE, ChatType.BOT)
        or user_id in DRAGONS
        or user_id in DEV_USERS
        or user_id in [777000, 1087968824]
    ):  # Count telegram and Group Anonymous as admin
        return True

    if not member:
        member = await app.get_chat_member(chat.id, user_id)

    return is_admin(member)


async def is_user_in_chat(chat, user_id: int) -> bool:
    member = await app.get_chat_member(chat.id, user_id)
    return getattr(member, "status", None) in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.RESTRICTED,
    )


def dev_plus(func):
    return requirement(kind="dev_plus")(func)


def sudo_plus(func):
    return requirement(kind="sudo_plus")(func)


def support_plus(func):
    return requirement(kind="support_plus")(func)


def whitelist_plus(func):
    return requirement(kind="whitelist_plus")(func)


def user_not_admin(func):
    return requirement(kind="user_not_admin")(func)


def connection_status(func):
    """Resolve the linked group; handlers read it from the injected connected_chat."""
    return requirement(kind="connection_status")(func)


# <=======================================================================================================>
# <===================================================== END =====================================================>
