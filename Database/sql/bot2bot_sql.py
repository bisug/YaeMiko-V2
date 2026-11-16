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

from Database.sql import BASE, SESSION, unit_of_work_guard

MODE_OFF = "off"
MODE_ADMIN = "admin"
MODE_ALL = "all"
MODES = (MODE_OFF, MODE_ADMIN, MODE_ALL)

#: Commands that change configuration or chat state. A bot with admin rights
#: can be prompted by anyone, so every one of these needs a human in the loop.
#: Keep this list in step with the mutating commands in Mikobot/plugins.
SETTING_COMMANDS = frozenset(
    {
        "actiontopic",
        "addblacklist",
        "addblsticker",
        "adddemon",
        "addsudo",
        "addsupport",
        "addtiger",
        "addwarn",
        "addwhitelist",
        "addwolf",
        "admincache",
        "adminlist",
        "allowconnect",
        "allowlist",
        "antinsfw",
        "antiraid",
        "antispam",
        "approval",
        "approve",
        "autoantiraid",
        "ban",
        "blacklistmode",
        "blocklistdelete",
        "blstickermode",
        "broadcast",
        "broadcastall",
        "broadcastgroups",
        "broadcastusers",
        "captcha",
        "captchabuttons",
        "captchakick",
        "captchakicktime",
        "captchamode",
        "captchamutetime",
        "captcharules",
        "chatfed",
        "cleanservice",
        "cleanservicetypes",
        "cleanwelcome",
        "clear",
        "clearflood",
        "clearrules",
        "closetopic",
        "connect",
        "connection",
        "dban",
        "del",
        "deletefed",
        "deletetopic",
        "delfed",
        "demote",
        "disable",
        "disablemodule",
        "disconnect",
        "dkick",
        "dmute",
        "dtmute",
        "dwelcome",
        "enable",
        "enablemodule",
        "export",
        "fban",
        "fbroadcast",
        "fdemote",
        "filter",
        "fpromote",
        "fullpromote",
        "gban",
        "gcast",
        "goodbye",
        "import",
        "importfbans",
        "joinfed",
        "kang",
        "kick",
        "leavefed",
        "lock",
        "logchannel",
        "mute",
        "newfed",
        "newtopic",
        "nocleanservice",
        "nowarn",
        "nsfwscan",
        "pin",
        "pkang",
        "promote",
        "purge",
        "raidactiontime",
        "raidtime",
        "removeallfilters",
        "removeallnotes",
        "renamefed",
        "renametopic",
        "reopentopic",
        "reset",
        "resetcaptcha",
        "resetcaptchatext",
        "resetgoodbye",
        "resetwarn",
        "resetwarns",
        "resetwelcome",
        "rmallowlist",
        "rmallowlistall",
        "rmblsticker",
        "save",
        "sban",
        "setactiontopic",
        "setfedlog",
        "setflood",
        "setfloodmode",
        "setfloodtimer",
        "setfrules",
        "setgoodbye",
        "setlog",
        "setrules",
        "setwelcome",
        "silentactions",
        "spurge",
        "stop",
        "stopwarn",
        "strongwarn",
        "subfed",
        "tban",
        "title",
        "tmute",
        "unapprove",
        "unapproveall",
        "unban",
        "unbanall",
        "unblacklist",
        "unblsticker",
        "unfban",
        "ungban",
        "unlock",
        "unmute",
        "unmuteall",
        "unpin",
        "unpinall",
        "unsetfedlog",
        "unsetlog",
        "unsubfed",
        "warn",
        "warnlimit",
        "welcome",
        "welcomemute",
    }
)


class BotToBot(BASE):
    __tablename__ = "bot_to_bot"
    chat_id = Column(String, primary_key=True)
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
    return (
        entry["mode"],
        entry["skip_review"],
        {part for part in entry["allowed"].split(",") if part},
    )


def set_mode(chat_id, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    _mutate(chat_id, mode=mode)


def set_skip_review(chat_id, enabled: bool) -> None:
    _mutate(chat_id, skip_review=bool(enabled))


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
