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
from time import monotonic

from cachetools import TTLCache
from sqlalchemy import BigInteger, Column, String
from sqlalchemy.dialects.postgresql import insert as pg_insert

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Approvals(BASE):
    __tablename__ = "approval"
    chat_id = Column(String(14), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)

    def __init__(self, chat_id, user_id):
        self.chat_id = str(chat_id)  # ensure string
        self.user_id = user_id

    def __repr__(self):
        return "<ᴀᴘᴘʀᴏᴠᴇ %s>" % self.user_id


Approvals.__table__.create(bind=ENGINE, checkfirst=True)

APPROVE_INSERTION_LOCK = threading.RLock()

# is_approved runs once per message from antiflood, the blacklist, locks and
# warn filters, so the same row was read four times per update. Only hits are
# cached: a miss stays a query, so a user approved by another path is picked up
# within the TTL rather than being remembered as absent.
APPROVED_TTL = 30.0
APPROVED = TTLCache(maxsize=16384, ttl=APPROVED_TTL, timer=monotonic)


def _approval_key(chat_id, user_id):
    return str(chat_id), int(user_id)


def _remember_approved(key) -> None:
    # TTLCache is not thread safe and the helpers run on reused worker threads.
    with APPROVE_INSERTION_LOCK:
        APPROVED[key] = True


@unit_of_work_guard
def approve(chat_id, user_id):
    key = _approval_key(chat_id, user_id)
    with APPROVE_INSERTION_LOCK:
        # One statement, and a second approve is a no-op instead of an
        # IntegrityError on the composite primary key.
        SESSION.execute(
            pg_insert(Approvals.__table__)
            .values(chat_id=key[0], user_id=key[1])
            .on_conflict_do_nothing()
        )
        SESSION.commit()
    _remember_approved(key)


@unit_of_work_guard
def is_approved(chat_id, user_id):
    key = _approval_key(chat_id, user_id)
    if key in APPROVED:
        return True
    try:
        row = SESSION.get(Approvals, key)
        if row:
            _remember_approved(key)
        return row
    finally:
        SESSION.close()


@unit_of_work_guard
def disapprove(chat_id, user_id):
    key = _approval_key(chat_id, user_id)
    with APPROVE_INSERTION_LOCK:
        disapprove_user = SESSION.get(Approvals, key)
        APPROVED.pop(key, None)
        if disapprove_user:
            SESSION.delete(disapprove_user)
            SESSION.commit()
            return True
        else:
            SESSION.close()
            return False


@unit_of_work_guard
def list_approved(chat_id):
    try:
        return (
            SESSION.query(Approvals)
            .filter(Approvals.chat_id == str(chat_id))
            .order_by(Approvals.user_id.asc())
            .all()
        )
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with APPROVE_INSERTION_LOCK:
        rows = (
            SESSION.query(Approvals)
            .filter(Approvals.chat_id == str(old_chat_id))
            .all()
        )
        for row in rows:
            row.chat_id = str(new_chat_id)
        SESSION.commit()
        for key in [key for key in APPROVED if key[0] == str(old_chat_id)]:
            APPROVED.pop(key, None)
