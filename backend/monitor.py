import asyncio
import logging
import threading
import time
import event_log
from config import get_course_config, make_headers, api_url, http_request
from lesson import Lesson
from runtime import get_runtime, can_signin

logger = logging.getLogger(__name__)
URL_ON_LESSON = "https://{domain}/api/v3/classroom/on-lesson-upcoming-exam"


class Monitor:
    def __init__(self, sessionid, event_queue, on_session_expired=None):
        self.sessionid = sessionid
        self.event_queue = event_queue
        self._on_session_expired = on_session_expired
        self._active_lessons = {}
        self._finished = set()
        self._lock = threading.RLock()
        self._running = False
        self._thread = None
        self._loop = None
        self._stop = threading.Event()
        self.last_attempt = None
        self.last_success = None
        self.last_error = None
        self.discovered = []
        self.state = "stopped"

    def start(self, loop):
        if self._running: return
        self._loop = loop
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="monitor")
        self._thread.start()

    def stop(self):
        self._running = False
        self.state = "stopped"
        self._stop.set()
        with self._lock: lessons = list(self._active_lessons.values())
        for lesson in lessons: lesson.stop_lesson()
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=5)

    def get_active_lessons(self):
        with self._lock: return [lesson.status() for lesson in self._active_lessons.values()]

    def health(self):
        interval = get_runtime()["poll_interval"]
        age = time.time() - self.last_success if self.last_success else None
        alive = bool(self._thread and self._thread.is_alive())
        return {"running": self._running, "thread_alive": alive,
                "state": self.state, "last_attempt": self.last_attempt, "last_success": self.last_success,
                "last_error": self.last_error, "poll_age_seconds": round(age, 1) if age is not None else None,
                "discovery_healthy": bool(self._running and alive and age is not None and age < interval + 30 and not self.last_error),
                "discovered": self.discovered, "lessons": self.get_active_lessons()}

    def _poll_once(self):
        self.last_attempt = time.time()
        r = http_request("GET", api_url(URL_ON_LESSON), headers=make_headers(self.sessionid), retries=2)
        if r.status_code in (401, 403):
            self._expire()
            return
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            # Distinguish temporary business errors from actual login expiry by verifying user info.
            user = http_request("GET", api_url("https://{domain}/api/v3/user/basic-info"), headers=make_headers(self.sessionid), retries=1)
            body = user.json()
            if user.status_code in (401, 403) or body.get("code") != 0 or not (body.get("data") or {}).get("id"):
                self._expire()
                return
            raise ValueError("开课接口业务异常，用户登录仍有效")
        lessons = data["data"]["onLessonClassrooms"]
        self.discovered = [{"lessonid": item["lessonId"], "classroomid": str(item["classroomId"]), "name": item.get("courseName", "")} for item in lessons]
        self.last_success = time.time()
        self.last_error = None
        self.state = "watching" if lessons else "waiting"
        self._emit("monitor", {"status": self.state, "message": f"发现循环正常，本轮 {len(lessons)} 节开课；模式 {get_runtime()['mode']}"})
        self._sync_lessons(lessons)

    def _expire(self):
        self.state = "login_expired"
        self._running = False
        with self._lock: lessons = list(self._active_lessons.values())
        for lesson in lessons: lesson.stop_lesson()
        self._emit("session_expired", {"message": "服务器登录验证失效；监听暂停，请重新扫码"})
        if self._on_session_expired: self._on_session_expired()

    def _run(self):
        while self._running:
            try: self._poll_once()
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.state = "degraded"
                self._emit("monitor", {"status": "error", "message": f"发现接口临时失败：{self.last_error}；稍后重试"})
            if self._stop.wait(get_runtime()["poll_interval"]): break

    def _sync_lessons(self, lesson_list):
        incoming = {item["lessonId"] for item in lesson_list}
        # Never re-enter a lesson that explicitly announced lessonfinished while still listed by discovery.
        self._finished.intersection_update(incoming)
        with self._lock: active = list(self._active_lessons.items())
        for lid, lesson in active:
            if lesson._finished: self._finished.add(lid)
            if lid not in incoming or not can_signin(lesson.classroomid) or lesson._finished or lesson._stop.is_set():
                lesson.stop_lesson()
                with self._lock: self._active_lessons.pop(lid, None)
                self._emit("lesson_end", {"lessonid": lid, "message": "课堂已结束或实验范围已关闭；发现循环继续"})
        for item in lesson_list:
            lid = item["lessonId"]
            if not can_signin(item["classroomId"]) or lid in self._finished: continue
            with self._lock:
                if lid in self._active_lessons: continue
                lesson = Lesson({"lessonid": lid, "lessonname": item.get("courseName", "Unknown"), "classroomid": item["classroomId"]}, self.sessionid, get_course_config(str(item["classroomId"])), self._emit)
                self._active_lessons[lid] = lesson
            self._emit("lesson_start", {"lessonid": lid, "lesson": lesson.lessonname, "message": "已发现选中班级开课，准备签到和连接"})
            threading.Thread(target=self._lesson_thread, args=(lesson,), daemon=True, name=f"lesson-{lid}").start()

    def _lesson_thread(self, lesson):
        try: lesson.start_lesson()
        except Exception as exc:
            lesson.connection_state = "error"
            self._emit("connection", {"lessonid": lesson.lessonid, "status": "error", "message": f"课堂线程异常：{type(exc).__name__}"})
        finally:
            lesson._running = False
            # Keep failed entries visible; do not launch endless retry threads or duplicate check-ins.

    def _emit(self, event_type, data):
        event = event_log.redact({"type": event_type, **data})
        logger.info("%s %s", event_type, data.get("message", data.get("status", "")))
        event_log.append(event)
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.event_queue.put(event), self._loop)
