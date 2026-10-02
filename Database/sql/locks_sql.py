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

# New chat added -> setup permissions
import threading

from sqlalchemy import Boolean, Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Permissions(BASE):
    __tablename__ = "permissions"
    chat_id = Column(String(14), primary_key=True)
    # Booleans are for "is this locked", _NOT_ "is this allowed"
    audio = Column(Boolean, default=False)
    voice = Column(Boolean, default=False)
    contact = Column(Boolean, default=False)
    video = Column(Boolean, default=False)
    document = Column(Boolean, default=False)
    photo = Column(Boolean, default=False)
    sticker = Column(Boolean, default=False)
    gif = Column(Boolean, default=False)
    url = Column(Boolean, default=False)
    bots = Column(Boolean, default=False)
    forward = Column(Boolean, default=False)
    game = Column(Boolean, default=False)
    location = Column(Boolean, default=False)
    rtl = Column(Boolean, default=False)
    button = Column(Boolean, default=False)
    egame = Column(Boolean, default=False)
    inline = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)  # ensure string
        self.audio = False
        self.voice = False
        self.contact = False
        self.video = False
        self.document = False
        self.photo = False
        self.sticker = False
        self.gif = False
        self.url = False
        self.bots = False
        self.forward = False
        self.game = False
        self.location = False
        self.rtl = False
        self.button = False
        self.egame = False
        self.inline = False

    def __repr__(self):
        return "<ᴘᴇʀᴍɪssɪᴏɴs ғᴏʀ %s>" % self.chat_id


class AllowedItem(BASE):
    __tablename__ = "allowed_items"
    chat_id = Column(String(14), primary_key=True)
    # Which locktype this exemption applies to, e.g. "url" or "forward".
    lockable = Column(String(32), primary_key=True)
    # Domain, bot id, invite link or pack name. Stored lowercase so lookups
    # do not have to normalise on every message.
    item = Column(String(256), primary_key=True)

    def __init__(self, chat_id, lockable, item):
        self.chat_id = str(chat_id)
        self.lockable = lockable
        self.item = str(item).lower()

    def __repr__(self):
        return "<ᴀʟʟᴏᴡᴇᴅ %s %s ғᴏʀ %s>" % (self.lockable, self.item, self.chat_id)


class Restrictions(BASE):
    __tablename__ = "restrictions"
    chat_id = Column(String(14), primary_key=True)
    # Booleans are for "is this restricted", _NOT_ "is this allowed"
    messages = Column(Boolean, default=False)
    media = Column(Boolean, default=False)
    other = Column(Boolean, default=False)
    preview = Column(Boolean, default=False)

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)  # ensure string
        self.messages = False
        self.media = False
        self.other = False
        self.preview = False

    def __repr__(self):
        return "<ʀᴇsᴛʀɪᴄᴛɪᴏɴs ғᴏʀ %s>" % self.chat_id


# For those who faced database error, Just uncomment the
# line below and run bot for 1 time & remove that line!

Permissions.__table__.create(bind=ENGINE, checkfirst=True)
# Permissions.__table__.drop()
Restrictions.__table__.create(bind=ENGINE, checkfirst=True)
AllowedItem.__table__.create(bind=ENGINE, checkfirst=True)

PERM_LOCK = threading.RLock()
RESTR_LOCK = threading.RLock()


@unit_of_work_guard
def init_permissions(chat_id, reset=False):
    curr_perm = SESSION.get(Permissions, str(chat_id))
    if reset and curr_perm:
        SESSION.delete(curr_perm)
        SESSION.flush()
    perm = Permissions(str(chat_id))
    SESSION.add(perm)
    SESSION.commit()
    return perm


@unit_of_work_guard
def init_restrictions(chat_id, reset=False):
    curr_restr = SESSION.get(Restrictions, str(chat_id))
    if reset and curr_restr:
        SESSION.delete(curr_restr)
        SESSION.flush()
    restr = Restrictions(str(chat_id))
    SESSION.add(restr)
    SESSION.commit()
    return restr


@unit_of_work_guard
def update_lock(chat_id, lock_type, locked):
    with PERM_LOCK:
        curr_perm = SESSION.get(Permissions, str(chat_id))
        if not curr_perm:
            curr_perm = init_permissions(chat_id)

        if lock_type == "audio":
            curr_perm.audio = locked
        elif lock_type == "voice":
            curr_perm.voice = locked
        elif lock_type == "contact":
            curr_perm.contact = locked
        elif lock_type == "video":
            curr_perm.video = locked
        elif lock_type == "document":
            curr_perm.document = locked
        elif lock_type == "photo":
            curr_perm.photo = locked
        elif lock_type == "sticker":
            curr_perm.sticker = locked
        elif lock_type == "gif":
            curr_perm.gif = locked
        elif lock_type == "url":
            curr_perm.url = locked
        elif lock_type == "bots":
            curr_perm.bots = locked
        elif lock_type == "forward":
            curr_perm.forward = locked
        elif lock_type == "game":
            curr_perm.game = locked
        elif lock_type == "location":
            curr_perm.location = locked
        elif lock_type == "rtl":
            curr_perm.rtl = locked
        elif lock_type == "button":
            curr_perm.button = locked
        elif lock_type == "egame":
            curr_perm.egame = locked
        elif lock_type == "inline":
            curr_perm.inline = locked

        SESSION.add(curr_perm)
        SESSION.commit()


