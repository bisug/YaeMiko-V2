# aiogram to kurigram migration

The bot spoke the Bot API through aiogram. It now speaks MTProto through
kurigram. This file is the contract the port follows: every plugin is
converted against it, and the conversion is checked by the test suite.

## The client

`Mikobot.app` is the kurigram `Client`. It is the only Telegram client: there
is no `bot` object and no `dp` dispatcher any more.

```python
from Mikobot import app
```

## Handlers

Handlers are registered with the decorators in `Mikobot.events`, and they are
called the kurigram way, `handler(client, update)`.

```python
from pyrogram import filters
from Mikobot.events import on_message


@on_message(filters.command("ping"))
async def ping(client, message):
    await message.reply_text("pong")
```

A handler that must let the next matching handler run as well is chained:

```python
@on_message(filters.command("locks"), chained=True)
async def locks(client, message): ...
```

`chained=True` is what the old `chain(handler)` wrapper did. It is not a
wrapper any more: the registry in `Mikobot.events` walks the handlers in
registration order and stops at the first one that is not chained.

The permission decorators are unchanged and still tag the handler:

```python
from Mikobot.plugins.helper_funcs.chat_status import check_admin


@check_admin(only_dev=True)
@on_message(filters.command("ping"))
async def ping(client, message): ...
```

## Filters

| aiogram | kurigram |
| --- | --- |
| `Command("x")` | `filters.command("x")` |
| `CommandObject` | `message.command`, a list: `message.command[0]` is the command, the rest are the arguments |
| `F.text` | `filters.text` |
| `F.text.regexp(r"...")` | `filters.regex(r"...")` |
| `F.chat.type == ChatType.PRIVATE` | `filters.private` |
| `F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})` | `filters.group` |
| `F.chat.type == ChatType.CHANNEL` | `filters.channel` |
| `F.data == "x"` | `filters.regex(r"^x$")` |
| `F.data.startswith("x")` | `filters.regex(r"^x")` |
| `F.data.regexp(r"...")` | `filters.regex(r"...")` |
| `F.photo` | `filters.photo` |
| `F.sticker` | `filters.sticker` |
| `F.new_chat_members` | `filters.new_chat_members` |
| `F.left_chat_member` | `filters.left_chat_member` |
| `F.update.migrate` | `filters.migrate_to_chat_id \| filters.migrate_from_chat_id` |

`Mikobot.utils.filters` keeps the shared chat-type filters: `PRIVATE`,
`GROUPS`, `GROUP_AND_SUPERGROUP`, `CHANNELS`, `SENDERS`, `NOT_GROUPS`.

## Messages

| aiogram | kurigram |
| --- | --- |
| `message.answer(text)` | `message.reply_text(text)` |
| `message.answer_photo(...)` | `message.reply_photo(...)` |
| `message.answer_document(...)` | `message.reply_document(...)` |
| `message.answer_sticker(...)` | `message.reply_sticker(...)` |
| `message.answer_video(...)` | `message.reply_video(...)` |
| `message.answer_voice(...)` | `message.reply_voice(...)` |
| `message.answer_audio(...)` | `message.reply_audio(...)` |
| `message.reply(text=...)` | `message.reply_text(text=...)` |
| `message.edit_text(...)` | `message.edit_text(...)` |
| `message.delete()` | `message.delete()` |
| `message.download(...)` | `client.download_media(...)` |
| `message.from_user` | `message.from_user` |
| `message.reply_to_message` | `message.reply_to_message` |
| `message.migrate_to_chat_id` | `message.migrate_to_chat_id` |

`message.answer` has no counterpart in kurigram: `reply_text` is the text
reply, and every other media has its own `reply_*`.

## Client calls

