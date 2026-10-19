"""Behavior tests: all classroom HTTP/WS calls are faked; no real attendance or answers."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import config
import event_log
import journal
import runtime
import lesson
import monitor
from ai_provider import parse_choice


class Response:
    def __init__(self, data=None, status=200, headers=None):
        self.data = data if data is not None else {"code": 0}
        self.status_code = status
        self.ok = status < 400
        self.headers = headers or {}
    def json(self): return self.data
    def raise_for_status(self):
        if not self.ok: raise RuntimeError("HTTP failure")


def until(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for observable behavior")


class ClassroomTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(config, "_CONFIG_PATH", root / "config.json"),
                        patch.object(runtime, "PATH", root / "runtime.json"),
                        patch.object(journal, "PATH", root / "actions.json"),
                        patch.object(event_log, "_LOG_PATH", root / "events.jsonl"),
                        patch("requests.request", side_effect=AssertionError("Real network forbidden in classroom simulation"))]
        for p in self.patches: p.start()
        config.save_config({**config._EMPTY_CONFIG, "user": {"id": 42, "name": "test"}})
        self.events = []
        self.instance = self.make_lesson()
        self.monitors = []
        runtime.save_runtime({"mode": "auto", "auto_signin": True, "submit_answers": True, "course_ids": ["101"]})

    def tearDown(self):
        self.instance.stop_lesson()
        for m in self.monitors: m.stop()
        time.sleep(0.03)
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def make_lesson(self):
        obj = lesson.Lesson({"lessonid": 11, "lessonname": "电路", "classroomid": 101}, "fake-session", {**config.DEFAULT_COURSE_CONFIG, "answer_delay_min": 0}, lambda kind, data: self.events.append({"type": kind, **data}))
        obj._running = True
        return obj

    def question(self, kind=1, pid=21):
        return {"problemId": pid, "problemType": kind, "content": "2+2=?", "options": [{"key": "A", "content": "3"}, {"key": "B", "content": "4"}], "_cover": "https://example.invalid/slide.png"}

    def answer(self, problem=None, ai=None, response=None, limit=30):
        problem = problem or self.question()
        self.instance._add_problems([problem])
        build = patch.object(self.instance, "_build_ai_answers", side_effect=ai if isinstance(ai, Exception) or callable(ai) else None, return_value=ai if ai is not None else ["B"])
        with build, patch.object(lesson, "http_request", return_value=response or Response()) as request:
            self.instance._start_answer_for_problem(problem["problemId"], limit)
            until(lambda: any(e.get("type") == "problem" and e.get("status") not in ("sent", "duplicate") for e in self.events))
            return request.call_args_list

    def statuses(self): return [e.get("status") for e in self.events]

    def test_observe_blocks_all_signin_and_submission(self):
        runtime.save_runtime({"mode": "observe", "auto_signin": True, "submit_answers": True})
        with patch.object(lesson, "http_request") as request:
            self.assertFalse(self.instance._checkin())
            request.assert_not_called()
        self.assertFalse(runtime.can_submit(101))
        self.assertFalse(runtime.get_runtime()["auto_signin"])

    def test_signin_only_once_and_server_token_required(self):
        reply = Response({"code": 0, "data": {"lessonToken": "fake-token"}}, headers={"Set-Auth": "fake-auth"})
        with patch.object(lesson, "http_request", side_effect=[reply, Response({"data": {}})]) as request:
            self.assertTrue(self.instance._checkin())
            self.assertTrue(self.instance._checkin())
            self.assertEqual(sum(c.args[0] == "POST" for c in request.call_args_list), 1)
        self.assertIn("accepted", self.statuses())
        self.assertIn("reused", self.statuses())

    def test_signin_rejection_not_success(self):
        with patch.object(lesson, "http_request", return_value=Response({"code": 9, "data": {}})):
            self.assertFalse(self.instance._checkin())
        self.assertIn("rejected", self.statuses())
        self.assertNotIn("accepted", self.statuses())

    def test_valid_ai_choice_submitted_and_accepted(self):
        calls = self.answer()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["retries"], 1)
        self.assertEqual(json.loads(calls[0].kwargs["data"])["result"], ["B"])
        self.assertIn("accepted", self.statuses())

    def test_ai_failure_no_random_or_blank_request(self):
        self.assertEqual(self.answer(ai=RuntimeError("failed")), [])
        self.assertIn("ai_failed", self.statuses())

    def test_missing_key_no_submit(self):
        self.instance._add_problems([self.question()])
        with patch.object(lesson, "http_request") as request:
            self.instance._start_answer_for_problem(21, 30)
            until(lambda: "ai_failed" in self.statuses())
            request.assert_not_called()

    def test_invalid_answer_does_not_submit(self):
        for answer in (["A", "B"], ["Z"], [], "", "B"):
            with self.subTest(answer=answer):
                self.events.clear()
                self.instance.problems_ls.clear()
                journal.PATH.unlink(missing_ok=True)
                self.assertEqual(self.answer(ai=answer), [])
                self.assertIn("invalid", self.statuses())

    def test_timeout_late_ai_is_discarded(self):
        def slow(*args): time.sleep(0.18); return ["B"]
        self.assertEqual(self.answer(ai=slow, limit=3.05), [])
        self.assertIn("timeout", self.statuses())
        time.sleep(0.2)
        self.assertNotIn("sent", self.statuses())

    def test_deadline_already_too_close(self):
        self.assertEqual(self.answer(limit=1), [])
        self.assertIn("timeout", self.statuses())

    def test_duplicate_events_and_new_object_after_reconnect_submit_once(self):
        self.answer()
        second = self.make_lesson()
        second._add_problems([self.question()])
        with patch.object(lesson, "http_request") as request:
            second._start_answer_for_problem(21, 30)
            self.instance._start_answer_for_problem(21, 30)
            request.assert_not_called()
        second.stop_lesson()
        self.assertEqual(self.statuses().count("accepted"), 1)
        self.assertEqual(self.statuses().count("duplicate"), 2)

    def test_unknown_submission_never_retried(self):
        self.instance._add_problems([self.question()])
        with patch.object(self.instance, "_build_ai_answers", return_value=["B"]), patch.object(lesson, "http_request", side_effect=TimeoutError()) as request:
            self.instance._start_answer_for_problem(21, 30)
            until(lambda: "unknown" in self.statuses())
            self.instance._start_answer_for_problem(21, 30)
            self.assertEqual(request.call_count, 1)
        self.assertNotIn("accepted", self.statuses())

    def test_server_rejects_answer(self):
        self.answer(response=Response({"code": 7}))
        self.assertIn("rejected", self.statuses())
        self.assertNotIn("accepted", self.statuses())

    def test_trial_generates_preview_without_submit(self):
        runtime.save_runtime({"mode": "trial", "auto_signin": True, "submit_answers": True})
        self.assertEqual(self.answer(), [])
        self.assertIn("preview", self.statuses())
        self.assertFalse(runtime.get_runtime()["submit_answers"])

    def test_unsupported_fill_blank(self):
        self.assertEqual(self.answer(problem=self.question(kind=4)), [])
        self.assertIn("unsupported", self.statuses())

    def test_multi_poll_and_short_payloads(self):
        for kind, answer in ((2, ["A", "B"]), (3, ["B"]), (5, "4")):
            with self.subTest(kind=kind):
                self.events.clear()
                calls = self.answer(problem=self.question(kind=kind, pid=100+kind), ai=answer)
                result = json.loads(calls[0].kwargs["data"])["result"]
                self.assertEqual(result, {"content": "4", "pics": [{"pic": "", "thumb": ""}]} if kind == 5 else answer)

    def test_cache_miss_refresh_then_answer(self):
        self.instance.presentation_ids.add("ppt1")
        question = self.question()
        def network(method, url, **kwargs):
            if "presentation/fetch" in url: return Response({"code": 0, "data": {"slides": [{"problem": question, "cover": question["_cover"]}]}})
            return Response()
        with patch.object(lesson, "http_request", side_effect=network) as request, patch.object(self.instance, "_build_ai_answers", return_value=["B"]):
            self.instance._start_answer_for_problem(21, 30)
            until(lambda: "accepted" in self.statuses())
            self.assertEqual(sum(c.args[0] == "POST" for c in request.call_args_list), 1)
        self.assertIn("retry", self.statuses())

    def test_cache_still_missing_reports_it(self):
        with patch.object(lesson, "http_request") as request:
            self.instance._start_answer_for_problem(21, 30)
            until(lambda: "cache_missing" in self.statuses())
            request.assert_not_called()

    def test_switch_off_while_ai_in_flight(self):
        def switch(*args):
            runtime.save_runtime({"mode": "observe"}); return ["B"]
        self.assertEqual(self.answer(ai=switch), [])
        self.assertIn("preview", self.statuses())

    def test_monitor_no_class_then_two_classes_signin_once_each(self):
        m = monitor.Monitor("fake", asyncio.Queue())
        self.monitors.append(m)
        m._running = True
        m._thread = threading.current_thread()
        sockets = []
        class FakeWS:
            def __init__(self, **kwargs): self.callbacks = kwargs; self.closed = threading.Event(); self.sent = []; sockets.append(self)
            def send(self, data): self.sent.append(json.loads(data))
            def run_forever(self, **kwargs):
                self.callbacks["on_open"](self)
                self.callbacks["on_message"](self, json.dumps({"op": "hello"}))
                self.closed.wait(3)
            def close(self): self.closed.set()
        lessons = []
        signins = []
        def network(method, url, **kwargs):
            if "on-lesson" in url: return Response({"code": 0, "data": {"onLessonClassrooms": lessons.copy()}})
            if method == "POST":
                signins.append(json.loads(kwargs["data"])["lessonId"])
                return Response({"code": 0, "data": {"lessonToken": "fake-token"}})
            return Response({"code": 0, "data": {}})
        with patch.object(monitor, "http_request", side_effect=network), patch.object(lesson, "http_request", side_effect=network), patch.object(lesson.websocket, "WebSocketApp", FakeWS):
            m._poll_once(); m._poll_once()
            self.assertEqual(m.state, "waiting")
            self.assertTrue(m.health()["discovery_healthy"])
            lessons.append({"lessonId": 51, "classroomId": 101, "courseName": "电路"})
            m._poll_once()
            until(lambda: len(sockets) == 1 and m.get_active_lessons()[0]["connected"])
            m._poll_once()
            sockets[0].callbacks["on_message"](sockets[0], json.dumps({"op": "lessonfinished"}))
            m._poll_once()
            self.assertEqual(signins, [51])
            lessons.clear(); m._poll_once()
            lessons.append({"lessonId": 52, "classroomId": 101, "courseName": "电路"})
            m._poll_once()
            until(lambda: len(sockets) == 2 and m.get_active_lessons()[0]["connected"])
            self.assertEqual(signins, [51, 52])
            self.assertEqual(sockets[1].sent[0]["op"], "hello")
            m.stop()

    def test_monitor_temporary_error_then_recovery_and_expiry(self):
        m = monitor.Monitor("fake", asyncio.Queue())
        self.monitors.append(m)
        expired = []
        m._on_session_expired = lambda: expired.append(True)
        with patch.object(monitor, "http_request", return_value=Response({"code": 0, "data": {"onLessonClassrooms": []}})):
            m._poll_once()
        with patch.object(monitor, "http_request", return_value=Response(status=401)):
            m._poll_once()
        self.assertEqual(m.state, "login_expired")
        self.assertEqual(expired, [True])

    def test_course_scope_excludes_other_class(self):
        self.assertFalse(runtime.can_signin(999))
        self.assertFalse(runtime.can_submit(999))

    def test_actual_discovery_loop_survives_temporary_failure(self):
        m = monitor.Monitor("fake", asyncio.Queue())
        self.monitors.append(m)
        intervals = runtime.get_runtime()
        intervals["poll_interval"] = 0.02
        attempts = []
        def network(*args, **kwargs):
            attempts.append(True)
            if len(attempts) == 1: raise TimeoutError()
            return Response({"code": 0, "data": {"onLessonClassrooms": []}})
        with patch.object(monitor, "get_runtime", return_value=intervals), patch.object(monitor, "http_request", side_effect=network):
            m._running = True
            m._thread = threading.Thread(target=m._run, daemon=True)
            m._thread.start()
            until(lambda: len(attempts) >= 3 and m.last_success is not None)
            self.assertEqual(m.state, "waiting")
            self.assertTrue(m.health()["discovery_healthy"])
            self.assertIsNone(m.last_error)
            m.stop()
        self.assertFalse(m.health()["discovery_healthy"])

    def test_socket_disconnect_reconnect_keeps_signin_and_answer_once(self):
        obj = self.instance
        obj._add_problems([self.question()])
        sockets, posts = [], []
        original_wait = obj._stop.wait
        class FakeWS:
            def __init__(self, **kwargs): self.callbacks = kwargs; self.closed = threading.Event(); sockets.append(self)
            def send(self, data): pass
            def close(self): self.closed.set()
            def run_forever(self, **kwargs):
                self.callbacks["on_open"](self)
                self.callbacks["on_message"](self, json.dumps({"op": "hello"}))
                self.callbacks["on_message"](self, json.dumps({"op": "unlockproblem", "problem": {"sid": 21, "limit": 30}}))
                if len(sockets) == 1:
                    until(lambda: "accepted" in [e.get("status") for e in obj_test.events if e.get("type") == "problem"])
                else: self.closed.wait(2)
        obj_test = self
        def network(method, url, **kwargs):
            if method == "POST":
                posts.append(url)
                return Response({"code": 0, "data": {"lessonToken": "fake"}})
            return Response({"code": 0, "data": {}})
        with patch.object(lesson.websocket, "WebSocketApp", FakeWS), patch.object(lesson, "http_request", side_effect=network), patch.object(obj, "_build_ai_answers", return_value=["B"]), patch.object(obj._stop, "wait", side_effect=lambda seconds=None: original_wait(min(seconds or 0, 0.02))):
            thread = threading.Thread(target=obj.start_lesson, daemon=True)
            thread.start()
            until(lambda: len(sockets) >= 2 and "duplicate" in self.statuses())
            obj.stop_lesson(); thread.join(2)
        self.assertEqual(sum("checkin" in url for url in posts), 1)
        self.assertEqual(sum("problem/answer" in url for url in posts), 1)
        self.assertIn("reconnecting", self.statuses())

    def test_missing_question_content_is_not_guessed(self):
        question = self.question()
        question.pop("content"); question.pop("_cover")
        self.assertEqual(self.answer(problem=question), [])
        self.assertIn("incomplete", self.statuses())

    def test_strict_parser_rejects_prose(self):
        self.assertEqual(parse_choice("A,C", ["A", "B", "C"], 2), ["A", "C"])
        for raw in ("The answer is B", "A B", "Z", "A,A", ""):
            with self.assertRaises(ValueError): parse_choice(raw, ["A", "B"], 1)

    def test_signed_picture_credentials_redacted_without_changing_ai_input(self):
        original = {"type": "question", "question": {"_cover": "https://example.invalid/a.png?auth_key=private-signature&x=1"}, "sessionid": "fake-secret"}
        event_log.append(original)
        record = event_log.load_recent(1)[0]
        self.assertNotIn("private-signature", json.dumps(record))
        self.assertNotIn("fake-secret", event_log._LOG_PATH.read_text(encoding="utf-8"))
        self.assertIn("private-signature", original["question"]["_cover"])


if __name__ == "__main__": unittest.main(verbosity=2)
