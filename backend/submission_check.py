"""Run only in a child process: isolated data, simulated AI, real loopback HTTP."""
import json
import os
import socket
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


def run_checks():
    with tempfile.TemporaryDirectory(prefix="yuketang-check-") as directory:
        os.environ["YUKETANG_DATA_DIR"] = str(Path(directory) / "store")
        # Import after isolation; the live server's globals are never modified.
        import config
        import journal
        import lesson
        import runtime

        config.save_config({**config._EMPTY_CONFIG, "user": {"id": "simulation"},
                            "ai": {"keys": [{"provider": "simulation", "key": "local-test-only"}], "active_key": 0, "fallback_keys": False}})
        runtime.save_runtime({"mode": "auto", "auto_signin": True, "submit_answers": True, "course_ids": ["simulation"]})
        cases = [
            ("single", "单选题", 1, ["B"], "accepted", 1),
            ("multiple", "多选题", 2, ["A", "C"], "accepted", 1),
            ("poll", "投票题", 3, ["B"], "accepted", 1),
            ("short", "简答题", 5, "4", "accepted", 1),
            ("fill", "填空题明确跳过", 4, None, "unsupported", 0),
            ("bad-single", "单选返回多个选项", 1, ["A", "B"], "ai_failed", 0),
            ("bad-letter", "不存在的选项", 2, ["Z"], "ai_failed", 0),
            ("bad-poll", "投票超出可选数量", 3, ["A", "B"], "ai_failed", 0),
            ("blank-short", "空白简答被拒绝", 5, " ", "ai_failed", 0),
            ("ai-error", "AI 调用失败", 1, None, "ai_failed", 0),
            ("late", "AI 超时不提交", 1, ["B"], "timeout", 0),
            ("deadline", "截止预算不足", 1, ["B"], "timeout", 0),
            ("duplicate", "重复事件仅提交一次", 1, ["B"], "accepted", 1),
            ("rejected", "服务器拒绝不报成功", 1, ["B"], "rejected", 1),
            ("unknown", "响应中断不自动重试", 1, ["B"], "unknown", 1),
            ("trial", "试答模式不提交", 1, ["B"], "preview", 0),
        ]
        specs = {case[0]: case for case in cases}
        received = []

        class Server(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                case = specs.get(body.get("problemId"))
                valid = False
                if case and self.path == "/api/v3/lesson/problem/answer":
                    kind, answer = case[2], case[3]
                    expected = {"content": answer, "pics": [{"pic": "", "thumb": ""}]} if kind == 5 else answer
                    valid = (body.get("problemType") == kind and body.get("result") == expected
                             and isinstance(body.get("dt"), int) and abs(time.time() * 1000 - body["dt"]) < 30000)
                received.append({"id": body.get("problemId"), "valid": valid, "payload": body})
                if body.get("problemId") == "unknown":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                accepted = valid and body.get("problemId") != "rejected"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"code": 0 if accepted else 409, "msg": "local simulation only"}).encode())

        server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        results = []
        started = time.monotonic()
        try:
            for name, label, kind, answer, expected, expected_count in cases:
                events = []
                item = lesson.Lesson({"lessonid": "local-check", "lessonname": "本机模拟", "classroomid": "simulation"},
                                     "simulation-only", {**config.DEFAULT_COURSE_CONFIG, "answer_delay_min": 0},
                                     lambda event, data: events.append({"type": event, **data}))
                item._running = True
                problem = {"problemId": name, "problemType": kind, "body": "本机模拟问题：2+2=?", "pollingCount": 1,
                           "options": [{"key": "A", "value": "2"}, {"key": "B", "value": "4"}, {"key": "C", "value": "6"}]}
                item._add_problems([problem])

                class Provider:
                    def prepare(self, *args): return self
                    def answer_choice(self, *args):
                        if name == "late": time.sleep(0.2)
                        if name == "ai-error": raise RuntimeError("simulated AI failure")
                        return answer
                    def answer_short(self, *args): return answer

                runtime.save_runtime({"mode": "trial" if name == "trial" else "auto", "submit_answers": name != "trial"})
                limit = 3.06 if name == "late" else (1 if name == "deadline" else 30)
                with patch.object(lesson, "create_provider_from_entry", return_value=Provider()), \
                     patch.object(lesson, "api_url", side_effect=lambda template, **kw: base + "/api/v3/lesson/problem/answer"):
                    item._start_answer_for_problem(name, limit)
                    if name == "duplicate": item._start_answer_for_problem(name, limit)
                    key = item._key(f"problem:{name}")
                    stop_at = time.monotonic() + 5
                    while time.monotonic() < stop_at:
                        record = journal.get(key) or {}
                        if record.get("state") not in (None, "processing", "sent"): break
                        time.sleep(0.01)
                    # Let timed-out mock AI finish before the next closure is installed.
                    if name == "late": time.sleep(0.21)
                    record = journal.get(key) or {}
                posts = [row for row in received if row["id"] == name]
                passed = record.get("state") == expected and len(posts) == expected_count and all(row["valid"] for row in posts)
                if name == "duplicate": passed = passed and any(e.get("status") == "duplicate" for e in events)
                results.append({"id": name, "label": label, "passed": passed, "expected": expected,
                                "actual": record.get("state", "no_result"), "requests": len(posts),
                                "payload": posts[0]["payload"] if posts else None})
                item.stop_lesson()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
        return {"ok": all(row["passed"] for row in results), "simulation": True,
                "real_classroom_requests": 0, "transport": "loopback HTTP", "ai": "simulated",
                "tested_at": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": round(time.monotonic() - started, 2),
                "passed": sum(row["passed"] for row in results), "total": len(results), "cases": results}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    arguments = parser.parse_args()
    result = run_checks()
    Path(arguments.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if result["ok"] else 1)
