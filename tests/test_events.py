from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from Mikobot import events
from Mikobot.utils.gate import chain, requirement


@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is global, so every test starts from an empty one."""
    events.registry.messages.clear()
    events.registry.callbacks.clear()
    events.registry.inline_queries.clear()
    events.registry.join_requests.clear()
    events.registry.chat_member_updates.clear()
    yield
    events.registry.messages.clear()
    events.registry.callbacks.clear()


def make_client():
    client = AsyncMock()
    client.me = MagicMock()
    client.me.id = 123456789
    client.me.username = "YaeMikoTestBot"
    return client


def make_message():
    message = MagicMock()
    message.chat.type = "supergroup"
    message.chat.id = -1001234567890
    message.from_user.id = 987654321
    message.from_user.is_bot = False
    message.text = "/ping"
    message.command = None
    return message


async def test_a_matching_handler_runs():
    calls = []

    @events.on_message(lambda client, message: True)
    async def handler(client, message):
        calls.append(message)

    client = make_client()
    message = make_message()
    await events.registry.run(events.registry.messages, client, message)

    assert calls == [message]


async def test_a_handler_that_does_not_match_never_runs():
    calls = []

    @events.on_message(lambda client, message: False)
    async def handler(client, message):
        calls.append(message)

    await events.registry.run(events.registry.messages, make_client(), make_message())

    assert calls == []


async def test_a_chained_handler_lets_the_next_one_run():
    calls = []

    @events.on_message(lambda client, message: True)
    async def first(client, message):
        calls.append("first")

    @events.on_message(lambda client, message: True)
    async def second(client, message):
        calls.append("second")

    chain(first)
    await events.registry.run(events.registry.messages, make_client(), make_message())

    assert calls == ["first", "second"]


async def test_a_handler_that_does_not_chain_stops_the_registry():
    calls = []

    @events.on_message(lambda client, message: True)
    async def first(client, message):
        calls.append("first")

    @events.on_message(lambda client, message: True)
    async def second(client, message):
        calls.append("second")

    await events.registry.run(events.registry.messages, make_client(), make_message())

    assert calls == ["first"]


async def test_the_gate_refuses_the_handler_and_stops_the_registry(monkeypatch):
    calls = []

    async def refuse(client, event, handler):
        return False

    monkeypatch.setattr(events, "enforce", refuse)

    @events.on_message(lambda client, message: True)
    async def first(client, message):
        calls.append("first")

    @events.on_message(lambda client, message: True)
    async def second(client, message):
        calls.append("second")

    await events.registry.run(events.registry.messages, make_client(), make_message())

    assert calls == []


def test_the_requirement_decorator_keeps_the_source_order():
    @requirement(kind="admin", permission="ban_users")
    @requirement(kind="sudo_plus")
    async def handler(client, message):
        return None

    assert [spec["kind"] for spec in handler.requirements] == ["admin", "sudo_plus"]


async def test_gate_chat_action_runs_and_cancels():
    from Mikobot.utils import gate

    sent_actions = []

    async def fake_send_chat_action(chat_id, action):
        sent_actions.append((chat_id, action))

    client = make_client()
    client.send_chat_action = fake_send_chat_action
    message = make_message()

    @requirement(chat_action="typing")
    async def handler(c, m):
        pass

    assert await gate.enforce(client, message, handler) is True
    assert len(sent_actions) >= 1
    assert sent_actions[0][0] == message.chat.id
