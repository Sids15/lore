"""Tests for the evaluation harness (no network: answer/retrieve/embed mocked)."""

from __future__ import annotations

import asyncio

from app.eval import harness
from app.eval.harness import EvalReport
from app.query.answer import AnswerResponse
from app.retrieval.hybrid import RetrievedChunk


def _write_eval(repo_dir):
    repo_dir.mkdir(parents=True)
    (repo_dir / ".lore").mkdir()
    (repo_dir / ".lore" / "eval.yml").write_text(
        "questions:\n"
        "  - q: 'where is retry?'\n"
        "    relevant: ['app/llm/ollama_client.py']\n"
        "  - q: 'say hi'\n",
        encoding="utf-8",
    )


def _chunk(file_path: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=file_path, repo="r", file_path=file_path, language="python",
        kind="function", symbol="f", qualified_name=f"{file_path}::f",
        start_line=1, end_line=2, code="...", score=1.0,
    )


def _patch(monkeypatch, *, grounded=True, retrieved_file="app/llm/ollama_client.py"):
    async def fake_answer(question, *, k=None, settings=None):
        return AnswerResponse(answer="Some answer.", sources=[], grounded=grounded)

    async def fake_retrieve(question, *, k=None, settings=None):
        return [_chunk(retrieved_file)]

    async def fake_embed(base_url, model, text, **kwargs):
        return [1.0, 0.0, 0.0]  # identical vectors -> relevancy 1.0

    monkeypatch.setattr(harness, "answer_question", fake_answer)
    monkeypatch.setattr(harness.hybrid, "retrieve", fake_retrieve)
    monkeypatch.setattr(harness.ollama_client, "embed", fake_embed)


def test_eval_computes_metrics(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_eval(repo)
    _patch(monkeypatch, grounded=True)

    job = asyncio.run(harness.run_eval(repo))
    assert job.state == "done"
    report: EvalReport = job.report
    assert report.total == 2
    assert report.faithfulness == 1.0
    assert report.recall_at_k == 1.0  # the labelled question's file was retrieved
    assert 0.99 <= report.answer_relevancy <= 1.0
    # second question has no labels -> recall_hit None
    assert any(r.recall_hit is None for r in report.per_question)


def test_recall_miss(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    _write_eval(repo)
    _patch(monkeypatch, grounded=False, retrieved_file="some/other/file.py")

    job = asyncio.run(harness.run_eval(repo))
    assert job.report.faithfulness == 0.0
    assert job.report.recall_at_k == 0.0  # relevant file not retrieved


def test_missing_eval_file_marks_unconfigured(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch(monkeypatch)

    job = asyncio.run(harness.run_eval(repo))
    assert job.state == "done"
    assert job.configured is False
    assert job.report is None
