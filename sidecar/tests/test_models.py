"""Tests for the model-pull client + endpoint (no network)."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

from app.llm import ollama_client


# --- faked httpx streaming client (mirrors test_ollama_stream) -----------------


class _FakeResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCtx:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> _FakeResponse:
        return _FakeResponse(self._lines)

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakeClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def stream(self, method: str, url: str, json=None):  # noqa: A002 - mirror httpx
        return _FakeStreamCtx(self._lines)


def _collect(agen) -> list[dict]:
    async def run() -> list[dict]:
        return [record async for record in agen]

    return asyncio.run(run())


def test_pull_model_yields_records(monkeypatch):
    lines = [
        json.dumps({"status": "pulling manifest"}),
        json.dumps({"status": "downloading", "total": 100, "completed": 40}),
        json.dumps({"status": "success"}),
    ]
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines))

    records = _collect(ollama_client.pull_model("http://x", "qwen3:8b"))
    assert [r["status"] for r in records] == ["pulling manifest", "downloading", "success"]
    assert records[1]["completed"] == 40


def test_pull_model_skips_malformed_lines(monkeypatch):
    lines = ["not json", json.dumps({"status": "success"})]
    monkeypatch.setattr(ollama_client.httpx, "AsyncClient", lambda *a, **k: _FakeClient(lines))

    records = _collect(ollama_client.pull_model("http://x", "m"))
    assert [r["status"] for r in records] == ["success"]


def test_pull_endpoint_streams_progress_then_done(monkeypatch):
    import app.api.models as models_api
    import app.main as main

    async def fake_pull(base_url, model):
        yield {"status": "downloading", "total": 10, "completed": 5}
        yield {"status": "success"}

    monkeypatch.setattr(models_api.ollama_client, "pull_model", fake_pull)

    client = TestClient(main.app)
    resp = client.post("/models/pull", json={"model": "qwen3:8b"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")

    events = [json.loads(line) for line in resp.text.strip().splitlines()]
    assert events[0]["type"] == "progress"
    assert events[0]["completed"] == 5
    assert events[-1] == {"type": "done"}


def test_pull_endpoint_rejects_empty_model():
    import app.main as main

    client = TestClient(main.app)
    resp = client.post("/models/pull", json={"model": "  "})
    assert resp.status_code == 400
