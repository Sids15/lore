"""Tests for the refactor suggestion + API (no network)."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.refactor import suggest as suggest_mod
from app.refactor.candidates import RefactorCandidate
from app.refactor.suggest import suggest_refactor
from app.retrieval.hybrid import RetrievedChunk


def _candidate() -> RefactorCandidate:
    return RefactorCandidate(
        id="abc123",
        kind="cycle",
        severity="high",
        title="Circular dependency among 2 files",
        summary="a.py and b.py import each other.",
        files=["a.py", "b.py"],
    )


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c",
        repo="r",
        file_path="a.py",
        language="python",
        kind="module",
        symbol="a.py",
        qualified_name="a.py::<module>",
        start_line=1,
        end_line=2,
        code="import b",
        score=1.0,
    )


def test_suggest_uses_retrieved_code(monkeypatch):
    captured: dict = {}

    async def fake_retrieve(question, *, k=None, settings=None):
        captured["q"] = question
        return [_chunk()]

    async def fake_generate(base_url, model, prompt, *, system=None, **kwargs):
        captured["prompt"] = prompt
        return "1. Extract the shared piece into c.py."

    monkeypatch.setattr(suggest_mod.hybrid, "retrieve", fake_retrieve)
    monkeypatch.setattr(suggest_mod.ollama_client, "generate", fake_generate)

    out = asyncio.run(suggest_refactor(_candidate(), Settings()))
    assert "Extract" in out
    assert "import b" in captured["prompt"]  # grounded in the retrieved code


def test_suggest_fails_open(monkeypatch):
    async def fake_retrieve(question, *, k=None, settings=None):
        return []

    async def boom(*args, **kwargs):
        import httpx

        raise httpx.ConnectError("down")

    monkeypatch.setattr(suggest_mod.hybrid, "retrieve", fake_retrieve)
    monkeypatch.setattr(suggest_mod.ollama_client, "generate", boom)

    out = asyncio.run(suggest_refactor(_candidate(), Settings()))
    assert "Couldn't generate" in out


def test_refactor_endpoint_lists_candidates(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import app.api.refactor as refactor_api
    import app.main as main

    def fake_detect(conn, repo, settings):
        return [_candidate()]

    monkeypatch.setattr(refactor_api, "detect_candidates", fake_detect)
    monkeypatch.setattr(refactor_api, "get_settings", lambda: Settings(data_dir=tmp_path / "data"))

    client = TestClient(main.app)
    resp = client.get("/refactor")
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"][0]["kind"] == "cycle"
