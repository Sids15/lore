"""Tests for the parent-watchdog (sidecar exits when its parent pipe closes)."""

from __future__ import annotations

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
    # Provided the process has a real stdin; in pytest this is fine.
    assert parent_watchdog.start() is True


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
