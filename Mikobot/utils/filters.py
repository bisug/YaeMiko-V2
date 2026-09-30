"""Shared aiogram filters for the chat-type checks PTB spelled as filters.ChatType.

PTB had `filters.ChatType.GROUPS` meaning "group or supergroup" and it appeared
44 times across 24 plugins. The magic-filter equivalents are short enough to
name once here, so each ported plugin imports a symbol instead of repeating a
set literal.
"""

from aiogram import F
from aiogram.enums import ChatType

PRIVATE = F.chat.type == ChatType.PRIVATE
GROUPS = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
GROUP_AND_SUPERGROUP = GROUPS
CHANNELS = F.chat.type == ChatType.CHANNEL
SENDERS = F.chat.type == ChatType.SENDER
NOT_GROUPS = F.chat.type.in_({ChatType.PRIVATE, ChatType.CHANNEL})
