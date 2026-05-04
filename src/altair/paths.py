from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
CORE_DIR = SRC_DIR / "altair" / "core"
CONFIG_DIR = PROJECT_ROOT / "configs"
CONFIG_JSON_DIR = CONFIG_DIR / "json"
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
WHATSAPP_DIR = SCRIPTS_DIR / "whatsapp"
