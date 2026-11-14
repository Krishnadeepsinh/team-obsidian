import os
import sys
from pathlib import Path

# Ensure the backend directory is always in sys.path for test collection
BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Use an isolated SQLite database for automated pytest runs unless explicitly overridden
TEST_DB_PATH = Path(__file__).resolve().parent / "pytest_isolated.db"
if TEST_DB_PATH.exists():
    try:
        TEST_DB_PATH.unlink()
    except Exception:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ.setdefault("APP_ENV", "test")

