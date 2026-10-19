import sys
from pathlib import Path


def resource_path(name):
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return root / name
