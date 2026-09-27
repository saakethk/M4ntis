"""Run the Mantis backend: ``python main.py`` (port from BACKEND_PORT, default 8001)."""

from __future__ import annotations

import uvicorn

from src.backend.mantis.api.app import create_app
from src.backend.mantis.config import env_port

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=env_port("BACKEND_PORT", 8001))
