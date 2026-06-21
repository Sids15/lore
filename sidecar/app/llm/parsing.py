"""Lenient parsing of structured output from local LLMs.

Models often wrap JSON in prose or code fences; this extracts the first JSON
object and parses it, returning None when nothing usable is found.
"""

from __future__ import annotations

import json
import re

_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_object(text: str) -> dict | None:
    """Extract and parse the first JSON object in ``text``, or return None."""
    match = _OBJECT_RE.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
