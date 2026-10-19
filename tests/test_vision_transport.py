"""Uses a real local HTTP server and installed SDK; the model itself is simulated."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from ai_provider import create_provider_from_entry, GeminiProvider


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.raw = "B"
        self.status = 200
        self.png = (Path(__file__).resolve().parents[1] / "examples" / "circuit.png").read_bytes()
        case = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Type", "image/png"); self.end_headers(); self.wfile.write(case.png)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                case.requests.append(body)
                self.send_response(case.status); self.send_header("Content-Type", "application/json"); self.end_headers()
                response = {"id": "local-test", "object": "chat.completion", "created": 1, "model": "mock-vision", "choices": [{"index": 0, "message": {"role": "assistant", "content": case.raw}, "finish_reason": "stop"}]}
                self.wfile.write(json.dumps(response).encode())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.client = create_provider_from_entry({"provider": "openai_compat", "key": "local-test-only", "base_url": self.base, "model": "mock-vision"})
        self.problem = {"content": "Compute I from the circuit", "options": [{"key": "A", "content": "1A"}, {"key": "B", "content": "2A"}]}
        self.client.prepare(self.problem, 5)

    def tearDown(self):
        self.client.client.close()
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def test_real_sdk_downloads_image_sends_pixels_and_full_text_then_parses(self):
        result = self.client.answer_choice(self.base + "/circuit.png", ["A", "B"], 1)
        self.assertEqual(result, ["B"])
        self.assertEqual(len(self.requests), 1)
        content = self.requests[0]["messages"][0]["content"]
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(content[0]["image_url"]["url"].split(",")[1]), self.png)
        self.assertIn("Compute I", content[1]["text"])
        self.assertIn("2A", content[1]["text"])
        self.assertEqual(self.requests[0]["model"], "mock-vision")

    def test_model_prose_is_rejected_after_real_http(self):
        self.raw = "I think B is correct"
        with self.assertRaises(ValueError): self.client.answer_choice(self.base + "/circuit.png", ["A", "B"], 1)

    def test_images_in_options_are_sent_as_pixels_too(self):
        self.problem["options"][0]["content"] = '<img src="' + self.base + '/option.png">'
        self.client.prepare(self.problem, 5)
        self.client.answer_choice(self.base + "/circuit.png", ["A", "B"], 1)
        content = self.requests[0]["messages"][0]["content"]
        self.assertEqual(sum(part["type"] == "image_url" for part in content), 2)

    def test_live_schema_body_and_option_value_are_kept_without_teacher_metadata(self):
        self.client.prepare({"body": "Find current I", "options": [{"key": "A", "value": "1A"}, {"key": "B", "value": "2A"}],
                             "answers": ["PRIVATE_ANSWER_KEY"], "remark": "TEACHER_REMARK", "sendTime": 0}, 5)
        self.client.answer_choice(self.base + "/circuit.png", ["A", "B"], 1)
        prompt = self.requests[0]["messages"][0]["content"][-1]["text"]
        self.assertIn("Find current I", prompt)
        self.assertIn("2A", prompt)
        self.assertNotIn("PRIVATE_ANSWER_KEY", prompt)
        self.assertNotIn("TEACHER_REMARK", prompt)

    def test_sdk_does_not_retry_model_errors(self):
        self.status = 503
        with self.assertRaises(Exception): self.client.answer_choice(self.base + "/circuit.png", ["A", "B"], 1)
        self.assertEqual(len(self.requests), 1)

    def test_gemini_request_accepts_current_timeout_config(self):
        from google.genai import types
        # Validate current installed SDK schema without making an external request.
        cfg = types.GenerateContentConfig(http_options=types.HttpOptions(timeout=5000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.assertEqual(cfg.http_options.timeout, 5000)


if __name__ == "__main__": unittest.main(verbosity=2)
