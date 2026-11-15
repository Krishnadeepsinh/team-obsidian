import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure the backend directory is always in sys.path for test collection
BACKEND_DIR = str(Path(__file__).resolve().parent.parent)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Provision isolated sandbox directory for test DB, uploads, and generated reports
TEST_SANDBOX_DIR = Path(tempfile.mkdtemp(prefix="obsidian_pytest_")).resolve()
TEST_DB_PATH = TEST_SANDBOX_DIR / "pytest_isolated.db"
TEST_UPLOAD_DIR = TEST_SANDBOX_DIR / "uploads"
TEST_REPORTS_DIR = TEST_SANDBOX_DIR / "generated_reports"
TEST_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
TEST_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["UPLOAD_DIR"] = str(TEST_UPLOAD_DIR)
os.environ["REPORTS_DIR"] = str(TEST_REPORTS_DIR)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_DEMO_SEED", "true")

# Ensure settings singleton reflects test isolation paths
try:
    from app.core.config import settings

    settings.APP_ENV = "test"
    settings.ENABLE_DEMO_SEED = True
    settings.DATABASE_URL = f"sqlite:///{TEST_DB_PATH.as_posix()}"
    settings.UPLOAD_DIR = TEST_UPLOAD_DIR
    settings.REPORTS_DIR = TEST_REPORTS_DIR
except Exception:
    pass


def pytest_sessionfinish(session, exitstatus):
    """Teardown and purge isolated sandbox files after pytest completes."""
    try:
        shutil.rmtree(TEST_SANDBOX_DIR, ignore_errors=True)
    except Exception:
        pass
