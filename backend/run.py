import os
import sys
from pathlib import Path
import uvicorn

backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting TEAM OBSIDIAN Backend on http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, reload=True, app_dir=str(backend_dir))

