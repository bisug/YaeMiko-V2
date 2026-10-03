"""Per-chat feature switches, shared by the welcome, antinsfw and nekomode plugins.

The Mongo collections these replace did not agree on what a missing row meant.
dwelcome and nekomode were opt-out: no row meant the feature was ON, and the
row recorded the chat that had turned it off. nsfw was opt-in: no row meant
OFF, and the row recorded the chat that had turned it on. One boolean column
covers both only if the default is per-feature, so it lives in DEFAULTS rather
than in the schema.
"""

import threading

from sqlalchemy import Boolean, Column, String

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard

WELCOME = "welcome"
NSFW = "nsfw"
NEKOMODE = "nekomode"
KARMA = "karma"
SANGMATA = "sangmata"

# Absent row means ON for welcome, nekomode, karma and sangmata; OFF for nsfw.
DEFAULTS = {
    WELCOME: True,
    NSFW: False,
    NEKOMODE: True,
    KARMA: True,
    SANGMATA: False,
}


class ChatToggle(BASE):
    __tablename__ = "chat_toggles"

    chat_id = Column(String(14), primary_key=True)
    feature = Column(String(16), primary_key=True)
    enabled = Column(Boolean, default=False)

    def __init__(self, chat_id, feature, enabled):
        self.chat_id = str(chat_id)
        self.feature = feature
        self.enabled = enabled


ChatToggle.__table__.create(bind=ENGINE, checkfirst=True)

INSERTION_LOCK = threading.RLock()


@unit_of_work_guard
def is_toggle_on(chat_id, feature):
    try:
        row = SESSION.get(ChatToggle, (str(chat_id), feature))
        if row is None:
            return DEFAULTS[feature]
        return bool(row.enabled)
    finally:
        SESSION.close()


@unit_of_work_guard
def set_toggle(chat_id, feature, enabled):
    with INSERTION_LOCK:
        SESSION.merge(ChatToggle(str(chat_id), feature, bool(enabled)))
        SESSION.commit()


def _feature_api(feature):
    """Build the three functions one feature needs, over the shared table.

    The Mongo module exposed nine functions with identical bodies; this keeps
    one implementation and three thin wrappers per feature.
    """

    def is_on(chat_id):
        return is_toggle_on(chat_id, feature)

    def turn_on(chat_id):
        set_toggle(chat_id, feature, True)

    def turn_off(chat_id):
        set_toggle(chat_id, feature, False)

    return is_on, turn_on, turn_off


is_dwelcome_on, dwelcome_on, dwelcome_off = _feature_api(WELCOME)
is_nsfw_on, nsfw_on, nsfw_off = _feature_api(NSFW)
is_nekomode_on, nekomode_on, nekomode_off = _feature_api(NEKOMODE)
is_karma_on, karma_on, karma_off = _feature_api(KARMA)
