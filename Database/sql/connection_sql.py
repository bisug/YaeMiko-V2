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
from typing import Union

from sqlalchemy import BigInteger, Boolean, Column, String, UnicodeText

from Database.sql import BASE, ENGINE, SESSION


class ChatAccessConnectionSettings(BASE):
    __tablename__ = "access_connection"
    chat_id = Column(String(14), primary_key=True)
    allow_connect_to_chat = Column(Boolean, default=True)

    def __init__(self, chat_id, allow_connect_to_chat):
        self.chat_id = str(chat_id)
        self.allow_connect_to_chat = str(allow_connect_to_chat)

    def __repr__(self):
        return "<ᴄʜᴀᴛ ᴀᴄᴄᴇss sᴇᴛᴛɪɴɢs ({}) is {}>".format(
            self.chat_id,
            self.allow_connect_to_chat,
        )


class Connection(BASE):
    __tablename__ = "connection"
    user_id = Column(BigInteger, primary_key=True)
    chat_id = Column(String(14))

    def __init__(self, user_id, chat_id):
        self.user_id = user_id
        self.chat_id = str(chat_id)  # Ensure String


class ConnectionHistory(BASE):
    __tablename__ = "connection_history"
    user_id = Column(BigInteger, primary_key=True)
    chat_id = Column(String(14), primary_key=True)
    chat_name = Column(UnicodeText)
    conn_time = Column(BigInteger)

    def __init__(self, user_id, chat_id, chat_name, conn_time):
        self.user_id = user_id
        self.chat_id = str(chat_id)
        self.chat_name = str(chat_name)
        self.conn_time = int(conn_time)

    def __repr__(self):
        return "<ᴄᴏɴɴᴇᴄᴛɪᴏɴ ᴜsᴇʀ {} ʜɪsᴛᴏʀʏ {}>".format(self.user_id, self.chat_id)


ChatAccessConnectionSettings.__table__.create(bind=ENGINE, checkfirst=True)
Connection.__table__.create(bind=ENGINE, checkfirst=True)
ConnectionHistory.__table__.create(bind=ENGINE, checkfirst=True)

CHAT_ACCESS_LOCK = threading.RLock()
CONNECTION_INSERTION_LOCK = threading.RLock()
CONNECTION_HISTORY_LOCK = threading.RLock()

HISTORY_CONNECT = {}


def allow_connect_to_chat(chat_id: Union[str, int]) -> bool:
    try:
        chat_setting = SESSION.get(ChatAccessConnectionSettings, str(chat_id))
        if chat_setting:
            return chat_setting.allow_connect_to_chat
        return False
    finally:
        SESSION.close()


def set_allow_connect_to_chat(chat_id: Union[int, str], setting: bool):
    with CHAT_ACCESS_LOCK:
        chat_setting = SESSION.get(ChatAccessConnectionSettings, str(chat_id))
        if not chat_setting:
            chat_setting = ChatAccessConnectionSettings(chat_id, setting)

        chat_setting.allow_connect_to_chat = setting
        SESSION.add(chat_setting)
        SESSION.commit()


def connect(user_id, chat_id):
    with CONNECTION_INSERTION_LOCK:
        connection = SESSION.get(Connection, int(user_id))
        if connection is None:
            connection = Connection(int(user_id), chat_id)
            SESSION.add(connection)
        else:
            connection.chat_id = str(chat_id)
        SESSION.commit()
        return True


def get_connected_chat(user_id):
    try:
        return SESSION.get(Connection, int(user_id))
    finally:
        SESSION.close()


def curr_connection(chat_id):
    try:
        return SESSION.query(Connection).filter(Connection.chat_id == str(chat_id)).first()
    finally:
        SESSION.close()


def disconnect(user_id):
    with CONNECTION_INSERTION_LOCK:
        disconnect = SESSION.get(Connection, int(user_id))
        if disconnect:
            SESSION.delete(disconnect)
            SESSION.commit()
            return True
        SESSION.close()
        return False


def add_history_conn(user_id, chat_id, chat_name):
    global HISTORY_CONNECT
    with CONNECTION_HISTORY_LOCK:
        user_id = int(user_id)
        chat_id = str(chat_id)
        history = HISTORY_CONNECT.setdefault(user_id, {})
        old = SESSION.get(ConnectionHistory, (user_id, chat_id))
        evicted = None
        if chat_id not in history and len(history) >= 5:
            evicted = min(history, key=lambda key: history[key]["conn_time"])
            oldest = SESSION.get(ConnectionHistory, (user_id, evicted))
            if oldest:
                SESSION.delete(oldest)

        conn_time = int(time.time())
        if old:
            old.chat_name = chat_name
            old.conn_time = conn_time
        else:
            SESSION.add(ConnectionHistory(user_id, chat_id, chat_name, conn_time))
        SESSION.commit()
        if evicted:
            history.pop(evicted, None)
        history[chat_id] = {
            "chat_name": chat_name,
            "chat_id": chat_id,
            "conn_time": conn_time,
        }


def get_history_conn(user_id):
    with CONNECTION_HISTORY_LOCK:
        return dict(HISTORY_CONNECT.setdefault(int(user_id), {}))


def clear_history_conn(user_id):
    global HISTORY_CONNECT
    user_id = int(user_id)
    with CONNECTION_HISTORY_LOCK:
        SESSION.query(ConnectionHistory).filter(
            ConnectionHistory.user_id == user_id
        ).delete(synchronize_session=False)
        SESSION.commit()
        HISTORY_CONNECT[user_id] = {}
    return True


def __load_user_history():
    global HISTORY_CONNECT
    try:
        qall = SESSION.query(ConnectionHistory).all()
        HISTORY_CONNECT = {}
        for x in qall:
            check = HISTORY_CONNECT.get(x.user_id)
            if check is None:
                HISTORY_CONNECT[x.user_id] = {}
            HISTORY_CONNECT[x.user_id][x.chat_id] = {
                "chat_name": x.chat_name,
                "chat_id": x.chat_id,
                "conn_time": x.conn_time,
            }
    finally:
        SESSION.close()


__load_user_history()
