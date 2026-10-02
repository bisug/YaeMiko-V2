"""Bot-to-bot access control.

Telegram does not deliver one bot's messages to another unless "bot to bot
communication" is enabled for the receiving bot in @BotFather, so most groups
will never see this fire at all. Where it does, the default is to ignore bot
commands entirely.

Three modes, per chat:
  off    bots cannot run commands (default)
  admin  only bots that are admins in the chat may
  all    any bot may

A separate review gate covers the commands that change settings. A bot with
admin rights can be talked into running one by anyone who can prompt it, so
those are shown to a human first unless review is switched off.
"""

import threading

from sqlalchemy import Boolean, Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

MODE_OFF = "off"
MODE_ADMIN = "admin"
MODE_ALL = "all"
MODES = (MODE_OFF, MODE_ADMIN, MODE_ALL)

#: Commands that change configuration, and so go through review when run by a bot.
SETTING_COMMANDS = frozenset(
    {
        "lock", "unlock", "setflood", "setfloodmode", "setfloodtimer", "clearflood",
        "addblacklist", "unblacklist", "blacklistmode", "blocklistdelete",
        "silentactions", "antispam", "gban", "ungban",
        "mute", "unmute", "tmute", "dmute", "dtmute",
        "ban", "unban", "tban", "dban", "sban", "kick", "dkick",
        "allowlist", "rmallowlist", "rmallowlistall",
        "setwelcome", "resetwelcome", "setgoodbye", "resetgoodbye", "welcomemute",
        "cleanservice", "nocleanservice", "cleanservicetypes", "cleanwelcome",
        "antiraid", "raidtime", "raidactiontime", "autoantiraid",
        "setrules", "clearrules", "import", "export", "reset",
        "promote", "demote", "fullpromote", "title", "adminlist", "admincache",
        "setlog", "unsetlog", "logchannel",
        "newtopic", "renametopic", "closetopic", "reopentopic", "deletetopic",
        "setactiontopic",
    }
)


class BotToBot(BASE):
    __tablename__ = "bot_to_bot"
    chat_id = Column(String(14), primary_key=True)
    mode = Column(String(16), default=MODE_OFF)
    skip_review = Column(Boolean, default=False)
    # Bot ids allowed to run command triggers in this chat, independent of mode.
    allowed = Column(String, default="")

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)
        self.mode = MODE_OFF
        self.skip_review = False
        self.allowed = ""

    def __repr__(self):
        return "<ʙᴏᴛ ᴛᴏ ʙᴏᴛ %s for %s>" % (self.mode, self.chat_id)


BotToBot.__table__.create(bind=ENGINE, checkfirst=True)
INSERTION_LOCK = threading.RLock()

_cache: dict = {}


@unit_of_work_guard
def _mutate(chat_id, **fields) -> None:
    with INSERTION_LOCK:
        row = SESSION.get(BotToBot, str(chat_id))
        if row is None:
            row = BotToBot(str(chat_id))
        for name, value in fields.items():
            setattr(row, name, value)
        SESSION.add(row)
        SESSION.commit()
        _cache[str(chat_id)] = {
            "mode": row.mode,
            "skip_review": bool(row.skip_review),
            "allowed": row.allowed or "",
        }


@unit_of_work_guard
def get_setting(chat_id):
    """(mode, skip_review, allowed_ids) with off/defaults when unset."""
    key = str(chat_id)
    if key in _cache:
        entry = _cache[key]
    else:
        try:
            row = SESSION.get(BotToBot, key)
        finally:
            SESSION.close()
        entry = (
            {
                "mode": row.mode,
                "skip_review": bool(row.skip_review),
                "allowed": row.allowed or "",
            }
            if row
            else {"mode": MODE_OFF, "skip_review": False, "allowed": ""}
        )
        _cache[key] = entry
    return entry["mode"], entry["skip_review"], {
        part for part in entry["allowed"].split(",") if part
    }


def set_mode(chat_id, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    _mutate(chat_id, mode=mode)


def set_skip_review(chat_id, enabled: bool) -> None:
    _mutate(chat_id, skip_review=bool(enabled))


def allow_bot(chat_id, user_id) -> None:
    _mode, _skip, allowed = get_setting(chat_id)
    allowed.add(str(user_id))
    _mutate(chat_id, allowed=",".join(sorted(allowed)))


def disallow_bot(chat_id, user_id) -> None:
    _mode, _skip, allowed = get_setting(chat_id)
    allowed.discard(str(user_id))
    _mutate(chat_id, allowed=",".join(sorted(allowed)))


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id) -> None:
    with INSERTION_LOCK:
        row = SESSION.get(BotToBot, str(old_chat_id))
        if row is None:
            return
        if SESSION.get(BotToBot, str(new_chat_id)) is not None:
            SESSION.delete(row)
        else:
            row.chat_id = str(new_chat_id)
            SESSION.add(row)
        SESSION.commit()
        _cache.pop(str(old_chat_id), None)
        _cache.pop(str(new_chat_id), None)
