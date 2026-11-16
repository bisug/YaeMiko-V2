"""The single shared logger for the application.

Every module imports :data:`LOGGER` from here. Configuration is read once, at
import time, from two environment variables:

``LOG_LEVEL``
    One of ``debug``, ``info`` (default), ``warn``, ``error``. The legacy
    ``warning``, ``critical`` and ``notset`` names are still accepted.
``LOG_FORMAT``
    ``json`` (default, for production) or ``text`` (human readable, for local
    development). An unrecognised value falls back to ``json``.

Output goes through a queue so a slow stderr or disk never blocks the caller.
Both the stream and the rotating file sink share the same formatter and the
same redaction rules.
"""

from __future__ import annotations

import atexit
import copy
import json
import logging
import logging.handlers
import os
import queue
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

SERVICE_NAME = "yaemiko"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "NOTSET": logging.NOTSET,
}
_DEFAULT_LEVEL = logging.INFO

# Bot tokens appear in Telegram API URLs, which HTTP clients like to log.
_TOKEN_RE = re.compile(r"\bbot\d+:[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")

# Extra fields carrying these names are replaced before a record is emitted.
_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "bot_token",
        "api_hash",
        "api_key",
        "password",
        "passwd",
        "secret",
        "client_secret",
        "authorization",
        "auth",
        "credentials",
        "access_token",
        "refresh_token",
        "cookie",
        "session",
        "email",
        "phone",
    }
)

# Standard LogRecord attributes; everything else on a record is caller context.
_RESERVED_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)

# A request/update identifier, set by the dispatcher for the life of one update.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def _redact(text: str) -> str:
    text = _TOKEN_RE.sub("bot<redacted>", text)
    return _BEARER_RE.sub("Bearer <redacted>", text)


@contextmanager
def correlation_scope(value: object):
    """Attach an identifier to every log entry emitted in this scope."""
    token = correlation_id.set(str(value))
    try:
        yield
    finally:
        correlation_id.reset(token)


class RedactingFormatter(logging.Formatter):
    """Human readable formatter that strips secrets from the rendered line."""

    def format(self, record: logging.LogRecord) -> str:
        return _redact(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per entry: timestamp, level, message and context."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower().replace("warning", "warn"),
            "message": record.getMessage(),
            "service": SERVICE_NAME,
            "correlation_id": getattr(record, "correlation_id", ""),
        }
        for key, value in vars(record).items():
            if key in _RESERVED_KEYS or key.startswith("_"):
                continue
            payload[key] = "<redacted>" if key in _SENSITIVE_KEYS else value
        if record.exc_text:
            payload["exception"] = record.exc_text
        elif record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return _redact(json.dumps(payload, default=str, ensure_ascii=False))


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.service = SERVICE_NAME
        record.correlation_id = correlation_id.get()
        return True


class _QueueHandler(logging.handlers.QueueHandler):
    """QueueHandler that keeps the traceback, which the stock one drops."""

    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        prepared = copy.copy(record)
        prepared.msg = record.getMessage()
        prepared.args = None
        prepared.exc_info = None
        prepared.exc_text = (
            logging.Formatter().formatException(record.exc_info)
            if record.exc_info
            else None
        )
        prepared.stack_info = None
        return prepared


def _level_from_env() -> int:
    return _LEVELS.get(
        os.environ.get("LOG_LEVEL", "INFO").strip().upper(), _DEFAULT_LEVEL
    )


def _build_formatter() -> logging.Formatter:
    if os.environ.get("LOG_FORMAT", "json").strip().lower() == "text":
        return RedactingFormatter(
            "%(asctime)s %(levelname)s [%(service)s] [%(correlation_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    return JsonFormatter()


def configure_logging() -> logging.Logger:
    """Attach the shared sinks to the root logger exactly once."""
    formatter = _build_formatter()
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    sinks = [stream]
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            "Logs.txt", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        # A container filesystem may allow stdout but not a writable log file.
        pass
    else:
        file_handler.setFormatter(formatter)
        sinks.append(file_handler)

    listener = logging.handlers.QueueListener(
        queue.Queue(-1), *sinks, respect_handler_level=True
    )
    listener.start()
    atexit.register(listener.stop)

    handler = _QueueHandler(listener.queue)
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    if not any(isinstance(h, logging.handlers.QueueHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(_level_from_env())

    # These libraries emit full Telegram API URLs (with the token) at INFO.
    for name in ("pyrogram", "pyrate_limiter"):
        logging.getLogger(name).setLevel(logging.ERROR)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    return root


configure_logging()
LOGGER = logging.getLogger(SERVICE_NAME)
