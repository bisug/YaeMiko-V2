"""Per-chat and per-user scratch storage.

PTB's ``PicklePersistence`` exposed ``context.chat_data`` and
``context.user_data`` and wrote them to ``ptb_persistence.pickle``. aiogram's
Dispatcher has no equivalent dict (its storage is FSM-only), so the federation
keeps its own copy in the same file and plugins read it from here.
"""

import os
import pickle


class DataStore:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data: dict = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.filepath, "rb") as handle:
                loaded = pickle.load(handle)
        except (OSError, EOFError, pickle.UnpicklingError):
            loaded = {}
        self.data = loaded if isinstance(loaded, dict) else {}
        self.data.setdefault("chat_data", {})
        self.data.setdefault("user_data", {})

    @property
    def chat_data(self) -> dict:
        return self.data["chat_data"]

    @property
    def user_data(self) -> dict:
        return self.data["user_data"]

    def save(self) -> None:
        tmp = f"{self.filepath}.tmp"
        try:
            with open(tmp, "wb") as handle:
                pickle.dump(self.data, handle)
            os.replace(tmp, self.filepath)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


def open_store(filepath: str) -> DataStore:
    return DataStore(filepath)
