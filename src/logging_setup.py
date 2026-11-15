"""Structured JSON-lines logging (stdlib only).

One line per pipeline request. Raw free text is never logged by default: only its length and
a short hash. API keys are never logged.
"""
from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import os
import threading
from typing import Any, Dict

_lock = threading.Lock()
_loggers: Dict[str, logging.Logger] = {}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "payload", None)
        if payload is None:
            payload = {"message": record.getMessage()}
        return json.dumps(payload, sort_keys=True, default=str)


def get_logger(log_file: str, max_bytes: int = 1_000_000, backups: int = 3) -> logging.Logger:
    """Return a rotating JSON-lines logger for log_file (created lazily, cached per path)."""
    key = os.path.abspath(log_file)
    with _lock:
        if key in _loggers:
            return _loggers[key]
        os.makedirs(os.path.dirname(key), exist_ok=True)
        logger = logging.getLogger("vibify." + hashlib.sha1(key.encode()).hexdigest()[:10])
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.handlers.RotatingFileHandler(
            key, maxBytes=max_bytes, backupCount=backups, encoding="utf-8")
        handler.setFormatter(_JsonFormatter())
        logger.handlers = [handler]
        _loggers[key] = logger
        return logger


def close_loggers() -> None:
    """Close all file handlers (needed on Windows before deleting temp dirs)."""
    with _lock:
        for lg in _loggers.values():
            for h in list(lg.handlers):
                h.close()
                lg.removeHandler(h)
        _loggers.clear()


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def text_fingerprint(text: str, log_raw: bool = False) -> Dict[str, Any]:
    """What we record about free text: length and short hash (raw text only if explicitly enabled)."""
    info: Dict[str, Any] = {"text_len": len(text), "text_hash": short_hash(text)}
    if log_raw:
        info["text_raw"] = text
    return info


def log_request(config, payload: Dict[str, Any]) -> None:
    """Write one structured request line. Never raises."""
    try:
        logger = get_logger(config.log_file, config.log_max_bytes, config.log_backups)
        logger.info("request", extra={"payload": payload})
    except Exception:  # logging must never break a request
        pass


def append_jsonl(path: str, obj: Dict[str, Any]) -> None:
    """Append one JSON object to a .jsonl file (creating the directory). Never raises."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, sort_keys=True, default=str) + "\n")
    except Exception:
        pass
