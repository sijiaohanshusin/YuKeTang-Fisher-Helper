"""Portable desktop entry point; all user state stays outside the executable."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
if not getattr(sys, "frozen", False): sys.path.insert(0, str(ROOT / "backend"))


def creation_time(pid):
    if sys.platform != "win32": return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle: return None
    values = [ctypes.c_uint64() for _ in range(4)]
    try:
        if kernel.GetProcessTimes(handle, *[ctypes.byref(v) for v in values]): return values[0].value
    finally: kernel.CloseHandle(handle)


def main():
    from app_version import VERSION
    parser = argparse.ArgumentParser(description="Yuketang Helper localhost desktop application")
    parser.add_argument("--port", type=int, default=8500)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    if args.self_test:
        if sys.stderr is None: sys.stderr = open(os.devnull, "w")
        if sys.stdout is None: sys.stdout = sys.stderr
        if not args.report: parser.error("--self-test requires --report PATH")
        from submission_check import run_checks
        result = run_checks()
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if result["ok"] else 1
    if not 1024 <= args.port <= 65535: parser.error("Port must be between 1024 and 65535")
    if args.data_dir: os.environ["YUKETANG_DATA_DIR"] = str(args.data_dir.resolve())
    from config import STORE_DIR
    logs = STORE_DIR.parent / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    pid_file = logs / "desktop.json"
    if args.stop:
        if not pid_file.exists(): return 0
        saved = json.loads(pid_file.read_text(encoding="utf-8"))
        if sys.platform == "win32":
            if saved.get("creation") and creation_time(saved["pid"]) == saved["creation"]:
                subprocess.run(["taskkill", "/PID", str(saved["pid"]), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try: os.kill(saved["pid"], signal.SIGTERM)
            except ProcessLookupError: pass
        pid_file.unlink(missing_ok=True)
        return 0
    # Windowed executables have no console streams; Uvicorn still expects writable streams.
    if sys.stdout is None: sys.stdout = open(logs / "console.log", "a", encoding="utf-8")
    if sys.stderr is None: sys.stderr = sys.stdout
    handler = RotatingFileHandler(logs / "backend.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    if getattr(sys, "frozen", False):
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{args.port}"
    try:
        with opener.open(url + "/api/health", timeout=2) as response:
            if json.load(response).get("server") == "ok":
                if not args.no_browser: webbrowser.open(url + "/experiment")
                return 0
    except Exception: pass
    import uvicorn
    from main import app
    pid_file.write_text(json.dumps({"pid": os.getpid(), "creation": creation_time(os.getpid()), "port": args.port, "version": VERSION}), encoding="utf-8")
    if not args.no_browser:
        def open_when_ready():
            for _ in range(60):
                try:
                    with opener.open(url + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            webbrowser.open(url + "/experiment"); return
                except Exception: time.sleep(0.5)
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info", use_colors=False, access_log=False)
    finally:
        if pid_file.exists():
            saved = json.loads(pid_file.read_text(encoding="utf-8"))
            if saved.get("pid") == os.getpid(): pid_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