@unit_of_work_guard
def update_restriction(chat_id, restr_type, locked):
    with RESTR_LOCK:
        curr_restr = SESSION.get(Restrictions, str(chat_id))
        if not curr_restr:
            curr_restr = init_restrictions(chat_id)

        if restr_type == "messages":
            curr_restr.messages = locked
        elif restr_type == "media":
            curr_restr.media = locked
        elif restr_type == "other":
            curr_restr.other = locked
        elif restr_type == "previews":
            curr_restr.preview = locked
        elif restr_type == "all":
            curr_restr.messages = locked
            curr_restr.media = locked
            curr_restr.other = locked
            curr_restr.preview = locked
        SESSION.add(curr_restr)
        SESSION.commit()


@unit_of_work_guard
def is_locked(chat_id, lock_type):
    curr_perm = SESSION.get(Permissions, str(chat_id))
    SESSION.close()

    if not curr_perm:
        return False

    if lock_type == "sticker":
        return curr_perm.sticker
    if lock_type == "photo":
        return curr_perm.photo
    if lock_type == "audio":
        return curr_perm.audio
    if lock_type == "voice":
        return curr_perm.voice
    if lock_type == "contact":
        return curr_perm.contact
    if lock_type == "video":
        return curr_perm.video
    if lock_type == "document":
        return curr_perm.document
    if lock_type == "gif":
        return curr_perm.gif
    if lock_type == "url":
        return curr_perm.url
    if lock_type == "bots":
        return curr_perm.bots
    if lock_type == "forward":
        return curr_perm.forward
    if lock_type == "game":
        return curr_perm.game
    if lock_type == "location":
        return curr_perm.location
    if lock_type == "rtl":
        return curr_perm.rtl
    if lock_type == "button":
        return curr_perm.button
    if lock_type == "egame":
        return curr_perm.egame
    if lock_type == "inline":
        return curr_perm.inline


@unit_of_work_guard
def is_restr_locked(chat_id, lock_type):
    curr_restr = SESSION.get(Restrictions, str(chat_id))
    SESSION.close()

    if not curr_restr:
        return False

    if lock_type == "messages":
        return curr_restr.messages
    if lock_type == "media":
        return curr_restr.media
    if lock_type == "other":
        return curr_restr.other
    if lock_type == "previews":
        return curr_restr.preview
    if lock_type == "all":
        return (
            curr_restr.messages
            and curr_restr.media
            and curr_restr.other
            and curr_restr.preview
        )


@unit_of_work_guard
def get_locks(chat_id):
    try:
        return SESSION.get(Permissions, str(chat_id))
    finally:
        SESSION.close()


@unit_of_work_guard
def get_restr(chat_id):
    try:
        return SESSION.get(Restrictions, str(chat_id))
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with PERM_LOCK:
        perms = SESSION.get(Permissions, str(old_chat_id))
        if perms:
            perms.chat_id = str(new_chat_id)
        SESSION.commit()

    with RESTR_LOCK:
        rest = SESSION.get(Restrictions, str(old_chat_id))
        if rest:
            rest.chat_id = str(new_chat_id)
        SESSION.commit()


@unit_of_work_guard
def allow_item(chat_id, lockable, item):
    """Add an exemption for one locktype. Repeatable and case-insensitive."""
    with PERM_LOCK:
        SESSION.merge(AllowedItem(str(chat_id), lockable, str(item).lower()))
        SESSION.commit()


@unit_of_work_guard
def unallow_item(chat_id, lockable, item):
    with PERM_LOCK:
        row = SESSION.get(AllowedItem, (str(chat_id), lockable, str(item).lower()))
        if row:
            SESSION.delete(row)
            SESSION.commit()


@unit_of_work_guard
def rmallow_all(chat_id):
    with PERM_LOCK:
        for row in SESSION.query(AllowedItem).filter_by(chat_id=str(chat_id)).all():
            SESSION.delete(row)
        SESSION.commit()


@unit_of_work_guard
def list_allowed(chat_id):
    """Every exemption for a chat, as (lockable, item) pairs."""
    try:
        return [
            (row.lockable, row.item)
            for row in SESSION.query(AllowedItem).filter_by(chat_id=str(chat_id)).all()
        ]
    finally:
        SESSION.close()


@unit_of_work_guard
def allowed_for(chat_id, lockable):
    """The item list for one locktype, as a set for fast membership checks."""
    try:
        return {
            row.item
            for row in SESSION.query(AllowedItem)
            .filter_by(chat_id=str(chat_id), lockable=lockable)
            .all()
        }
    finally:
        SESSION.close()
