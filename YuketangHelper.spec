# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import certifi
from PyInstaller.utils.hooks import collect_submodules, copy_metadata
ROOT = Path(SPECPATH)
# Explicit data allowlist: never bundle the backend folder or any local state.
data = [(str(ROOT / "frontend" / "dist"), "static"),
        (str(ROOT / "build" / "licenses"), "licenses"),
        (str(ROOT / "examples" / "circuit.png"), "examples"),
        (certifi.where(), "certifi")]
for package in ("openai", "google-genai", "uvicorn", "fastapi", "requests"):
    data += copy_metadata(package)
a = Analysis([str(ROOT / "app_entry.py")], pathex=[str(ROOT / "backend")], datas=data,
    hiddenimports=["main", "config", "runtime", "journal", "lesson", "monitor", "event_log", "ai_provider", "app_version", "resources", "submission_check",
                   "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
                   "multipart", "multipart.multipart"] + collect_submodules("google.genai"),
    excludes=["tkinter", "pytest", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="YuketangHelper", debug=False,
          strip=False, upx=False, console=False, icon=str(ROOT / "frontend" / "src" / "favicon_256x256.ico"))
