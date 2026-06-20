"""Lore sidecar — the Python backend that performs the RAG/ML work.

The sidecar is a FastAPI HTTP service launched and supervised by the Tauri
desktop shell. The React frontend talks to it over local HTTP.
"""

__version__ = "0.1.0"
