"""Evaluation harness: run a golden question set and compute quality metrics.

Metrics (all local):
* **faithfulness** — fraction of answers the grounding pass marks grounded.
* **retrieval recall@k** — fraction of labelled questions whose `relevant` file(s)
  appear in the top-k retrieved chunks (only over questions that have labels).
* **answer relevancy** — mean cosine similarity between the question and answer
  embeddings (a local proxy for relevancy).
"""

from __future__ import annotations

import math
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.config import get_settings
from app.llm import ollama_client
from app.query.answer import answer_question
from app.retrieval import hybrid

EVAL_RELATIVE_PATH = ".lore/eval.yml"


class EvalQuestion(BaseModel):
    q: str
    relevant: list[str] = []


class EvalSet(BaseModel):
    questions: list[EvalQuestion] = []


class EvalQuestionResult(BaseModel):
    question: str
    grounded: bool
    recall_hit: bool | None  # None when the question has no `relevant` labels
    relevancy: float


class EvalReport(BaseModel):
    total: int
    faithfulness: float
    answer_relevancy: float
    recall_at_k: float | None  # None when no question is labelled
    per_question: list[EvalQuestionResult]


class EvalJob(BaseModel):
    state: str = "idle"  # idle | running | done | error
    repo: str | None = None
    total: int = 0
    processed: int = 0
    configured: bool = True  # whether a .lore/eval.yml was found
    message: str | None = None
    report: EvalReport | None = None


_job = EvalJob()


def current_job() -> EvalJob:
    return _job


def is_running() -> bool:
    return _job.state == "running"


def mark_running(repo: str) -> EvalJob:
    global _job
    _job = EvalJob(state="running", repo=repo, message="Queued…")
    return _job


def load_eval_set(repo_root: Path) -> EvalSet | None:
    """Load `.lore/eval.yml`, or None if absent. Raises ValueError on bad YAML."""
    path = repo_root / EVAL_RELATIVE_PATH
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return EvalSet.model_validate(raw)
    except (yaml.YAMLError, ValueError) as error:
        raise ValueError(f"Invalid {EVAL_RELATIVE_PATH}: {error}") from error


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _recall_hit(relevant: list[str], retrieved_files: set[str]) -> bool:
    for rel in relevant:
        if any(f == rel or f.endswith("/" + rel) or f.endswith(rel) for f in retrieved_files):
            return True
    return False


def _aggregate(results: list[EvalQuestionResult]) -> EvalReport:
    total = len(results)
    faithfulness = sum(1 for r in results if r.grounded) / total if total else 0.0
    relevancy = sum(r.relevancy for r in results) / total if total else 0.0
    labelled = [r for r in results if r.recall_hit is not None]
    recall = (sum(1 for r in labelled if r.recall_hit) / len(labelled)) if labelled else None
    return EvalReport(
        total=total,
        faithfulness=faithfulness,
        answer_relevancy=relevancy,
        recall_at_k=recall,
        per_question=results,
    )


async def run_eval(repo_path: Path) -> EvalJob:
    """Run the eval set for a repo and store the report in the job."""
    global _job
    # Eval needs a stable, bounded config regardless of runtime UI overrides:
    # force the grounding pass on (faithfulness is measured from it) and the
    # iterative loop off (otherwise a grounded-off + iterative-on UI state would
    # balloon each ungrounded question into many retrieval/LLM rounds).
    settings = get_settings().model_copy(
        update={"grounding_enabled": True, "iterative_enabled": False}
    )
    _job = EvalJob(state="running", repo=repo_path.name, message="Loading eval set…")

    try:
        eval_set = load_eval_set(repo_path)
        if eval_set is None:
            _job.state, _job.configured, _job.message = "done", False, "No .lore/eval.yml found"
            return _job
        if not eval_set.questions:
            _job.state, _job.message = "done", "Eval set is empty"
            return _job

        _job.total = len(eval_set.questions)
        _job.message = "Evaluating…"
        results: list[EvalQuestionResult] = []

        for item in eval_set.questions:
            response = await answer_question(item.q, settings=settings)

            q_vec = await ollama_client.embed(
                settings.ollama_url, settings.embedding_model, item.q
            )
            a_vec = (
                await ollama_client.embed(
                    settings.ollama_url, settings.embedding_model, response.answer
                )
                if response.answer.strip()
                else []
            )
            relevancy = _cosine(q_vec, a_vec)

            recall_hit: bool | None = None
            if item.relevant:
                hits = await hybrid.retrieve(item.q, k=settings.eval_k, settings=settings)
                recall_hit = _recall_hit(item.relevant, {h.file_path for h in hits})

            results.append(
                EvalQuestionResult(
                    question=item.q,
                    grounded=response.grounded,
                    recall_hit=recall_hit,
                    relevancy=relevancy,
                )
            )
            _job.processed += 1

        _job.report = _aggregate(results)
        _job.state = "done"
        _job.message = f"Evaluated {len(results)} questions"
    except Exception as error:  # noqa: BLE001 - surface any failure to the UI
        _job.state = "error"
        _job.message = str(error)

    return _job