| aiogram | kurigram |
| --- | --- |
| `bot.send_message(...)` | `client.send_message(...)` |
| `bot.get_chat(...)` | `client.get_chat(...)` |
| `bot.get_chat_member(...)` | `client.get_chat_member(...)` |
| `bot.get_chat_member_count(...)` | `client.get_chat_members_count(...)` |
| `bot.get_chat_administrators(...)` | `client.get_chat_members(chat_id, filter=ChatMembersFilter.ADMINISTRATORS)`, an async generator |
| `bot.ban_chat_member(...)` | `client.ban_chat_member(...)` |
| `bot.unban_chat_member(...)` | `client.unban_chat_member(...)` |
| `bot.restrict_chat_member(...)` | `client.restrict_chat_member(chat_id, user_id, permissions)` |
| `bot.promote_chat_member(...)` | `client.promote_chat_member(...)` |
| `bot.set_chat_permissions(...)` | `client.set_chat_permissions(chat_id, permissions)` |
| `bot.set_chat_title(...)` | `client.set_chat_title(...)` |
| `bot.set_chat_description(...)` | `client.set_chat_description(...)` |
| `bot.set_chat_photo(...)` | `client.set_chat_photo(chat_id, file=...)` |
| `bot.delete_chat_photo(...)` | `client.delete_chat_photo(...)` |
| `bot.set_chat_administrator_custom_title(...)` | `client.set_administrator_title(...)` |
| `bot.set_chat_menu_button(...)` | `client.set_chat_menu_button(...)` |
| `bot.pin_chat_message(...)` | `client.pin_chat_message(...)` |
| `bot.unpin_chat_message(...)` | `client.unpin_chat_message(...)` |
| `bot.unpin_all_chat_messages(...)` | `client.unpin_all_chat_messages(...)` |
| `bot.create_forum_topic(...)` | `client.create_forum_topic(...)` |
| `bot.edit_forum_topic(...)` | `client.edit_forum_topic(...)` |
| `bot.create_chat_invite_link(...)` | `client.create_invite_link(...)` |
| `bot.edit_chat_invite_link(...)` | `client.edit_invite_link(...)` |
| `bot.revoke_chat_invite_link(...)` | `client.revoke_invite_link(...)` |
| `bot.export_chat_invite_link(...)` | `client.export_chat_invite_link(...)` |
| `bot.approve_chat_join_request(...)` | `client.approve_chat_join_request(...)` |
| `bot.decline_chat_join_request(...)` | `client.decline_chat_join_request(...)` |
| `bot.delete_message(...)` | `client.delete_messages(chat_id, message_ids)` |
| `bot.answer_callback_query(...)` | `client.answer_callback_query(...)` |
| `bot.get_sticker_set(...)` | `client.get_sticker_set(...)` |
| `bot.leave_chat(...)` | `client.leave_chat(...)` |

## Types and errors

| aiogram | kurigram |
| --- | --- |
| `aiogram.types.Message` | `pyrogram.types.Message` |
| `aiogram.types.CallbackQuery` | `pyrogram.types.CallbackQuery` |
| `aiogram.types.ChatPermissions` | `pyrogram.types.ChatPermissions` |
| `aiogram.types.LinkPreviewOptions` | `pyrogram.types.LinkPreviewOptions` |
| `aiogram.types.MessageEntity` | `pyrogram.types.MessageEntity` |
| `aiogram.types.InlineKeyboardButton` | `pyrogram.types.InlineKeyboardButton` |
| `aiogram.types.InlineKeyboardMarkup` | `pyrogram.types.InlineKeyboardMarkup` |
| `aiogram.types.BufferedInputFile` | a file path, or `pyrogram.types.InputFile` |
| `aiogram.enums.ParseMode` | `pyrogram.enums.ParseMode` |
| `aiogram.enums.ChatType` | `pyrogram.enums.ChatType` |
| `aiogram.enums.ChatMemberStatus` | `pyrogram.enums.ChatMemberStatus` |
| `aiogram.enums.ButtonStyle` | `pyrogram.enums.ButtonStyle` |
| `aiogram.exceptions.TelegramAPIError` | `pyrogram.errors.RPCError` |

A chat member's status is an enum now, not a string: `ChatMemberStatus.OWNER`
and `ChatMemberStatus.ADMINISTRATOR` replace `"creator"` and
`"administrator"`. The administrator rights live in `member.privileges`, not
on the member itself, and `Mikobot.plugins.helper_funcs.chat_status.granted`
reads them.

## What kurigram cannot do

The Bot API has a few endpoints MTProto does not expose:

- `ban_chat_sender_chat` and `unban_chat_sender_chat`
- `set_chat_sticker_set`
- `unpin_all_general_forum_topic_messages`
- `set_chat_administrator_custom_title` (kurigram calls it
  `set_administrator_title`)

Where a plugin needs one of these, the raw MTProto function is used instead
(`pyrogram.raw.functions.channels.BlockChannel` and friends), and where
MTProto has no equivalent at all, the command says so instead of pretending
to work.
