"""Frozen entry point for the Lore sidecar.

PyInstaller needs a real script to freeze (it can't freeze `-m uvicorn`), so this
imports the FastAPI app and runs it programmatically. The parent-watchdog starts
inside the app's lifespan, so the frozen binary still exits when the Tauri shell
that launched it goes away.

In development the sidecar is run via ``python -m uvicorn app.main:app`` instead;
this file is only the production/packaged path.
"""

from __future__ import annotations

import os

import uvicorn

from app.main import app


def main() -> None:
    host = os.environ.get("LORE_HOST", "127.0.0.1")
    port = int(os.environ.get("LORE_PORT", "8765"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
