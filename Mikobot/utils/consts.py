"""Telegram constants PTB exposed that aiogram does not.

``MessageLimit`` and ``ChatID.FAKE_CHANNEL`` have no aiogram counterpart, and
both are used for length checks and for spotting messages relayed by the
channel bot. The values are the Bot API's, so they are just stated here.
"""

from enum import IntEnum


class MessageLimit(IntEnum):
    MAX_TEXT_LENGTH = 4096


class ChatID(IntEnum):
    FAKE_CHANNEL = 136817688
    SERVICE_CHAT = 777000
    ANONYMOUS_ADMIN = 1087968824
