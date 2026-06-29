"""Tests for the parent-watchdog (sidecar exits when its parent pipe closes)."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

from app import parent_watchdog

SIDECAR_DIR = Path(__file__).resolve().parents[1]


def test_disabled_when_env_not_set(monkeypatch):
    monkeypatch.delenv(parent_watchdog.ENABLE_ENV, raising=False)
    assert parent_watchdog.start() is False


def test_enabled_when_env_set(monkeypatch):
    monkeypatch.setenv(parent_watchdog.ENABLE_ENV, "1")
    # No-op the reader so the spawned thread can't read pytest's stdin and call
    # os._exit on EOF (which would hard-kill the whole test run).
    monkeypatch.setattr(parent_watchdog, "_watch_stdin", lambda *a, **k: None)
    assert parent_watchdog.start() is True


def test_watch_stdin_exits_on_eof():
    """The reader exits with 0 once the stream reaches EOF (in-process, safe)."""
    codes: list[int] = []

    # Empty stream → immediate EOF.
    parent_watchdog._watch_stdin(io.StringIO(""), exit_fn=codes.append)
    assert codes == [0]

    # Drains existing lines, then exits with 0 at EOF.
    codes.clear()
    parent_watchdog._watch_stdin(io.StringIO("line1\nline2\n"), exit_fn=codes.append)
    assert codes == [0]


def test_child_exits_when_stdin_closes():
    """Simulate the parent dying: a child running the watchdog must exit on EOF."""
    code = (
        "from app import parent_watchdog;"
        "parent_watchdog.start();"
        "import time; time.sleep(30)"
    )
    env = {**os.environ, parent_watchdog.ENABLE_ENV: "1"}
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        cwd=str(SIDECAR_DIR),
        env=env,
    )
    try:
        # Closing stdin delivers EOF to the watchdog, just like a parent exit.
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0
