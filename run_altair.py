import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALT_DIR = ROOT / "src" / "altair"
CORE_DIR = ALT_DIR / "core"
APP_DIR = ALT_DIR / "app"

for p in (str(ALT_DIR), str(CORE_DIR), str(APP_DIR), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("ALTAIR_WWEBJS_DIR", str(ROOT / "scripts" / "whatsapp"))
os.environ.setdefault("ALTAIR_CHROME_PROFILE_DIR", str(ROOT / "data" / "chrome_profile"))
os.environ.setdefault("ALTAIR_DATA_DIR", str(ROOT / "data"))

from altair import main  # noqa: F401
