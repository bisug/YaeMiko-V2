"""Permission and chat-action gates, driven by handler metadata.

PTB did this with decorator wrappers around ``async def handler(update, context)``.
aiogram injects handler arguments by name from the *inner* signature, so a
wrapper only ever sees what the wrapped function declares and cannot reach for
the event or the bot by itself. The decorators therefore tag the handler
instead of wrapping it, and this middleware enforces the tags once per event,
where both the event and the bot are in hand.

Order matters: ``@a`` above ``@b`` must run first, and tags are prepended so the
list order matches the source order.
"""

from functools import wraps

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError


def requirement(**spec):
    """Attach a gate to a handler. Runs outermost-first, like the old wrappers."""

    def decorator(func):
        func.requirements = (spec, *getattr(func, "requirements", ()))
        return func

    return decorator


def chain(func):
    """Run this handler, then let the next matching handler run as well.

    PTB's ``block=False`` meant "do not stop the chain", and 105 of the bot's
    handlers used it: one message could hit locks, then flood, then the plugin.
    aiogram's observer.trigger() returns after the *first* matching handler
    (dispatcher/event/telegram.py), so without this only one would ever run.
    Raising SkipHandler from a finally block is what resumes the iteration.
    """
    if getattr(func, "_chained", False):
        return func

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # SkipHandler is raised only after the handler returns. Raising it
        # from a finally block replaced whatever exception was in flight, so
        # a failing handler looked like a successful one and its traceback
        # never reached error_callback. The dispatcher's trigger() discards
        # the return value anyway, so it is not propagated here.
        await func(*args, **kwargs)
        raise SkipHandler()

    wrapper._chained = True
    return wrapper


async def _action_reply(event, text):
    """Reply through whatever event we were handed, matching the old behaviour."""
    answer = getattr(event, "answer", None)
    if answer is not None:
        return await answer(text)
    message = getattr(event, "message", None)
    if message is not None:
        return await message.answer(text)
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


class GateMiddleware(BaseMiddleware):
    def __init__(self, chat_status):
        self.chat_status = chat_status

    async def __call__(self, handler, event, data):
        bot = data["bot"]
        # aiogram passes the HandlerObject under "handler"; it subclasses
        # CallableObject, whose .callback is the decorated function carrying
        # the gate requirements.
        callback = data["handler"].callback
        for spec in getattr(callback, "requirements", ()):
            action = spec.get("chat_action")
            if action:
                chat_id = self._chat_id(event)
                if chat_id is not None:
                    await bot.send_chat_action(chat_id=chat_id, action=action)
                continue

            if spec["kind"] == "connection_status":
                resolved = await self._connected_chat(bot, event)
                if resolved is not None:
                    data["connected_chat"] = resolved
                elif self._is_private(event):
                    await _action_reply(
                        event,
                        "Send /connect in a group that you and I have in common first.",
                    )
                    return None
                continue

            # Skips quietly when the sender is an admin, matching PTB, which
            # only reached the handler for a non-admin user. It is not a
            # denial: no reply and no command deletion.
            if spec["kind"] == "user_not_admin":
                if not await self._sender_is_not_admin(event):
                    return None
                continue

            denial = await self._denial(bot, event, spec)
            if denial is not None:
                text, drop = denial
                if drop and await _silently_drop(event):
                    return None
                await _action_reply(event, text)
                return None
        return await handler(event, data)

    @staticmethod
    def _event_parts(event):
        message = getattr(event, "message", None)
        chat = getattr(event, "chat", None) or getattr(message, "chat", None)
        user = getattr(event, "from_user", None) or getattr(message, "from_user", None)
        return chat, user

    async def _sender_is_not_admin(self, event) -> bool:
        """PTB's @user_not_admin ran the handler only for a non-admin sender."""
        chat, user = self._event_parts(event)
        if chat is None or user is None:
            return False
        return not await self.chat_status.is_user_admin(chat, user.id)

    @staticmethod
    def _chat_id(event):
        chat = getattr(event, "chat", None)
        if chat is not None:
            return chat.id
        message = getattr(event, "message", None)
        return getattr(message, "chat", None) and message.chat.id

    @staticmethod
    def _is_private(event) -> bool:
        chat = getattr(event, "chat", None) or getattr(
            getattr(event, "message", None), "chat", None
        )
        return getattr(chat, "type", None) == "private"

    async def _connected_chat(self, bot, event):
        from Mikobot.plugins import connection

        chat = getattr(event, "chat", None) or getattr(
            getattr(event, "message", None), "chat", None
        )
        user = getattr(event, "from_user", None)
        if chat is None or user is None:
            return None
        conn = await connection.connected(bot, event, chat, user.id, need_admin=False)
        return await bot.get_chat(conn) if conn else None

    async def _denial(self, bot, event, spec):
        """None to allow, otherwise (text, drop_silently) to deny with."""
        status = self.chat_status
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

        if self._is_private(event) and not (
            spec["only_dev"] or spec["only_sudo"] or spec["only_owner"]
        ):
            return None

        bot_member = user_member = None
        if spec["is_bot"] or spec["is_both"]:
            bot_member = await self._member(bot, chat, bot.id)
        if spec["is_user"] or spec["is_both"]:
            user_member = await self._member(bot, chat, user_id)

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

        permission = spec["permission"]
        if permission and (spec["is_user"] or spec["is_both"]):
            if not (status.granted(user_member, permission) or user_id in status.DRAGONS):
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
            status.is_admin(user_member) or user_id in status.DRAGONS
        ):
            return ("You are not admin here.", False)
        return None

    @staticmethod
    async def _member(bot, chat, user_id):
        if chat is None or user_id is None:
            return None
        try:
            return await bot.get_chat_member(chat.id, user_id)
        except TelegramAPIError:
            return None
