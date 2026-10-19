"""
Append-only event log stored as JSON Lines (store/events.jsonl).
Keeps the most recent MAX_EVENTS entries; older ones are trimmed automatically.
"""

import json
import threading
import re
from datetime import datetime
from pathlib import Path

from config import STORE_DIR

MAX_EVENTS = 500
_lock = threading.Lock()
_LOG_PATH = STORE_DIR / "events.jsonl"


def redact(value):
    """Keep signed image credentials out of UI events and persisted event logs."""
    if isinstance(value, dict):
        secrets = {"sessionid", "cookie", "authorization", "api_key", "apikey", "lessontoken", "set-auth"}
        return {key: "[redacted]" if key.lower() in secrets else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?i)(auth_key|access_token|api_key|sessionid|signature|ticket|token)=([^&\s\"<>]+)", r"\1=[redacted]", value)
    return value


def sanitize_storage():
    if not _LOG_PATH.exists(): return
    with _lock:
        records = [redact(json.loads(line)) for line in _LOG_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        temporary = _LOG_PATH.with_suffix(".tmp")
        temporary.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
        temporary.replace(_LOG_PATH)


def append(event: dict) -> None:
    record = redact({**event, "logged_at": datetime.now().isoformat(timespec="seconds")})
    with _lock:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        _trim()


def load_recent(n: int = 50) -> list:
    if not _LOG_PATH.exists():
        return []
    with _lock:
        lines = [l.strip() for l in _LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [redact(json.loads(l)) for l in lines[-n:]]


def _trim() -> None:
    lines = [l for l in _LOG_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lines) > MAX_EVENTS:
        _LOG_PATH.write_text("\n".join(lines[-MAX_EVENTS:]) + "\n", encoding="utf-8")
