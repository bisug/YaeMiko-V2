"""Permission and chat-action gates, enforced before a handler runs.

PTB did this with decorator wrappers around ``async def handler(update, context)``.
aiogram injected the handler arguments by name from the *inner* signature, so a
wrapper only ever saw what the wrapped function declared and could not reach
for the event or the bot by itself. The decorators therefore tag the handler
instead of wrapping it, and the middleware enforces the tags once per event,
where both the event and the bot are in hand.

kurigram calls handlers as ``handler(client, update)`` and has no middleware,
so the registry in ``Mikobot.events`` calls ``enforce`` before it calls the
handler and hands it the same two things.

Order matters: ``@a`` above ``@b`` must run first, and tags are prepended so the
list order matches the source order.
"""

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager

from pyrogram.enums import ChatAction, ChatMemberStatus, ChatType
from pyrogram.errors import RPCError

LOGGER = logging.getLogger(__name__)

# Telegram drops a chat action roughly five seconds after it is sent, so the
# indicator is repeated on this interval while the handler runs.
CHAT_ACTION_INTERVAL = 5.0

# The names the decorators use, and the kurigram actions behind them.
CHAT_ACTIONS = {
    "typing": ChatAction.TYPING,
    "upload_photo": ChatAction.UPLOAD_PHOTO,
    "upload_document": ChatAction.UPLOAD_DOCUMENT,
    "choose_sticker": ChatAction.CHOOSE_STICKER,
}


# <=======================================================================================================>


# <================================================ FUNCTION =====================================================>
def requirement(**spec):
    """Attach a gate to a handler. Runs outermost-first, like the old wrappers."""

    def decorator(func):
        func.requirements = (spec, *getattr(func, "requirements", ()))
        return func

    return decorator


def chain(func):
    """Mark a handler that lets the next matching handler run as well.

    PTB's ``block=False`` meant "do not stop the chain", and 105 of the bot's
    handlers used it: one message could hit locks, then flood, then the plugin.
    The registry in ``Mikobot.events`` walks the handlers in order and stops at
    the first one that is not chained, so the marker is all this has to do.
    """
    func.chained = True
    return func
# <=======================================================================================================>


# <================================================== HELPERS ===================================================>
async def _action_reply(event, text):
    """Reply through whatever event we were handed, matching the old behaviour."""
    answer = getattr(event, "answer", None)
    if answer is not None:
        return await answer(text)
    message = getattr(event, "message", None)
    if message is not None:
        return await message.reply_text(text)
    return None


async def _silently_drop(event):
    """DEL_CMDS: remove a bare command from a non-privileged user instead."""
    message = getattr(event, "message", None) or event
    text = getattr(message, "text", None)
    if text and " " not in text:
        try:
            await message.delete()
        except Exception:
            return False
    return True


def end_unit_of_work() -> None:
    """Discard any database state this update left staged.

    Imported lazily because Database.sql imports Mikobot, so importing it at the
    top of this module would be circular.
    """
    try:
        from Database.sql import SESSION

        if SESSION is not None:
            SESSION.end_unit_of_work()
    except Exception:
        LOGGER.exception("Could not clear staged database state")


@asynccontextmanager
async def _repeat_action(client, chat_id, action):
    """Keep the chat action alive while the handler runs."""
    try:
        while True:
            await asyncio.sleep(CHAT_ACTION_INTERVAL)
            try:
                await client.send_chat_action(chat_id, action)
            except Exception:
                return
    except asyncio.CancelledError:
        return


@staticmethod
def _chat_id(event):
    chat = getattr(event, "chat", None)
    if chat is not None:
        return chat.id
    message = getattr(event, "message", None)
    chat = getattr(message, "chat", None)
    return chat.id if chat is not None else None


@staticmethod
def _thread_id(event):
    """The forum topic to show the action in, when the chat has topics.

    Telegram drops a chat action sent without a topic in a forum chat, so the
    indicator would otherwise land in General instead of the topic the command
    was issued in. The event carries chat and topic itself; a CallbackQuery
    carries the message that does.
    """
    chat = getattr(event, "chat", None)
    if chat is None:
        chat = getattr(getattr(event, "message", None), "chat", None)
        event = getattr(event, "message", None)
    if getattr(chat, "is_forum", False):
        return getattr(event, "message_thread_id", None)
    return None


