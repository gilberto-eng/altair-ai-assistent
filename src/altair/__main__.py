from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
ALT_DIR = ROOT / "src" / "altair"
CORE_DIR = ALT_DIR / "core"
APP_DIR = ROOT / "src" / "altair" / "app"

for p in (str(ALT_DIR), str(CORE_DIR), str(APP_DIR), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("ALTAIR_WWEBJS_DIR", str(ROOT / "scripts" / "whatsapp"))
os.environ.setdefault("ALTAIR_CHROME_PROFILE_DIR", str(ROOT / "data" / "chrome_profile"))
os.environ.setdefault("ALTAIR_DATA_DIR", str(ROOT / "data"))

from . import main  # noqa: F401
