from __future__ import annotations

import pytest

from Mikobot import events
from Mikobot.utils.gate import chain, requirement


@pytest.fixture(autouse=True)
def clean_registry():
    """The registry is global, so every test starts and ends empty."""
    lists = (
        events.registry.messages,
        events.registry.callbacks,
        events.registry.inline_queries,
        events.registry.join_requests,
        events.registry.chat_member_updates,
    )
    for registry in lists:
        registry.clear()
    yield
    for registry in lists:
        registry.clear()


async def test_a_matching_handler_runs(mock_client, sample_message):
    calls = []

    @events.on_message(lambda client, message: True)
    async def handler(client, message):
        calls.append(message)

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == [sample_message]


async def test_a_handler_that_does_not_match_never_runs(mock_client, sample_message):
    calls = []

    @events.on_message(lambda client, message: False)
    async def handler(client, message):
        calls.append(message)

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == []


async def test_a_chained_handler_lets_the_next_one_run(mock_client, sample_message):
    calls = []

    @events.on_message(lambda client, message: True)
    async def first(client, message):
        calls.append("first")

    @events.on_message(lambda client, message: True)
    async def second(client, message):
        calls.append("second")

    chain(first)
    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["first", "second"]


async def test_a_handler_that_does_not_chain_stops_the_registry(
    mock_client, sample_message
):
    calls = []

    @events.on_message(lambda client, message: True)
    async def first(client, message):
        calls.append("first")

    @events.on_message(lambda client, message: True)
    async def second(client, message):
        calls.append("second")

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["first"]


async def test_the_gate_refuses_the_handler_and_stops_the_registry(
    monkeypatch, mock_client, sample_message
):
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

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == []


async def test_chained_handler_gate_refusal_continues_to_subsequent_handlers(
    monkeypatch, mock_client, sample_message
):
    calls = []

    @events.on_message(lambda client, message: True, chained=True)
    async def first(client, message):
        calls.append("first")

    @events.on_message(lambda client, message: True)
    async def second(client, message):
        calls.append("second")

    async def refuse_first_only(client, event, handler):
        return handler != first

    monkeypatch.setattr(events, "enforce", refuse_first_only)

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["second"]


def test_the_requirement_decorator_keeps_the_source_order():
    @requirement(kind="admin", permission="ban_users")
    @requirement(kind="sudo_plus")
    async def handler(client, message):
        return None

    assert [spec["kind"] for spec in handler.requirements] == ["admin", "sudo_plus"]


async def test_gate_chat_action_runs_and_cancels(mock_client, sample_message):
    from Mikobot.utils import gate

    sent_actions = []

    async def fake_send_chat_action(chat_id, action):
        sent_actions.append((chat_id, action))

    mock_client.send_chat_action = fake_send_chat_action

    @requirement(chat_action="typing")
    async def handler(c, m):
        pass

    assert await gate.enforce(mock_client, sample_message, handler) is True
    assert len(sent_actions) >= 1
    assert sent_actions[0][0] == sample_message.chat.id


async def test_chained_handler_exception_does_not_abort_subsequent_handlers(
    mock_client, sample_message
):
    calls = []

    @events.on_message(lambda client, message: True, chained=True)
    async def bad_chained_handler(client, message):
        calls.append("bad_chained")
        raise RuntimeError("Something failed in background check")

    @events.on_message(lambda client, message: True)
    async def target_command_handler(client, message):
        calls.append("command")

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["bad_chained", "command"]


async def test_unchained_handler_exception_stops_registry(mock_client, sample_message):
    calls = []

    @events.on_message(lambda client, message: True, chained=False)
    async def failing_command(client, message):
        calls.append("failing")
        raise RuntimeError("Command failed")

    @events.on_message(lambda client, message: True)
    async def next_command(client, message):
        calls.append("next")

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["failing"]


async def test_stop_propagation_halts_all_handlers(mock_client, sample_message):
    from pyrogram import StopPropagation

    calls = []

    @events.on_message(lambda client, message: True, chained=True)
    async def gatekeeper(client, message):
        calls.append("gatekeeper")
        raise StopPropagation

    @events.on_message(lambda client, message: True)
    async def command(client, message):
        calls.append("command")

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["gatekeeper"]


async def test_filter_exception_does_not_abort_registry(mock_client, sample_message):
    calls = []

    def broken_filter(client, message):
        raise AttributeError("'Client' object has no attribute 'lower'")

    @events.on_message(broken_filter, chained=True)
    async def handler_with_broken_filter(client, message):
        calls.append("broken_filter_ran")

    @events.on_message(lambda client, message: True)
    async def normal_command(client, message):
        calls.append("normal_command")

    await events.registry.run(events.registry.messages, mock_client, sample_message)

    assert calls == ["normal_command"]
