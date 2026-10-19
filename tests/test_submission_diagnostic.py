import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DiagnosticTests(unittest.TestCase):
    def test_all_scenarios_use_isolated_process_and_only_local_http(self):
        root = Path(__file__).resolve().parents[1]
        runtime_file = root / "store" / "runtime.json"
        before = runtime_file.read_bytes() if runtime_file.exists() else None
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            result = subprocess.run([sys.executable, "-m", "submission_check", "--report", str(report)],
                                    cwd=root / "backend", capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            data = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["real_classroom_requests"], 0)
        self.assertEqual(data["passed"], data["total"])
        cases = {row["id"]: row for row in data["cases"]}
        for kind in ("single", "multiple", "poll", "short"):
            self.assertEqual(cases[kind]["actual"], "accepted")
            self.assertEqual(cases[kind]["requests"], 1)
        self.assertEqual(cases["fill"]["requests"], 0)
        self.assertEqual(cases["unknown"]["requests"], 1)
        self.assertEqual(cases["duplicate"]["requests"], 1)
        after = runtime_file.read_bytes() if runtime_file.exists() else None
        self.assertEqual(before, after, "Diagnostics must not change the live runtime file")
