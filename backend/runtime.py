"""Local experiment switches. Observation never calls the check-in endpoint."""
import copy
import json
import threading
from pathlib import Path
from config import STORE_DIR

DEFAULTS = {
    "mode": "observe", "auto_signin": False, "submit_answers": False,
    "course_ids": [], "poll_interval": 30, "submit_reserve": 3,
    "ai_timeout": 90,
}
PATH = STORE_DIR / "runtime.json"
_lock = threading.RLock()


def get_runtime():
    with _lock:
        return {**copy.deepcopy(DEFAULTS), **(json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else {})}


def save_runtime(data):
    with _lock:
        value = {**get_runtime(), **{key: value for key, value in data.items() if key in DEFAULTS}}
        if value["mode"] not in ("observe", "trial", "auto"):
            raise ValueError("无效运行模式")
        if not isinstance(value["course_ids"], list):
            raise ValueError("课程范围必须是 classroom_id 列表")
        if any(type(value[key]) is not bool for key in ("auto_signin", "submit_answers")):
            raise ValueError("签到和提交开关必须是 true/false")
        value["course_ids"] = list(dict.fromkeys(str(cid) for cid in value["course_ids"]))
        for key, low, high in (("poll_interval", 10, 120), ("submit_reserve", 2, 15), ("ai_timeout", 5, 180)):
            value[key] = max(low, min(high, float(value[key])))
        if value["mode"] == "observe":
            value.update(auto_signin=False, submit_answers=False)
        if value["mode"] == "trial":
            value["submit_answers"] = False
        temporary = PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(PATH)
        return value


def selected(classroomid):
    return str(classroomid) in get_runtime()["course_ids"]


def can_signin(classroomid):
    cfg = get_runtime()
    return selected(classroomid) and cfg["mode"] in ("trial", "auto") and cfg["auto_signin"]


def can_submit(classroomid):
    cfg = get_runtime()
    return selected(classroomid) and cfg["mode"] == "auto" and cfg["submit_answers"]

