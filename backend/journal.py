"""Persist claims before side effects; uncertain requests are never blindly retried."""
import json
import threading
from config import STORE_DIR

PATH = STORE_DIR / "actions.json"
_lock = threading.RLock()


def _read():
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {}


def get(key):
    with _lock:
        return _read().get(key)


def _write(data):
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PATH)


def claim(key, state="processing"):
    with _lock:
        data = _read()
        if key in data:
            return False
        data[key] = {"state": state}
        _write(data)
        return True


def put(key, state, **extra):
    with _lock:
        data = _read()
        data[key] = {"state": state, **extra}
        _write(data)
