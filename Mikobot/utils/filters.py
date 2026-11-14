"""Shared filters for chat-type checks.

``GROUPS`` selects group or supergroup chats.
"""

from pyrogram import filters

PRIVATE = filters.private
GROUPS = filters.group
GROUP_AND_SUPERGROUP = GROUPS
CHANNELS = filters.channel
SENDERS = filters.private
NOT_GROUPS = filters.private | filters.channel
