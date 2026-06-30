"""Runtime settings overrides, persisted to a JSON file in the data dir.

Settings normally come from env / ``.env`` and are fixed for the process lifetime.
To let the UI change a curated subset of knobs **live** (no restart), we persist
those overrides to ``<data_dir>/settings.json`` and layer them over env when
building :class:`Settings` (``Settings(**overrides)`` — explicit kwargs win). The
API clears the ``get_settings`` cache after saving so the next request rebuilds.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import ValidationError

from app.config import Settings

_OVERRIDES_FILE = "settings.json"

# Serializes the read-modify-write in merge_overrides. The sidecar is a single
# process; FastAPI runs sync handlers in a threadpool, so a plain Lock (not a
# cross-process file lock) is enough to keep concurrent PATCHes from racing.
_write_lock = threading.Lock()


def _overrides_path() -> Path:
    # A plain Settings() reads env only (no overrides), so this never recurses
    # with the overrides-applying get_settings(). data_dir is not a UI knob.
    return Settings().data_path / _OVERRIDES_FILE


def _drop_invalid(overrides: dict) -> dict:
    """Return only the overrides that validate against Settings.

    A persisted value that no longer validates (a corrupted/hand-edited file, or a
    future bound change) must never brick the sidecar: we drop the offending keys
    rather than let Settings(**overrides) raise. The next save rewrites a clean file.
    """
    data = dict(overrides)
    while data:
        try:
            Settings(**data)
            return data
        except ValidationError as error:
            bad = {str(loc[0]) for loc in (e.get("loc") for e in error.errors()) if loc}
            # Only keys actually in `data` are removable — if the error comes from
            # elsewhere (e.g. a bad LORE_* env value), give up rather than spin.
            removable = bad & data.keys()
            if not removable:
                return {}
            for key in removable:
                data.pop(key)
    return data


def load_overrides() -> dict:
    """Return the persisted, *valid* overrides ({} when absent/unreadable/invalid).

    Fail open at every layer: unreadable/non-dict file -> {}, and any individual
    entry that no longer validates is dropped (see :func:`_drop_invalid`).
    """
    path = _overrides_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return _drop_invalid(data)


def save_overrides(overrides: dict) -> None:
    """Persist the overrides dict as JSON atomically, creating the data dir if needed.

    Write to a sibling ``*.tmp`` then ``os.replace`` it onto the real path: the swap
    is atomic on Windows and POSIX (same directory), so a concurrent ``load_overrides``
    never reads a half-written file, and a crash mid-write can't truncate the original.
    """
    path = _overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(overrides, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def merge_overrides(changes: dict) -> dict:
    """Atomically merge ``changes`` into the persisted overrides; return the result.

    The whole read-modify-write runs under ``_write_lock`` so two concurrent PATCHes
    can't both read the same base and clobber each other (lost update). The merged set
    is validated by constructing :class:`Settings` before persisting — a value that
    doesn't validate raises ``ValidationError`` (the API maps it to 422) and nothing is
    written.
    """
    with _write_lock:
        merged = {**load_overrides(), **changes}
        Settings(**merged)  # validate before persisting; raises ValidationError
        save_overrides(merged)
        return merged
