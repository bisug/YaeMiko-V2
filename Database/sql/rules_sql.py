import threading

from sqlalchemy import Column, String, UnicodeText, distinct, func, select

from Database.sql import BASE, ENGINE, SESSION, unit_of_work_guard


class Rules(BASE):
    __tablename__ = "rules"
    chat_id = Column(String(14), primary_key=True)
    rules = Column(UnicodeText, default="")

    def __init__(self, chat_id):
        self.chat_id = chat_id

    def __repr__(self):
        return "<Chat {} rules: {}>".format(self.chat_id, self.rules)


Rules.__table__.create(bind=ENGINE, checkfirst=True)

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
        SESSION.commit()
