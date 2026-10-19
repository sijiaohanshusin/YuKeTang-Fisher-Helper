"""Smoke-test the frozen executable without Python/Node in PATH or real credentials."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


def run_smoke(executable, output):
    executable = Path(executable).resolve()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(url, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=60) as response:
            return response.read()
    with tempfile.TemporaryDirectory(prefix="yuketang-smoke-") as folder:
        directory = Path(folder)
        store = directory / "store"
        env = {**os.environ, "PATH": str(Path(os.environ["SystemRoot"]) / "System32") + os.pathsep + os.environ["SystemRoot"]}
        env.pop("YUKETANG_DATA_DIR", None)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        process = subprocess.Popen([str(executable), "--no-browser", "--port", str(port), "--data-dir", str(store)], env=env, **options)
        captured = []
        class ModelServer(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
                self.wfile.write(json.dumps({"id": "smoke", "object": "chat.completion", "created": 1, "model": "mock-vision", "choices": [{"index": 0, "message": {"role": "assistant", "content": "B"}, "finish_reason": "stop"}]}).encode())
        model = ThreadingHTTPServer(("127.0.0.1", 0), ModelServer)
        thread = threading.Thread(target=model.serve_forever, daemon=True); thread.start()
        results = {}
        try:
            deadline = time.monotonic() + 90
            while True:
                try:
                    health = json.loads(request(url + "/api/health")); break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Frozen server did not become healthy")
                    time.sleep(0.5)
            assert health["runtime"]["mode"] == "observe" and not health["runtime"]["auto_signin"] and not health["runtime"]["submit_answers"]
            assert not health["login_verified"] and not health["runtime"]["course_ids"] and health["needs_setup"]
            results["fresh_observation_defaults"] = True
            for route in ("/experiment", "/setup", "/login"):
                html = request(url + route).decode()
                assert '<div id="root"></div>' in html
                for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html):
                    assert request(url + asset)
            results["frontend_and_setup_routes"] = True
            png = request(url + "/api/experiment/sample.png")
            assert png.startswith(b"\x89PNG")
            results["bundled_image"] = True
            request(url + "/api/ai/keys", {"name": "smoke mock", "provider": "openai_compat", "key": "local-smoke-only", "base_url": f"http://127.0.0.1:{model.server_port}/v1", "model": "mock-vision"})
            vision = json.loads(request(url + "/api/experiment/vision-test", {}))
            assert vision.get("ok") and vision.get("correct") and not vision["submitted"], vision
            content = captured[0]["messages"][0]["content"]
            picture = next(part["image_url"]["url"] for part in content if part["type"] == "image_url")
            assert base64.b64decode(picture.split(",", 1)[1]) == png
            results["frozen_openai_sdk_and_image_transport"] = True
            diagnostic = json.loads(request(url + "/api/experiment/submission-test", {}))
            assert diagnostic.get("ok") and diagnostic["real_classroom_requests"] == 0, diagnostic
            results["frozen_submission_checks"] = {"passed": diagnostic["passed"], "total": diagnostic["total"]}
            final_health = json.loads(request(url + "/api/health"))
            assert final_health["runtime"] == health["runtime"] and not final_health["login_verified"]
            results["diagnostics_isolated_from_live_config"] = True
        finally:
            model.shutdown(); model.server_close(); thread.join(3)
            subprocess.run([str(executable), "--stop", "--no-browser", "--data-dir", str(store)], env=env, timeout=45, check=True, **options)
            try: process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                raise RuntimeError("Frozen stop command did not stop its instance")
        results["start_and_stop"] = True
        result = {"ok": True, "platform": "Windows x64", "python_node_in_path": False, "real_credentials": False, "checks": results}
        Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    arguments = parser.parse_args()
    print(json.dumps(run_smoke(arguments.executable, arguments.report), ensure_ascii=False, indent=2))
