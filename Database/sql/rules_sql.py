import threading

from sqlalchemy import Column, String, UnicodeText, distinct, func, select

from Database.sql import (
    BASE,
    SESSION,
    ensure_columns,
    run_migration,
    unit_of_work_guard,
)


class Rules(BASE):
    __tablename__ = "rules"
    chat_id = Column(String, primary_key=True)
    rules = Column(UnicodeText, default="")
    rules_button = Column(UnicodeText, default="")

    def __init__(self, chat_id):
        self.chat_id = str(chat_id)
        self.rules_button = ""

    def __repr__(self):
        return f"<Chat {self.chat_id} rules: {self.rules}>"


class ChatSetting(BASE):
    """Small key/value store for per-chat choices with no table of their own."""

    __tablename__ = "chat_settings"
    chat_id = Column(String, primary_key=True)
    key = Column(String(64), primary_key=True)
    value = Column(UnicodeText, default="")

    def __init__(self, chat_id, key, value=""):
        self.chat_id = str(chat_id)
        self.key = key
        self.value = value


def _ensure_columns() -> None:
    ensure_columns("rules", Rules)


run_migration(_ensure_columns)


INSERTION_LOCK = threading.RLock()


@unit_of_work_guard
def set_rules(chat_id, rules_text):
    with INSERTION_LOCK:
        rules = SESSION.get(Rules, str(chat_id))
        if not rules:
            rules = Rules(str(chat_id))
        rules.rules = rules_text

        SESSION.add(rules)
        SESSION.commit()


@unit_of_work_guard
def get_rules(chat_id):
    rules = SESSION.get(Rules, str(chat_id))
    ret = ""
    if rules:
        ret = rules.rules

    SESSION.close()
    return ret


@unit_of_work_guard
def get_rules_button(chat_id):
    try:
        row = SESSION.get(Rules, str(chat_id))
        return row.rules_button if row and row.rules_button else ""
    finally:
        SESSION.close()


@unit_of_work_guard
def set_rules_button(chat_id, label):
    with INSERTION_LOCK:
        row = SESSION.get(Rules, str(chat_id))
        if not row:
            row = Rules(str(chat_id))
        row.rules_button = label
        SESSION.add(row)
        SESSION.commit()


@unit_of_work_guard
def reset_rules_button(chat_id):
    set_rules_button(chat_id, "")


@unit_of_work_guard
def get_chat_setting(chat_id, key, default=""):
    try:
        row = SESSION.get(ChatSetting, (str(chat_id), key))
        return row.value if row else default
    finally:
        SESSION.close()


@unit_of_work_guard
def set_chat_setting(chat_id, key, value):
    with INSERTION_LOCK:
        SESSION.merge(ChatSetting(str(chat_id), key, str(value)))
        SESSION.commit()


@unit_of_work_guard
def num_chats():
    try:
        return SESSION.scalar(select(func.count(distinct(Rules.chat_id))))
    finally:
        SESSION.close()


@unit_of_work_guard
def migrate_chat(old_chat_id, new_chat_id):
    with INSERTION_LOCK:
        chat = SESSION.get(Rules, str(old_chat_id))
        if chat:
            chat.chat_id = str(new_chat_id)
        settings = SESSION.scalars(
            select(ChatSetting).where(ChatSetting.chat_id == str(old_chat_id))
        ).all()
        for setting in settings:
            setting.chat_id = str(new_chat_id)
        SESSION.commit()