@staticmethod
def _is_private(event):
    chat = getattr(event, "chat", None) or getattr(
        getattr(event, "message", None), "chat", None
    )
    return getattr(chat, "type", None) == ChatType.PRIVATE


@staticmethod
def _event_parts(event):
    message = getattr(event, "message", None)
    chat = getattr(event, "chat", None) or getattr(message, "chat", None)
    user = getattr(event, "from_user", None) or getattr(message, "from_user", None)
    return chat, user
# <=======================================================================================================>


# <=================================================== GATE =====================================================>
async def enforce(client, event, handler) -> bool:
    """Run the gate. False means the handler must not run.

    The handler's tags decide what is checked; the checks themselves live
    here so that one place owns the wording of every refusal.
    """
    from Mikobot.plugins.helper_funcs import chat_status

    # Bot senders are dropped before any handler runs. Telegram usually never
    # delivers these at all, but where it does, the default has to be that a
    # bot's message is inert.
    if not await _bot_sender_allowed(client, event):
        return False
    if not await _bot_command_reviewed(client, event):
        return False

    async with AsyncExitStack() as stack:
        for spec in getattr(handler, "requirements", ()):
            action = spec.get("chat_action")
            if action:
                chat_id = _chat_id(event)
                if chat_id is not None:
                    # The first send is awaited here rather than left to the
                    # repeat: a handler that finishes before the loop ever runs
                    # the repeat would show no indicator at all.
                    await client.send_chat_action(
                        chat_id, CHAT_ACTIONS.get(action, ChatAction.TYPING)
                    )
                    stack.enter_async_context(
                        _repeat_action(
                            client,
                            chat_id,
                            CHAT_ACTIONS.get(action, ChatAction.TYPING),
                        )
                    )
                continue

            if spec["kind"] == "connection_status":
                resolved = await _connected_chat(client, event)
                if resolved is not None:
                    # kurigram hands the handler the client and the event and
                    # nothing else, so the linked chat rides on the event.
                    event.connected_chat = resolved
                elif _is_private(event):
                    await _action_reply(
                        event,
                        "Send /connect in a group that you and I have in common first.",
                    )
                    return False
                continue

            # Skips quietly when the sender is an admin, matching PTB, which
            # only reached the handler for a non-admin user. It is not a
            # denial: no reply and no command deletion.
            if spec["kind"] == "user_not_admin":
                if not await _sender_is_not_admin(event):
                    return False
                continue

            denial = await _denial(client, event, spec, chat_status)
            if denial is not None:
                text, drop = denial
                if drop and await _silently_drop(event):
                    return False
                await _action_reply(event, text)
                return False

    return True
# <=======================================================================================================>


# <=============================================== BOT SENDERS ================================================>
async def _bot_sender_allowed(client, event) -> bool:
    """Whether a bot sender may run commands in this chat.

    Off by default. In "admin" mode the sending bot must itself be an admin,
    since that is the whole point of the mode. An explicit per-bot allow
    overrides the mode so a trusted automation bot can be permitted without
    opening the chat to every bot.
    """
    chat, user = _event_parts(event)
    if user is None or not getattr(user, "is_bot", False):
        return True
    # Our own messages come back through nothing, but be explicit.
    if chat is not None and user.id == client.me.id:
        return True

    from Database.sql import bot2bot_sql

    chat_id = _chat_id(event)
    if chat_id is None:
        return True
    try:
        mode, _skip, allowed = await asyncio.to_thread(
            bot2bot_sql.get_setting, chat_id
        )
    except Exception:
        # Fail closed: if the setting cannot be read, a bot gets no access.
        LOGGER.exception("Could not read the bot2bot setting for %s", chat_id)
        return False

    if str(user.id) in allowed:
        return True
    if mode == bot2bot_sql.MODE_OFF:
        return False
    if mode == bot2bot_sql.MODE_ALL:
        return True
    if chat is None:
        return False
    try:
        member = await client.get_chat_member(chat.id, user.id)
    except RPCError:
        return False
    return member.status in (
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
    )


