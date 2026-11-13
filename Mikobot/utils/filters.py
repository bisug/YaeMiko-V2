"""Shared filters for the chat-type checks PTB spelled as filters.ChatType.

PTB had `filters.ChatType.GROUPS` meaning "group or supergroup" and it appeared
44 times across 24 plugins. The kurigram equivalents are short enough to name
once here, so each ported plugin imports a symbol instead of repeating a
filter expression.
"""

from pyrogram import filters

PRIVATE = filters.private
GROUPS = filters.group
GROUP_AND_SUPERGROUP = GROUPS
CHANNELS = filters.channel
SENDERS = filters.private
NOT_GROUPS = filters.private | filters.channel
