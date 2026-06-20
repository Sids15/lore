"""Exit the sidecar if its parent (the Tauri shell) goes away.

The Tauri shell launches the sidecar with a piped stdin and keeps the write end
open for the lifetime of the app. If the shell exits for *any* reason — including
a hard kill where graceful shutdown never runs (e.g. Ctrl+C in a dev terminal) —
the operating system closes that pipe, this watchdog observes EOF on stdin, and
the sidecar terminates itself. That prevents an orphaned server from holding the
port and blocking the next launch.

The watchdog only runs when the shell explicitly enables it via the
``LORE_PARENT_WATCHDOG`` environment variable, so running the sidecar standalone
(e.g. ``uvicorn`` from a terminal for backend work) is unaffected.
"""

from __future__ import annotations

import os
import sys
import threading

ENABLE_ENV = "LORE_PARENT_WATCHDOG"


def _watch_stdin() -> None:
    """Block on stdin until EOF (parent closed the pipe), then exit hard."""
    try:
        while sys.stdin.readline() != "":
            continue
    except (ValueError, OSError):
        # stdin was closed/invalidated — treat as parent gone.
        pass
    # Bypass interpreter shutdown handlers; we want to free the port immediately.
    os._exit(0)


def start() -> bool:
    """Start the watchdog thread if enabled. Returns True if started."""
    if os.environ.get(ENABLE_ENV) != "1":
        return False
    thread = threading.Thread(target=_watch_stdin, name="parent-watchdog", daemon=True)
    thread.start()
    return True
