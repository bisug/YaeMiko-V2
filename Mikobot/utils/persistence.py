"""Per-chat and per-user scratch storage.

PTB's ``PicklePersistence`` exposed ``context.chat_data`` and
``context.user_data`` and wrote them to ``ptb_persistence.pickle``. aiogram's
Dispatcher has no equivalent dict (its storage is FSM-only), so the federation
keeps its own copy in the same file and plugins read it from here.
"""

import os
import pickle
import time


# chat_data holds one entry per pending anonymous-admin confirmation, keyed by a
# random token. Entries are only removed when the button is clicked, so an admin
# who issues the command and walks away leaks one forever, and the whole store is
# rewritten to disk on every save. Anything older than this is dead: the token is
# a uuid4 prefix, so a stale one can never be pressed again.
TOKEN_TTL_SECONDS = 24 * 60 * 60


class TokenDict(dict):
    """A dict that remembers when each key was last written.

    The pending-confirmation keys are written and read by plugins as plain
    ``chat_data[key]`` / ``chat_data.get(key)``, so the timestamps live in a
    side table rather than wrapping the values. Changing the value type would
    break every reader, including the nested one in feds.py that reaches
    straight into chat_data[chat_id]["federation"].

    A key with no timestamp was written by an older build that predates this,
    or was loaded from such a file. Either way it is treated as expired.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stamps: dict = {}

    def _table(self) -> dict:
        """The stamp table, created on demand.

        Unpickling restores a dict subclass's items before its instance state,
        so __setitem__ can run while _stamps does not exist yet.
        """
        try:
            return self._stamps
        except AttributeError:
            self._stamps = {}
            return self._stamps

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self._table()[key] = time.monotonic()

    def __delitem__(self, key) -> None:
        super().__delitem__(key)
        self._table().pop(key, None)

    def pop(self, key, *args):
        self._table().pop(key, None)
        return super().pop(key, *args)

    def prune(self, ttl: float) -> int:
        """Drop keys whose last write is older than ttl. Returns how many went."""
        now = time.monotonic()
        stamps = self._table()
        stale = [
            key
            for key in list(self)
            if key not in stamps or now - stamps[key] > ttl
        ]
        for key in stale:
            del self[key]
        return len(stale)


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
        for section in ("chat_data", "user_data"):
            value = self.data.get(section)
            if not isinstance(value, dict):
                value = {}
            # monotonic() is per-boot, so a stamp read back from disk would be
            # meaningless. Every key is re-stamped as fresh instead: a restart
            # keeps pending confirmations alive, which is what the store did
            # before this, and pruning still bounds growth within a run.
            restored = TokenDict()
            for key, item in value.items():
                restored[key] = item
            self.data[section] = restored

    @property
    def chat_data(self) -> dict:
        return self.data["chat_data"]

    @property
    def user_data(self) -> dict:
        return self.data["user_data"]

    def save(self) -> None:
        for section in ("chat_data", "user_data"):
            if isinstance(self.data.get(section), TokenDict):
                self.data[section].prune(TOKEN_TTL_SECONDS)
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
