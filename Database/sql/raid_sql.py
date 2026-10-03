"""
MIT License

Copyright (c) 2022 Aʙɪsʜɴᴏɪ

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import threading
import time
from collections import deque

from sqlalchemy import BigInteger, Boolean, Column, String, inspect, select, text

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

DEF_RAID_TIME = 60 * 60 * 6  # 6 hours, per the documented default
DEF_ACTION_TIME = 60 * 60  # 1 hour
DEF_AUTO_ANTIRAID = 0  # joins-per-minute threshold; 0 means disabled


class RaidChats(BASE):
    __tablename__ = "raid_chats"
    chat_id = Column(String(14), primary_key=True)
    # Absolute unix expiry rather than a bare flag: the raid has to end on its
    # own once the configured window is up, and a boolean cannot say when.
    raid_until = Column(BigInteger, default=0)
    raid_time = Column(BigInteger, default=DEF_RAID_TIME)
    action_time = Column(BigInteger, default=DEF_ACTION_TIME)
    auto_antiraid = Column(BigInteger, default=DEF_AUTO_ANTIRAID)
    notified = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)
        self.raid_until = 0
        self.raid_time = DEF_RAID_TIME
        self.action_time = DEF_ACTION_TIME
        self.auto_antiraid = DEF_AUTO_ANTIRAID
        self.notified = False

    def __repr__(self):
        return "<ʀᴀɪᴅ sᴇᴛᴛɪɴɢs ғᴏʀ %s>" % self.chat_id


RaidChats.__table__.create(bind=ENGINE, checkfirst=True)


def _ensure_columns() -> None:
    """Add the settings columns to a raid_chats table created by an older build.

    create(checkfirst=True) is a no-op when the table is already there, so an
    existing deployment keeps its original chat_id-only schema and every later
    SELECT of raid_until fails at runtime. Startup is the only place the
    difference is cheap to absorb.
    """
    inspector = inspect(ENGINE)
    if "raid_chats" not in inspector.get_table_names():
        return
    present = {column["name"] for column in inspector.get_columns("raid_chats")}
    with ENGINE.begin() as connection:
        for column in RaidChats.__table__.columns:
            if column.name in present:
                continue
            ddl = f'ALTER TABLE raid_chats ADD COLUMN "{column.name}" {column.type.compile(dialect=ENGINE.dialect)}'
            connection.execute(text(ddl))
            if column.default is not None and getattr(column.default, "arg", None) is not None:
                connection.execute(
                    text(
                        f'UPDATE raid_chats SET "{column.name}" = :value WHERE "{column.name}" IS NULL'
                    ),
                    {"value": column.default.arg},
                )


_ensure_columns()
INSERTION_LOCK = threading.RLock()

# chat_id -> deque of join timestamps inside the current window, used to decide
# when a join burst is large enough to trip autoantiraid.
JOIN_WINDOWS: dict = {}
JOIN_LOCK = threading.RLock()
JOIN_WINDOW_SECONDS = 60
MAX_JOIN_TRACK = 50


@unit_of_work_guard
def _row(chat_id):
    return SESSION.get(RaidChats, str(chat_id))


def _settings(chat_id):
    """(raid_until, raid_time, action_time, auto_antiraid), defaults when unset."""
    row = _row(chat_id)
    if not row:
        return (0, DEF_RAID_TIME, DEF_ACTION_TIME, DEF_AUTO_ANTIRAID)
    return (
        int(row.raid_until or 0),
        int(row.raid_time or DEF_RAID_TIME),
        int(row.action_time or DEF_ACTION_TIME),
        int(row.auto_antiraid or DEF_AUTO_ANTIRAID),
    )


@unit_of_work_guard
def is_raid(chat_id) -> bool:
    """True only while the raid window is still open.

    The expiry is checked here rather than by a background task, so a raid ends
    even if the process restarted after it was set.
    """
    try:
        raid_until, *_ = _settings(chat_id)
        return raid_until > int(time.time())
    finally:
        SESSION.close()


@unit_of_work_guard
def set_raid(chat_id, duration: int = None) -> None:
    """Enable the raid for `duration` seconds, or the chat's configured window."""
    with INSERTION_LOCK:
        _, raid_time, *_ = _settings(chat_id)
        seconds = int(duration) if duration else raid_time
        row = _row(chat_id)
        if not row:
            row = RaidChats(str(chat_id))
        row.raid_until = int(time.time()) + seconds
        row.notified = False
        SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def rem_raid(chat_id) -> None:
    """Disable the raid now, keeping the configured durations."""
    with INSERTION_LOCK:
        row = _row(chat_id)
        if row:
            row.raid_until = 0
            SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def set_raid_time(chat_id, seconds: int) -> None:
    with INSERTION_LOCK:
        row = _row(chat_id)
        if not row:
            row = RaidChats(str(chat_id))
        row.raid_time = int(seconds)
        SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def set_action_time(chat_id, seconds: int) -> None:
    with INSERTION_LOCK:
        row = _row(chat_id)
        if not row:
            row = RaidChats(str(chat_id))
        row.action_time = int(seconds)
        SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def set_auto_antiraid(chat_id, threshold: int) -> None:
    with INSERTION_LOCK:
        row = _row(chat_id)
        if not row:
            row = RaidChats(str(chat_id))
        row.auto_antiraid = max(0, int(threshold))
        SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def get_raid_setting(chat_id):
    """(is_active, raid_time, action_time, auto_antiraid) for the /antiraid view."""
    try:
        raid_until, raid_time, action_time, auto_antiraid = _settings(chat_id)
        return (
            raid_until > int(time.time()),
            raid_time,
            action_time,
            auto_antiraid,
        )
    finally:
        SESSION.close()


@unit_of_work_guard
def mark_notified(chat_id) -> None:
    """Record that the raid-alert was sent, so it is posted once per raid."""
    with INSERTION_LOCK:
        row = _row(chat_id)
        if row:
            row.notified = True
            SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def get_all_raid_chats():
    try:
        return [row.chat_id for row in SESSION.scalars(select(RaidChats)).all()]
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id) -> None:
    with INSERTION_LOCK:
        row = _row(old_chat_id)
        if not row:
            return
        if _row(new_chat_id):
            SESSION.delete(row)
        else:
            row.chat_id = str(new_chat_id)
            SESSION.add(row)
        SESSION.commit()


def record_join(chat_id) -> int:
    """Count joins in the last 60s and return that count.

    Bounded per chat so a long-running process cannot accumulate an unbounded
    deque for every group it has ever seen.
    """
    now = time.time()
    with JOIN_LOCK:
        window = JOIN_WINDOWS.setdefault(str(chat_id), deque())
        window.append(now)
        while window and window[0] <= now - JOIN_WINDOW_SECONDS:
            window.popleft()
        while len(window) > MAX_JOIN_TRACK:
            window.popleft()
        return len(window)


def clear_joins(chat_id) -> None:
    with JOIN_LOCK:
        JOIN_WINDOWS.pop(str(chat_id), None)
