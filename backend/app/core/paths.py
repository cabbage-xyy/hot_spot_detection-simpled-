from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = APP_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

CONFIG_DIR = BACKEND_DIR / "config"
DATA_DB_DIR = BACKEND_DIR / "data_db"
WEIGHTS_DIR = BACKEND_DIR / "weights"
RUNTIME_DIR = BACKEND_DIR / "runtime"

REPORTS_DIR = RUNTIME_DIR / "reports"
OUTPUT_VIDEOS_DIR = RUNTIME_DIR / "output_videos"
DETECTION_ASSETS_DIR = OUTPUT_VIDEOS_DIR / "detection_assets"
FILES_DIR = RUNTIME_DIR / "files"

CONFIG_PATH = CONFIG_DIR / "config.yaml"
DB_PATH = DATA_DB_DIR / "company_information.db"
BACKEND_PORT_PATH = RUNTIME_DIR / "backend_port.txt"

WEIGHT_BEST1_PATH = WEIGHTS_DIR / "best1.pt"
WEIGHT_BEST2_PATH = WEIGHTS_DIR / "best2.pt"
WEIGHT_BEST_PATH = WEIGHTS_DIR / "best.pt"


def ensure_runtime_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    DETECTION_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)