async def _bot_command_reviewed(client, event) -> bool:
    """Whether a bot's command may run now.

    Only commands that change configuration are held for a human; anything
    else a bot sends is inert enough to run, since the mode check above has
    already decided the bot is allowed to act at all.
    """
    _chat, user = _event_parts(event)
    if user is None or not getattr(user, "is_bot", False):
        return True
    if getattr(event, "text", None) is None:
        # Non-text updates from a bot (joins, reactions) carry no command.
        return True
    if _chat_id(event) == client.me.id:
        return True

    from Mikobot.plugins import bot2bot

    # A replay of an approved command passes straight through, once.
    message_id = getattr(event, "id", None) or getattr(event, "message_id", None)
    if message_id is not None and message_id in bot2bot.APPROVED_ONCE:
        bot2bot.APPROVED_ONCE.discard(message_id)
        return True

    return await bot2bot.request_review(user, _event_parts(event)[0], event)
# <=======================================================================================================>


# <================================================== PERMISSIONS ================================================>
async def _sender_is_not_admin(event) -> bool:
    """PTB's @user_not_admin ran the handler only for a non-admin sender."""
    from Mikobot.plugins.helper_funcs import chat_status

    chat, user = _event_parts(event)
    if chat is None or user is None:
        return False
    return not await chat_status.is_user_admin(chat, user.id)


async def _connected_chat(client, event):
    from Mikobot.plugins import connection

    chat = getattr(event, "chat", None) or getattr(
        getattr(event, "message", None), "chat", None
    )
    user = getattr(event, "from_user", None)
    if chat is None or user is None:
        return None
    conn = await connection.connected(client, event, chat, user.id, need_admin=False)
    return await client.get_chat(conn) if conn else None


async def _denial(client, event, spec, status):
    """None to allow, otherwise (text, drop_silently) to deny with."""
    kind = spec["kind"]
    chat = getattr(event, "chat", None) or getattr(
        getattr(event, "message", None), "chat", None
    )
    user = getattr(event, "from_user", None)
    user_id = getattr(user, "id", None)

    if kind == "dev_plus":
        if user_id in status.DEV_USERS:
            return None
        return (
            "This is a developer restricted command. "
            "You do not have permissions to run this.",
            status.DEL_CMDS,
        )
    if kind == "sudo_plus":
        if status.is_sudo_plus(chat, user_id):
            return None
        return (
            "Who dis non-admin telling me what to do? You want a punch?",
            status.DEL_CMDS,
        )
    if kind == "support_plus":
        if status.is_support_plus(chat, user_id):
            return None
        return ("You do not have permission to use this command.", status.DEL_CMDS)
    if kind == "whitelist_plus":
        if status.is_whitelist_plus(chat, user_id):
            return None
        return (
            f"You don't have access to use this.\nVisit @{status.SUPPORT_CHAT}",
            False,
        )

    if _is_private(event) and not (
        spec["only_dev"] or spec["only_sudo"] or spec["only_owner"]
    ):
        return None

    bot_member = user_member = None
    if spec["is_bot"] or spec["is_both"]:
        bot_member = await _member(client, chat, client.me.id)
    if spec["is_user"] or spec["is_both"]:
        user_member = await _member(client, chat, user_id)

    if spec["only_owner"]:
        if status.is_owner(user_member) or user_id in status.DEV_USERS:
            return None
        return ("Only chat owner can perform this action.", False)
    if spec["only_dev"]:
        if user_id in status.DEV_USERS:
            return None
        return (
            "Hey little kid\nWho the hell are you to say me what to execute on my server?",
            False,
        )
    if spec["only_sudo"]:
        if user_id in status.DRAGONS:
            return None
        return ("Who dis non-admin telling me what to do? You want a punch?", False)

    is_anon_admin = user_id in (777000, 1087968824)
    permission = spec["permission"]
    if permission and (spec["is_user"] or spec["is_both"]):
        if not (
            is_anon_admin
            or status.granted(user_member, permission)
            or user_id in status.DRAGONS
        ):
            if spec["no_reply"]:
                return ("", True)
            return (f"You don't have permission to {permission}.", False)
    if permission and (spec["is_bot"] or spec["is_both"]):
        if not status.granted(bot_member, permission):
            if spec["no_reply"]:
                return ("", True)
            return (f"I don't have permission to {permission}.", False)

    if spec["is_bot"] and not status.is_admin(bot_member):
        return ("I'm not admin here.", False)
    if spec["is_user"] and not (
        is_anon_admin or status.is_admin(user_member) or user_id in status.DRAGONS
    ):
        return ("You are not admin here.", False)
    return None


@staticmethod
async def _member(client, chat, user_id):
    if chat is None or user_id is None:
        return None
    try:
        return await client.get_chat_member(chat.id, user_id)
    except RPCError:
        return None
# <=======================================================================================================>
