import json
import logging
import threading
import time
from typing import Any
import websocket
import journal
from ai_provider import create_provider_from_entry
from config import (api_url, http_request, get_active_ai_key_entry, get_ai_config,
                    get_all_ai_key_entries, get_config, make_headers, get_domain)
from runtime import get_runtime, can_signin, can_submit

logger = logging.getLogger(__name__)
URL_WSS = "wss://{domain}/wsapp/"
URL_CHECKIN = "https://{domain}/api/v3/lesson/checkin"
URL_BASIC_INFO = "https://{domain}/api/v3/lesson/basic-info"
URL_PROBLEM_ANSWER = "https://{domain}/api/v3/lesson/problem/answer"
URL_PRESENTATION_FETCH = "https://{domain}/api/v3/lesson/presentation/fetch?presentation_id={presentation_id}"


class Lesson:
    def __init__(self, lesson_data, sessionid, course_config, on_event):
        self.lessonid = lesson_data["lessonid"]
        self.lessonname = lesson_data["lessonname"]
        self.classroomid = lesson_data["classroomid"]
        self.sessionid = sessionid
        self.course_config = course_config
        self.on_event = on_event
        self.headers = make_headers(sessionid)
        user = get_config().get("user", {})
        self.user_uid = user.get("id")
        self.user_uname = user.get("name")
        self.teacher_name = None
        self.auth = None
        self.wsapp = None
        self._running = False
        self._finished = False
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self.problems_ls = []
        self.presentation_ids = set()
        self.connected = False
        self.connected_at = None
        self.last_frame = None
        self.last_pong = None
        self.connection_state = "discovered"

    def _key(self, suffix):
        return f"{get_domain()}:{self.user_uid}:{self.lessonid}:{suffix}"

    def _event(self, kind, **data):
        self.on_event(kind, {"lesson": self.lessonname, "lessonid": self.lessonid, **data})

    def status(self):
        return {"lessonid": self.lessonid, "lessonname": self.lessonname,
                "classroomid": self.classroomid, "teacher_name": self.teacher_name,
                "connected": self.connected, "connection_state": self.connection_state,
                "last_frame": self.last_frame, "last_pong": self.last_pong,
                "cached_problems": len(self.problems_ls), "presentations": len(self.presentation_ids)}

    def _checkin(self):
        if not can_signin(self.classroomid):
            self._event("signin", status="skipped", message="自动签到已关闭，无法获取新的课堂连接令牌")
            return False
        key = self._key("signin")
        previous = journal.get(key)
        if previous:
            if previous["state"] == "accepted" and previous.get("auth"):
                self.auth = previous["auth"]
                if previous.get("authorization"):
                    self.headers["Authorization"] = previous["authorization"]
                self._event("signin", status="reused", message="复用本节已确认签到的令牌，未重复签到")
                return True
            self._event("signin", status="unknown", message="此前签到未获确认；停止自动重试，请核对真实考勤")
            return False
        if not journal.claim(key, "sent"):
            return False
        self._event("signin", status="sent", message="签到请求已发出，等待服务器确认")
        try:
            r = http_request("POST", api_url(URL_CHECKIN), headers=self.headers,
                             data=json.dumps({"source": 21, "lessonId": self.lessonid}), retries=1)
            result = r.json()
            token = (result.get("data") or {}).get("lessonToken")
            if not r.ok or result.get("code") != 0 or not token:
                journal.put(key, "rejected", code=result.get("code"))
                self._event("signin", status="rejected", message="服务器未确认签到或未返回课堂令牌", code=result.get("code"))
                return False
            if r.headers.get("Set-Auth"):
                self.headers["Authorization"] = "Bearer " + r.headers["Set-Auth"]
            self.auth = token
            journal.put(key, "accepted", auth=token, authorization=self.headers.get("Authorization"))
            self._event("signin", status="accepted", message="服务器 code=0，已获取课堂令牌")
            try:
                info = http_request("GET", api_url(URL_BASIC_INFO), headers=self.headers, retries=1).json()
                self.teacher_name = ((info.get("data") or {}).get("teacher") or {}).get("name")
            except Exception:
                self._event("connection", status="warning", message="签到已确认，教师信息暂不可用")
            return True
        except Exception as exc:
            journal.put(key, "unknown")
            self._event("signin", status="unknown", message=f"签到响应未知（{type(exc).__name__}），不重复发送")
            return False

    def start_lesson(self):
        self._running = True
        if not self._checkin():
            self.connection_state = "signin_blocked"
            self._running = False
            return
        backoff = 2
        while self._running and not self._stop.is_set():
            self.connection_state = "connecting"
            self.wsapp = websocket.WebSocketApp(
                url=api_url(URL_WSS), header=self.headers, on_open=self._on_open,
                on_message=self._on_message, on_error=self._on_error,
                on_close=self._on_close, on_pong=self._on_pong,
            )
            self.wsapp.run_forever(ping_interval=20, ping_timeout=8)
            self.connected = False
            if self._running and not self._stop.is_set():
                self.connection_state = "reconnecting"
                self._event("connection", status="reconnecting", message=f"连接中断，{backoff}秒后重连；保留题目处理记录")
                if self._stop.wait(backoff): break
                backoff = min(backoff * 2, 30)
        self._running = False
        self.connected = False

    def stop_lesson(self):
        self._running = False
        self.connected = False
        self._stop.set()
        if self.wsapp: self.wsapp.close()

    def _get_problems_from_presentation(self, presentation_id):
        r = http_request("GET", api_url(URL_PRESENTATION_FETCH, presentation_id=presentation_id), headers=self.headers, retries=1, timeout=3)
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0: raise ValueError("课件接口未返回成功")
        problems = []
        for slide in body["data"].get("slides", []):
            if isinstance(slide.get("problem"), dict):
                problems.append({**slide["problem"], "_cover": slide.get("cover", "")})
        self._event("problem_cache", status="ready", message=f"课件接口已成功返回，读取 {len(problems)} 道题目", presentationid=presentation_id)
        return problems

    def _add_problems(self, problems):
        with self._lock:
            values = {str(p["problemId"]): p for p in self.problems_ls}
            for p in problems:
                old = values.get(str(p["problemId"]), {})
                values[str(p["problemId"])] = {**old, **p}
            self.problems_ls = list(values.values())

    def _refresh_problems(self):
        for pid in list(self.presentation_ids):
            try:
                self._add_problems(self._get_problems_from_presentation(pid))
            except Exception as exc:
                self._event("problem_cache", status="retry", message=f"课件刷新失败：{type(exc).__name__}")

    @staticmethod
    def _valid_answer(problem, answer):
        kind = problem["problemType"]
        if kind == 5:
            return isinstance(answer, str) and bool(answer.strip()) and answer.strip().upper() not in ("UNANSWERABLE", "UNKNOWN", "N/A")
        options = [str(opt["key"]) for opt in problem.get("options", [])]
        if not isinstance(answer, list) or not answer or len(set(answer)) != len(answer): return False
        if any(a not in options for a in answer): return False
        if kind == 1: return len(answer) == 1
        if kind == 2: return True
        if kind == 3: return len(answer) <= int(problem.get("pollingCount") or 1)
        return False

    def _build_ai_answers(self, problem, deadline):
        cfg = get_ai_config()
        active = get_active_ai_key_entry()
        entries = get_all_ai_key_entries() if cfg.get("fallback_keys", True) else ([active] if active else [])
        if not entries: raise ValueError("未配置 AI API Key")
        for entry in entries:
            remaining = deadline - time.monotonic()
            if remaining <= 0: raise TimeoutError("AI 时间预算已耗尽")
            try:
                provider = create_provider_from_entry(entry)
                if provider is None: continue
                provider.prepare(problem, deadline - time.monotonic(), self.headers)
                if problem["problemType"] == 5:
                    answer = provider.answer_short(problem.get("_cover", ""))
                else:
                    answer = provider.answer_choice(problem.get("_cover", ""), [o["key"] for o in problem.get("options", [])], problem["problemType"])
                if not self._valid_answer(problem, answer): raise ValueError("AI 答案与题型或选项不匹配")
                return answer
            except Exception as exc:
                self._event("ai", status="failed", message=f"模型调用或解析失败：{type(exc).__name__}")
        raise ValueError("无有效 AI 答案；已跳过，不使用随机或空白答案")

    def _start_answer_for_problem(self, problemid, limit):
        # Reserve synchronously before starting a worker, including cache miss cases.
        key = self._key(f"problem:{problemid}")
        if not journal.claim(key):
            self._event("problem", problemid=problemid, status="duplicate", message="重复题目事件，未重复处理或提交")
            return
        received = time.monotonic()
        threading.Thread(target=self._resolve_answer, args=(problemid, limit, received, key), daemon=True, name=f"answer-{problemid}").start()

    def _resolve_answer(self, problemid, limit, received, key):
        cfg = get_runtime()
        cutoff = received + float(limit) if limit > 0 else None
        budget = min(received + cfg["ai_timeout"], cutoff - cfg["submit_reserve"]) if cutoff else received + cfg["ai_timeout"]
        def finish(state, message, **extra):
            journal.put(key, state)
            self._event("problem", problemid=problemid, status=state, message=message, **extra)
        try:
            problem = None
            for attempt in range(4):
                with self._lock:
                    problem = next((p.copy() for p in self.problems_ls if str(p["problemId"]) == str(problemid)), None)
                if problem: break
                if time.monotonic() >= budget: break
                self._event("problem_cache", problemid=problemid, status="retry", message="新题未在缓存中，重新拉取已知课件")
                self._refresh_problems()
                if attempt < 3: self._stop.wait(0.3)
            if not self._running: return finish("cancelled", "课堂已停止")
            if time.monotonic() >= budget: return finish("timeout", "时间不足，保留提交时间后已无 AI 预算")
            if not problem: return finish("cache_missing", "刷新后仍无题面，请手动处理；未静默漏题")
            kind = problem.get("problemType")
            if kind not in (1, 2, 3, 5): return finish("unsupported", f"题型 {kind} 未验证提交格式，跳过")
            if problem.get("result") is not None: return finish("already_answered", "课件显示已有作答，跳过")
            mode = self.course_config.get(f"type{kind}", "off")
            if mode != "ai": return finish("skipped", f"本次实验仅启用 AI/off；当前策略 {mode}，不使用随机、空白或队列回退")
            if not problem.get("_cover") and not any(problem.get(field) for field in ("content", "title", "body", "stem", "question")):
                return finish("incomplete", "题目没有课件图或可识别题干，不猜测作答")
            self._event("question", problemid=problemid, problemtype=kind, status="ready", question=problem, message="题面及选项已准备，开始 AI 试答")
            holder, done = {}, threading.Event()
            def call():
                try: holder["answer"] = self._build_ai_answers(problem, budget)
                except Exception as exc: holder["error"] = type(exc).__name__
                finally: done.set()
            threading.Thread(target=call, daemon=True, name=f"ai-{problemid}").start()
            while not done.wait(min(0.1, max(0, budget - time.monotonic()))):
                if not self._running: return finish("cancelled", "课堂停止，丢弃 AI 结果")
                if time.monotonic() >= budget: return finish("timeout", "AI 未在截止预算内返回；未提交")
            if not self._running: return finish("cancelled", "课堂停止，丢弃 AI 结果")
            if time.monotonic() >= budget: return finish("timeout", "AI 返回已超过截止预算；未提交")
            if "error" in holder: return finish("ai_failed", f"AI 未配置、调用或解析失败（{holder['error']}）；未提交")
            answer = holder.get("answer")
            if not self._valid_answer(problem, answer): return finish("invalid", "AI 答案无效，未提交")
            self._event("ai", problemid=problemid, status="valid", answers=answer, message="AI 答案格式有效，正确性仍需课堂验证")
            if not can_submit(self.classroomid):
                return finish("preview", "AI 试答已生成；答案提交开关关闭", answers=answer, problemtype=kind)
            delay = max(0, float(self.course_config.get("answer_delay_min", 1)))
            target = received + delay
            if self.course_config.get("answer_last5s") and cutoff:
                target = max(target, cutoff - cfg["submit_reserve"] - 1)
            while time.monotonic() < target:
                if self._stop.wait(min(0.1, target - time.monotonic())): return finish("cancelled", "课堂已停止")
                if cutoff and time.monotonic() >= cutoff - cfg["submit_reserve"]: break
            if not self._running or not can_submit(self.classroomid): return finish("cancelled", "运行开关或课堂状态已改变")
            if cutoff and time.monotonic() >= cutoff - cfg["submit_reserve"]:
                return finish("timeout", "提交前已无充足时间；未发送")
            self._submit_answer(problemid, kind, answer, cutoff, key)
        except Exception as exc:
            finish("error", f"题目处理异常：{type(exc).__name__}；未继续盲目提交")

    def _submit_answer(self, problemid, kind, answer, cutoff, key):
        result = {"content": answer, "pics": [{"pic": "", "thumb": ""}]} if kind == 5 else answer
        payload = {"problemId": problemid, "problemType": kind, "dt": int(time.time() * 1000), "result": result}
        journal.put(key, "sent")
        self._event("problem", problemid=problemid, problemtype=kind, status="sent", answers=answer, source="ai", message="答案请求已发出，尚未确认接受")
        try:
            remaining = min(8, cutoff - time.monotonic()) if cutoff else 8
            r = http_request("POST", api_url(URL_PROBLEM_ANSWER), headers=self.headers,
                             data=json.dumps(payload), retries=1, timeout=max(0.1, remaining / 2))
            body = r.json()
            state = "accepted" if r.ok and body.get("code") == 0 else "rejected"
            journal.put(key, state, code=body.get("code"))
            self._event("problem", problemid=problemid, problemtype=kind, status=state,
                        answers=answer, source="ai", code=body.get("code"), message=f"服务器响应：HTTP {r.status_code}, code={body.get('code')}")
        except Exception as exc:
            journal.put(key, "unknown")
            self._event("problem", problemid=problemid, status="unknown", message=f"提交结果未知（{type(exc).__name__}），不自动重发；请核对雨课堂")

    def _on_open(self, wsapp):
        wsapp.send(json.dumps({"op": "hello", "userid": self.user_uid, "role": "student", "auth": self.auth, "lessonid": self.lessonid}))

    def _on_error(self, wsapp, error):
        self._event("connection", status="error", message=f"课堂连接错误：{type(error).__name__}")

    def _on_close(self, wsapp, *args):
        self.connected = False

    def _on_pong(self, wsapp, data):
        self.last_pong = time.time()

    def _on_message(self, wsapp, message):
        try:
            self._handle_message(wsapp, json.loads(message))
        except Exception as exc:
            self._event("connection", status="error", message=f"课堂事件处理失败：{type(exc).__name__}")

    def _handle_message(self, wsapp, data):
        self.last_frame = time.time()
        op = data.get("op")
        logger.info("[WS lesson=%s] op=%s", self.lessonid, op)
        if op == "hello":
            self.connected = True
            self.connected_at = time.time()
            self.last_pong = self.connected_at
            self.connection_state = "connected"
            self._event("connection", status="connected", message="收到课堂 hello；WebSocket 已确认连接")
            for slide in data.get("timeline", []):
                if slide.get("type") == "slide" and slide.get("pres"): self.presentation_ids.add(slide["pres"])
            if data.get("presentation"): self.presentation_ids.add(data["presentation"])
            # Keep network fetches off the WebSocket receive thread.
            threading.Thread(target=self._refresh_problems, daemon=True).start()
        elif op == "unlockproblem":
            problem = data["problem"]
            self._event("problem_received", problemid=problem["sid"], limit=problem.get("limit", -1),
                        received_at=time.time(), message="收到新题，等待完整题面")
            self._start_answer_for_problem(problem["sid"], float(problem.get("limit", -1)))
        elif op == "lessonfinished":
            self._finished = True
            self.connection_state = "finished"
            self.stop_lesson()
            self._event("lesson_end", message="服务器通知下课，继续由发现循环等待下一节")
        elif op in ("presentationupdated", "presentationcreated", "showpresentation"):
            if data.get("presentation"):
                self.presentation_ids.add(data["presentation"])
                threading.Thread(target=self._refresh_problems, daemon=True).start()
        # Danmu/red packet side effects are disabled for this experiment.
