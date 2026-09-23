"""Local dev runner: demo data on, auto-reload off. `python dev.py` from the backend folder (or anywhere).

Creates ./data next to this file. NOT for production - see README for the real settings."""
import os

import uvicorn

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("SDMS_SEED_DEMO", "true")
    os.environ.setdefault("SDMS_ENABLE_DOCS", "true")  # Swagger UI at http://127.0.0.1:8000/docs
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
