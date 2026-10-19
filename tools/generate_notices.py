import importlib.metadata
from pathlib import Path
import re
import sys


def generate(root):
    output = root / "build" / "licenses"
    output.mkdir(parents=True, exist_ok=True)
    index = []
    for package in importlib.metadata.distributions():
        name = package.metadata.get("Name", "unknown")
        safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
        texts = []
        for item in package.files or []:
            if any(part.lower().startswith(("license", "copying", "notice")) for part in item.parts):
                path = Path(package.locate_file(item))
                if path.is_file() and path.stat().st_size < 1_000_000:
                    texts.append(f"\n--- {item.name} ---\n" + path.read_text(encoding="utf-8", errors="replace"))
        if texts:
            (output / (safe + ".txt")).write_text(f"{name} {package.version}\n" + "\n".join(texts), encoding="utf-8")
        index.append({"name": name, "version": package.version, "license": package.metadata.get("License-Expression") or package.metadata.get("License", "see package metadata")})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file(): (output / "Python.txt").write_bytes(python_license.read_bytes())
    import json
    # Include the notices for the browser bundle as well as the Python runtime.
    lock = json.loads((root / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    for package_path, metadata in lock.get("packages", {}).items():
        if not package_path or metadata.get("dev"): continue
        folder = root / "frontend" / package_path
        name = package_path.rsplit("node_modules/", 1)[-1]
        texts = []
        for path in folder.iterdir() if folder.is_dir() else []:
            if path.is_file() and path.name.lower().startswith(("license", "copying", "notice")):
                texts.append(f"\n--- {path.name} ---\n" + path.read_text(encoding="utf-8", errors="replace"))
        if texts:
            safe = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
            (output / ("npm-" + safe + ".txt")).write_text(name + " " + metadata.get("version", "") + "\n" + "\n".join(texts), encoding="utf-8")
        index.append({"name": "npm:" + name, "version": metadata.get("version"), "license": metadata.get("license", "see package metadata")})
    (output / "components.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": generate(Path(__file__).resolve().parents[1])
