"""Build from explicit inputs, verify the executable, then package clean assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app_version import VERSION


def run(command, cwd=ROOT):
    subprocess.run([str(item) for item in command], cwd=cwd, check=True)


def build(compiler, skip_dependencies=False):
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    (ROOT / "build").mkdir(exist_ok=True)
    from generate_notices import generate
    generate(ROOT)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if not skip_dependencies: run([npm, "ci"], ROOT / "frontend")
    run([npm, "run", "build"], ROOT / "frontend")
    run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])
    report = ROOT / "build" / "submission-validation.json"
    run([sys.executable, "-m", "submission_check", "--report", report], ROOT / "backend")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "YuketangHelper.spec"])
    executable = ROOT / "dist" / "YuketangHelper.exe"
    smoke = ROOT / "build" / "frozen-smoke.json"
    run([sys.executable, ROOT / "tools" / "smoke_release.py", executable, "--report", smoke])
    run([compiler, "/Qp", f"/DAppVersion={VERSION}", ROOT / "installer" / "windows.iss"])
    setup = release / f"YuketangHelper-Setup-v{VERSION}-Windows-x64.exe"
    if not setup.is_file(): raise RuntimeError("Installer compiler did not produce the expected output")
    installer_smoke = ROOT / "build" / "installer-smoke.json"
    run([sys.executable, ROOT / "tools" / "smoke_installer.py", setup, "--report", installer_smoke])
    portable = release / f"YuketangHelper-Portable-v{VERSION}-Windows-x64.zip"
    # No recursive folder copies: store/logs/config are deliberately absent.
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED) as archive:
        for source, target in [(executable, "YuketangHelper.exe"), (ROOT / "分发使用说明.md", "使用说明.md"),
                               (ROOT / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
                               (report, "submission-validation.json"), (smoke, "frozen-smoke.json")]:
            archive.write(source, target)
        archive.writestr("start.cmd", '@echo off\r\ncd /d "%~dp0"\r\nstart "" "%~dp0YuketangHelper.exe"\r\n')
        archive.writestr("stop.cmd", '@echo off\r\ncd /d "%~dp0"\r\n"%~dp0YuketangHelper.exe" --stop\r\n')
        for notice in (ROOT / "build" / "licenses").iterdir(): archive.write(notice, "licenses/" + notice.name)
        if any(name.startswith(("store/", "logs/", ".env")) for name in archive.namelist()): raise RuntimeError("Unexpected local data in package")
    deploy = release / "install-latest.ps1"
    shutil.copyfile(ROOT / "tools" / "install-latest.ps1", deploy)
    assets = [setup, portable, deploy]
    (release / "SHA256SUMS.txt").write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in assets), encoding="ascii")
    print(json.dumps({"version": VERSION, "assets": [{"name": p.name, "bytes": p.stat().st_size} for p in assets]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--skip-dependencies", action="store_true")
    args = parser.parse_args()
    build(args.compiler.resolve(), args.skip_dependencies)
