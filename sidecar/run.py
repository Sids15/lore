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
import sys

import uvicorn

from app.main import app


def _ensure_std_streams() -> None:
    """Give the process real stdout/stderr streams.

    PyInstaller's windowed build (``console=False``) sets ``sys.stdout`` and
    ``sys.stderr`` to ``None``, which crashes uvicorn's log formatter (it calls
    ``sys.stdout.isatty()``). Point any missing stream at the null device so
    logging configures cleanly. The handle is kept open for the process lifetime.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    devnull = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = devnull
    if sys.stderr is None:
        sys.stderr = devnull


def main() -> None:
    _ensure_std_streams()
    host = os.environ.get("LORE_HOST", "127.0.0.1")
    port = int(os.environ.get("LORE_PORT", "8765"))
    # log_config=None skips uvicorn's dictConfig, so its colour log formatter (which
    # calls sys.stdout.isatty()) is never constructed — belt-and-suspenders with the
    # stream guard above. The packaged binary is windowed and has no console to log
    # to anyway; dev uses `python -m uvicorn` and is unaffected.
    uvicorn.run(app, host=host, port=port, log_level="info", log_config=None)


if __name__ == "__main__":
    main()
