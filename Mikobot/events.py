"""Handler registration and dispatch on top of kurigram.

kurigram hands an update to the first matching handler inside a group and then
moves on to the next group. The bot needs the opposite for several commands:
the lock check, the flood check and the plugin's own command all have to see
the same message. aiogram ran every matching handler in registration order and
``chain`` marked the ones that let the next handler run.

So the registry lives here rather than in kurigram's dispatcher. One kurigram
handler per event type walks the registry in order, the permission gate runs
before the handler, and a chained handler hands the message on to the next
matching one.

Handlers are called the kurigram way, ``handler(client, update)``.
"""

import inspect
from dataclasses import dataclass
from typing import Any

from pyrogram import StopPropagation, filters
from pyrogram.handlers import (
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberUpdatedHandler,
    InlineQueryHandler,
    MessageHandler,
)

from Mikobot import app
from Mikobot.logger import LOGGER, correlation_scope
from Mikobot.utils.gate import end_unit_of_work, enforce


@dataclass(slots=True)
class Registration:
    """One handler, the filters that select it, and whether it chains."""

    filters: Any
    handler: Any
    chained: bool

    async def matches(self, client, update) -> bool:
        for one in self.filters:
            result = one(client, update)
            # A kurigram filter is a coroutine, a plain predicate is not.
            if inspect.isawaitable(result):
                result = await result
            if not result:
                return False
        return True


class Registry:
    """The handlers, in the order they were registered."""

    def __init__(self):
        self.messages: list[Registration] = []
        self.callbacks: list[Registration] = []
        self.inline_queries: list[Registration] = []
        self.join_requests: list[Registration] = []
        self.chat_member_updates: list[Registration] = []

    def add(self, bucket, filters, handler, chained: bool) -> None:
        bucket.append(Registration(filters, handler, chained))

    async def run(self, bucket, client, update) -> None:
        """Run every matching handler, stopping at the one that does not chain.

        A handler that the gate refuses ends the run for unchained handlers,
        while chained background checks continue to subsequent handlers.
        """
        with correlation_scope(f"{type(update).__name__}:{getattr(update, 'id', '')}"):
            for registration in bucket:
                try:
                    if not await registration.matches(client, update):
                        continue
                except Exception:
                    LOGGER.exception(
                        "Filter check failed for handler %s on update %s",
                        getattr(registration.handler, "__name__", "unknown"),
                        update,
                    )
                    continue
                is_chained = registration.chained or getattr(
                    registration.handler, "chained", False
                )
                try:
                    if not await enforce(client, update, registration.handler):
                        if is_chained:
                            continue
                        return
                    await registration.handler(client, update)
                except StopPropagation:
                    return
                except Exception as exc:
                    LOGGER.exception(
                        "Handler %s failed on update %s",
                        getattr(registration.handler, "__name__", "unknown"),
                        update,
                    )
                    # The registry swallows exceptions so a chained check can
                    # fail without stopping the command. Hand the error to
                    # kurigram's own ErrorHandler as well; otherwise the
                    # callback alert in __main__.error_callback is unreachable.
                    try:
                        await app.dispatcher.handle_update_handler_exception(
                            exc,
                            MessageHandler(registration.handler),
                            update,
                            {},
                            {},
                        )
                    except Exception:
                        LOGGER.exception("Error handler failed for %s", update)
                    if not is_chained:
                        return
                finally:
                    # Every handler may stage database writes and then raise. The
                    # session is thread-local, so whatever is left would otherwise
                    # be committed by an unrelated later call.
                    end_unit_of_work()
                if not is_chained:
                    return


registry = Registry()


def _event_decorator(name: str, bucket: str, doc: str):
    """Build one of the public ``on_*`` decorator factories."""

    def factory(*filters, chained: bool = False):
        def decorator(func):
            registry.add(getattr(registry, bucket), filters, func, chained)
            return func

        return decorator

    factory.__name__ = name
    factory.__qualname__ = name
    factory.__doc__ = doc
    return factory


on_message = _event_decorator(
    "on_message",
    "messages",
    """Register a message handler.

    ``chained=True`` lets the next matching handler run as well, which is what
    the lock, flood and plugin handlers need.
    """,
)
on_callback = _event_decorator(
    "on_callback", "callbacks", "Register a callback query handler."
)
on_inline_query = _event_decorator(
    "on_inline_query", "inline_queries", "Register an inline query handler."
)
on_chat_join_request = _event_decorator(
    "on_chat_join_request", "join_requests", "Register a chat join request handler."
)
on_chat_member_updated = _event_decorator(
    "on_chat_member_updated",
    "chat_member_updates",
    "Register a chat member update handler.",
)


def add_message(handler, *filters, chained: bool = False) -> None:
    """Register a message handler without a decorator.

    The bot's own commands are registered this way, after the plugins are
    imported, so that the lock and flood checks run ahead of them.
    """
    registry.add(registry.messages, filters, handler, chained)


def add_callback(handler, *filters, chained: bool = False) -> None:
    """Register a callback query handler without a decorator."""
    registry.add(registry.callbacks, filters, handler, chained)


def register(**args):
    """Legacy decorator: a message handler matched by a regex pattern.

    The handler takes the event only, the way the kurigram-era plugins were
    written. New code uses ``on_message``.
    """
    pattern = args.get("pattern")

    def decorator(func):
        handler_filter = filters.regex(pattern) if pattern else filters.all

        async def wrapper(client, event):
            return await func(event)

        registry.add(registry.messages, (handler_filter,), wrapper, False)
        return func

    return decorator


def callbackquery(**args):
    """Legacy decorator: a callback query handler matched by a regex pattern."""
    pattern = args.get("pattern")

    def decorator(func):
        handler_filter = filters.regex(pattern) if pattern else filters.all

        async def wrapper(client, event):
            return await func(event)

        registry.add(registry.callbacks, (handler_filter,), wrapper, False)
        return func

    return decorator


async def _dispatch_messages(client, message):
    await registry.run(registry.messages, client, message)


async def _dispatch_callbacks(client, query):
    await registry.run(registry.callbacks, client, query)


async def _dispatch_inline_queries(client, query):
    await registry.run(registry.inline_queries, client, query)


async def _dispatch_join_requests(client, request):
    await registry.run(registry.join_requests, client, request)


async def _dispatch_chat_member_updates(client, update):
    await registry.run(registry.chat_member_updates, client, update)


def install() -> None:
    """Hook the registry into kurigram's dispatcher.

    One handler per event type, with no filter of its own: the filters live
    in the registry, where the chain order is kept.
    """
    app.add_handler(MessageHandler(_dispatch_messages))
    app.add_handler(CallbackQueryHandler(_dispatch_callbacks))
    app.add_handler(InlineQueryHandler(_dispatch_inline_queries))
    app.add_handler(ChatJoinRequestHandler(_dispatch_join_requests))
    app.add_handler(ChatMemberUpdatedHandler(_dispatch_chat_member_updates))
