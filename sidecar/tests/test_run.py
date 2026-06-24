"""Tests for the frozen entry point's stream guard."""

from __future__ import annotations

import sys
from importlib import import_module


def test_ensure_std_streams_replaces_none(monkeypatch):
    run = import_module("run")  # sidecar/run.py

    # Simulate PyInstaller's windowed build, where both streams are None.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    run._ensure_std_streams()

    # The original crash was AttributeError on None.isatty(); after the guard the
    # streams exist and isatty() returns a bool without raising. (On Windows the
    # null device reports isatty()==True, which is harmless.)
    assert sys.stdout is not None and sys.stderr is not None
    assert isinstance(sys.stdout.isatty(), bool)
    assert isinstance(sys.stderr.isatty(), bool)
    sys.stdout.write("")  # writable


def test_ensure_std_streams_keeps_existing(monkeypatch):
    run = import_module("run")
    sentinel_out, sentinel_err = sys.stdout, sys.stderr
    run._ensure_std_streams()
    # Real streams are left untouched.
    assert sys.stdout is sentinel_out
    assert sys.stderr is sentinel_err
