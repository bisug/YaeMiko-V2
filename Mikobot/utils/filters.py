"""Shared filters for chat-type checks.

``GROUPS`` selects group or supergroup chats.
"""

from pyrogram import filters

PRIVATE = filters.private
GROUPS = filters.group
CHANNELS = filters.channel
