import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from smoke_release import run_smoke


def check_installer(installer, report):
    with tempfile.TemporaryDirectory(prefix="yuketang-installer-test-") as folder:
        root = Path(folder).resolve()
        app = root / "application"
        assert app.resolve().parent == root
        result = subprocess.run([str(Path(installer).resolve()), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/NOICONS", "/SmokeTest=1", "/DIR=" + str(app)], timeout=120)
        if result.returncode != 0: raise RuntimeError(f"Installer exit code {result.returncode}")
        executable = app / "YuketangHelper.exe"
        if not executable.is_file(): raise RuntimeError("Installed executable missing")
        try:
            smoke = run_smoke(executable, root / "installed-smoke.json")
        finally:
            uninstaller = (app / "unins000.exe").resolve()
            assert uninstaller.parent == app.resolve()
            result = subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SmokeTest=1"], timeout=90)
            if result.returncode != 0: raise RuntimeError(f"Uninstaller exit code {result.returncode}")
        import time
        for _ in range(30):
            if not executable.exists(): break
            time.sleep(0.2)
        if executable.exists(): raise RuntimeError("Uninstall did not remove installed executable")
        validation = {"ok": True, "install": True, "installed_application": smoke, "uninstall": True, "personal_data_used": False}
        Path(report).write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
        return validation


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("installer")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    print(json.dumps(check_installer(args.installer, args.report), ensure_ascii=False, indent=2))
