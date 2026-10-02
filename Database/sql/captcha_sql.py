"""CAPTCHA settings and per-user solve state.

A user is only ever asked once per chat; leaving and rejoining does not reset
that, so a "solved" row is the record that matters. A kick does reset it,
which is the documented way for an admin to re-test the flow.

Answers in flight are held in memory rather than the database: they are
short-lived, single-use, and there is no reason to keep them once a
challenge is answered or expires.
"""

import threading
import time

from sqlalchemy import BigInteger, Boolean, Column, String, UnicodeText

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

MODE_BUTTON = "button"
MODE_TEXT = "text"
MODE_MATH = "math"
MODE_TEXT2 = "text2"
MODES = (MODE_BUTTON, MODE_TEXT, MODE_MATH, MODE_TEXT2)

DEF_KICK_TIME = 5 * 60
DEF_MUTE_TIME = 0  # 0 means stay muted until solved
MIN_KICK_TIME = 5 * 60
MAX_KICK_TIME = 24 * 60 * 60

DEF_BUTTON_TEXT = "I'm not a bot"


class CaptchaSettings(BASE):
    __tablename__ = "captcha_settings"
    chat_id = Column(String(14), primary_key=True)
    enabled = Column(Boolean, default=False)
    mode = Column(String(16), default=MODE_BUTTON)
    # Plaintext only: the button label is shown inside an InlineKeyboardButton,
    # where no markup is rendered.
    button_text = Column(UnicodeText, default=DEF_BUTTON_TEXT)
    kick_enabled = Column(Boolean, default=False)
    kick_time = Column(BigInteger, default=DEF_KICK_TIME)
    mute_time = Column(BigInteger, default=DEF_MUTE_TIME)
    show_rules = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)
        self.enabled = False
        self.mode = MODE_BUTTON
        self.button_text = DEF_BUTTON_TEXT
        self.kick_enabled = False
        self.kick_time = DEF_KICK_TIME
        self.mute_time = DEF_MUTE_TIME
        self.show_rules = False

    def __repr__(self):
        return "<ᴄᴀᴘᴛᴄʜᴀ %s for %s>" % (self.mode, self.chat_id)


class CaptchaSolved(BASE):
    __tablename__ = "captcha_solved"
    chat_id = Column(String(14), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)

    def __init__(self, chat_id, user_id):
        self.chat_id = str(chat_id)
        self.user_id = user_id

    def __repr__(self):
        return "<ᴄᴀᴘᴛᴄʜᴀ ѕᴏʟᴠᴇᴅ %s in %s>" % (self.user_id, self.chat_id)


CaptchaSettings.__table__.create(bind=ENGINE, checkfirst=True)
CaptchaSolved.__table__.create(bind=ENGINE, checkfirst=True)

SETTINGS_LOCK = threading.RLock()
SOLVED_LOCK = threading.RLock()

_cache: dict = {}


@unit_of_work_guard
def _row(chat_id):
    return SESSION.get(CaptchaSettings, str(chat_id))


@unit_of_work_guard
def _update(chat_id, **fields) -> None:
    with SETTINGS_LOCK:
        row = _row(chat_id)
        if row is None:
            row = CaptchaSettings(str(chat_id))
        for name, value in fields.items():
            setattr(row, name, value)
        SESSION.add(row)
        SESSION.commit()
        _cache.pop(str(chat_id), None)


@unit_of_work_guard
def get_settings(chat_id):
    """Settings dict with defaults when the chat has never configured any."""
    key = str(chat_id)
    if key in _cache:
        return dict(_cache[key])
    try:
        row = _row(key)
    finally:
        SESSION.close()
    if row is None:
        return {
            "enabled": False,
            "mode": MODE_BUTTON,
            "button_text": DEF_BUTTON_TEXT,
            "kick_enabled": False,
            "kick_time": DEF_KICK_TIME,
            "mute_time": DEF_MUTE_TIME,
            "show_rules": False,
        }
    entry = {
        "enabled": bool(row.enabled),
        "mode": row.mode or MODE_BUTTON,
        "button_text": row.button_text or DEF_BUTTON_TEXT,
        "kick_enabled": bool(row.kick_enabled),
        "kick_time": int(row.kick_time or DEF_KICK_TIME),
        "mute_time": int(row.mute_time or 0),
        "show_rules": bool(row.show_rules),
    }
    _cache[key] = entry
    return dict(entry)


def set_enabled(chat_id, enabled: bool) -> None:
    _update(chat_id, enabled=bool(enabled))


def set_mode(chat_id, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    _update(chat_id, mode=mode)


def set_button_text(chat_id, text: str) -> None:
    _update(chat_id, button_text=text)


def set_kick_enabled(chat_id, enabled: bool) -> None:
    _update(chat_id, kick_enabled=bool(enabled))


def set_kick_time(chat_id, seconds: int) -> None:
    _update(chat_id, kick_time=int(seconds))


def set_mute_time(chat_id, seconds: int) -> None:
    # 0 keeps users muted until they solve, which is the recommended setting.
    _update(chat_id, mute_time=max(0, int(seconds)))


def set_show_rules(chat_id, enabled: bool) -> None:
    _update(chat_id, show_rules=bool(enabled))


@unit_of_work_guard
def has_solved(chat_id, user_id) -> bool:
    try:
        return (
            SESSION.get(CaptchaSolved, (str(chat_id), user_id)) is not None
        )
    finally:
        SESSION.close()


@unit_of_work_guard
def mark_solved(chat_id, user_id) -> None:
    with SOLVED_LOCK:
        if not has_solved(chat_id, user_id):
            SESSION.add(CaptchaSolved(str(chat_id), user_id))
            SESSION.commit()


@unit_of_work_guard
def reset_solved(chat_id, user_id) -> None:
    """Forget a solve, which is what a kick does so the user is asked again."""
    with SOLVED_LOCK:
        row = SESSION.get(CaptchaSolved, (str(chat_id), user_id))
        if row is not None:
            SESSION.delete(row)
            SESSION.commit()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id) -> None:
    with SETTINGS_LOCK, SOLVED_LOCK:
        settings = SESSION.get(CaptchaSettings, str(old_chat_id))
        if settings is not None:
            if SESSION.get(CaptchaSettings, str(new_chat_id)) is not None:
                SESSION.delete(settings)
            else:
                settings.chat_id = str(new_chat_id)
                SESSION.add(settings)
        for row in (
            SESSION.query(CaptchaSolved)
            .filter(CaptchaSolved.chat_id == str(old_chat_id))
            .all()
        ):
            SESSION.delete(row)
        SESSION.commit()
        _cache.pop(str(old_chat_id), None)
        _cache.pop(str(new_chat_id), None)
