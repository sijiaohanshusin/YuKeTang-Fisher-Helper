"""Local UI-only fixture. Never connects to Yuketang or a real model."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import mimetypes
import time

ROOT = Path(__file__).resolve().parents[1]
runtime = {"mode": "observe", "auto_signin": False, "submit_answers": False, "course_ids": [], "poll_interval": 30, "submit_reserve": 3, "ai_timeout": 90}
courses = [{"classroom_id": f"demo-{index}", "name": name, "teacher_name": "示例教师", "active": index == 1} for index, name in enumerate(["电路分析", "信号与系统", "数字信号处理", "电子系统设计"], 1)]
keys = []
active = -1
vision = None
complete = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_json(self, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == "/api/auth/status": return self.send_json({"logged_in": True, "user": {"name": "演示账号"}})
        if self.path == "/api/health": return self.send_json({"server": "ok", "version": "2.1.0-demo", "domain": "www.yuketang.cn", "login_verified": True, "needs_setup": not complete, "runtime": runtime, "vision_validation": vision,
            "monitor": {"state": "watching", "discovery_healthy": True, "last_error": None, "last_success": time.time(), "discovered": [{"lessonid": "demo", "classroomid": "demo-1", "name": "电路分析（演示）"}],
                        "lessons": [{"lessonid": "demo", "lessonname": "电路分析（演示数据）", "connected": True, "last_pong": time.time(), "cached_problems": 3, "presentations": 1}] if runtime["auto_signin"] else []}})
        if self.path == "/api/ai/settings": return self.send_json({"keys": keys, "active_key": active})
        if self.path == "/api/courses/all": return self.send_json(courses)
        if self.path == "/api/events/recent": return self.send_json([{"type": "submission_test", "status": "passed", "message": "界面演示数据：未连接真实课堂或模型", "logged_at": "2026-10-19T14:00:00"}])
        if self.path == "/api/runtime": return self.send_json(runtime)
        path = (ROOT / "examples" / "circuit.png") if self.path == "/api/experiment/sample.png" else (ROOT / "frontend" / "dist" / self.path.lstrip("/")).resolve()
        if not path.is_file() or not path.is_relative_to(ROOT): path = ROOT / "frontend" / "dist" / "index.html"
        body = path.read_bytes()
        if path.name == "index.html": body = body.replace(b'<title>Yuketang Helper</title>', '<title>界面演示 · 模拟账号</title>'.encode())
        self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream"); self.end_headers(); self.wfile.write(body)
    def do_PUT(self): self.do_POST()
    def do_POST(self):
        global active, vision, complete
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b'{}')
        if self.path == "/api/ai/keys":
            keys.append({**body, "key": "demo****only"}); return self.send_json({"ok": True, "index": len(keys) - 1})
        if self.path == "/api/ai/active": active = body["active_key"]
        if self.path == "/api/runtime": runtime.update(body); return self.send_json({"ok": True, "config": runtime})
        if self.path == "/api/experiment/vision-test":
            vision = {"correct": True, "current_config": True, "active_model": keys[active]["model"], "elapsed_seconds": 0.1}
            return self.send_json({"ok": True, "correct": True, "answers": ["B"], "elapsed_seconds": 0.1})
        if self.path == "/api/setup/complete": complete = True
        return self.send_json({"ok": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, default=18540); args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
