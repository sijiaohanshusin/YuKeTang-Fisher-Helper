"""Windows localhost launcher. Uses only this repository's virtual environment."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
PID = LOGS / "local-service.json"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def start():
    LOGS.mkdir(exist_ok=True)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8500/api/health", timeout=2) as response:
            if json.load(response).get("server") == "ok":
                print("Already running: http://127.0.0.1:8500/experiment")
                webbrowser.open("http://127.0.0.1:8500/experiment")
                return
    except Exception: pass
    if not PYTHON.exists() or not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise SystemExit("Run init-local.bat first. Virtual environment or frontend build missing.")
    with (LOGS / "backend.log").open("a", encoding="utf-8") as output:
        process = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8500", "--no-access-log"],
                                   cwd=ROOT / "backend", stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW,
                                   env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"})
    PID.write_text(json.dumps({"pid": process.pid, "creation": creation_time(process.pid)}), encoding="utf-8")
    for _ in range(40):
        if process.poll() is not None: raise SystemExit("Backend failed. See logs/backend.log (port 8500 may be occupied).")
        try:
            with urllib.request.urlopen("http://127.0.0.1:8500/api/health", timeout=1) as r:
                if r.status == 200:
                    print("Running: http://127.0.0.1:8500/experiment")
                    webbrowser.open("http://127.0.0.1:8500/experiment")
                    return
        except Exception: time.sleep(0.5)
    print("Backend is starting. See logs/backend.log")


def creation_time(pid):
    # Match both PID and process creation time so a stale PID file cannot kill an unrelated process.
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


def stop():
    if not PID.exists():
        print("No local service PID file."); return
    saved = json.loads(PID.read_text(encoding="utf-8"))
    if saved.get("creation") and creation_time(saved["pid"]) == saved["creation"]:
        subprocess.run(["taskkill", "/PID", str(saved["pid"]), "/T", "/F"], check=False)
        print("Stopped local classroom helper.")
    else: print("Service has already stopped; no unrelated process was terminated.")
    PID.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.platform != "win32": raise SystemExit("This launcher is for Windows.")
    if len(sys.argv) > 1 and sys.argv[1] == "stop": stop()
    else: start()
