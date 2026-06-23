"""Grounded question answering over the Code Index.

Pipeline: retrieve the most relevant chunks -> assemble them into a context ->
ask the LLM to answer **only** from that context with inline citations -> run a
second LLM pass that checks whether the answer is actually supported by the
sources (faithfulness/grounding). The grounding pass fails open: if it errors or
returns unparseable output, the answer is still returned (marked grounded) so a
flaky check never blocks a useful response.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.docs.retrieval import DocHit
from app.history.retrieval import CommitHit
from app.llm import ollama_client
from app.llm.parsing import parse_json_object
from app.query import context, router
from app.retrieval.hybrid import RetrievedChunk

_ANSWER_SYSTEM = (
    "You are Lore, an assistant that answers questions about a specific codebase. "
    "Answer using ONLY the provided context snippets. Cite the snippets you use inline "
    "as [file:line]. Be concise and concrete. If the context does not contain the answer, "
    "say so plainly instead of guessing."
)

_GROUNDING_SYSTEM = (
    "You verify whether an answer is fully supported by the provided source snippets. "
    'Respond with ONLY a JSON object: {"grounded": <true|false>, "unsupported": '
    '[<short description of each claim not supported by the sources>]}.'
)

_TRIVIAL_SYSTEM = (
    "You are Lore, an assistant for asking questions about a codebase. The user's "
    "message does not require looking at code. Reply briefly and helpfully."
)

_NO_CONTEXT_ANSWER = (
    "I couldn't find anything relevant in the indexed code. "
    "Make sure the repository has been indexed, then try again."
)


class AnswerResponse(BaseModel):
    """A grounded answer plus the sources and how it was produced."""

    answer: str
    sources: list[RetrievedChunk]
    grounded: bool
    unsupported: list[str] = []
    categories: list[str] = []  # the router's classification of the question
    graph_used: bool = False  # whether graph context was folded in
    corrected: bool = False  # whether a self-correction retry produced this answer
    commits: list[CommitHit] = []  # git-history commits cited in the answer
    docs: list[DocHit] = []  # documentation chunks cited in the answer


async def _check_grounding(
    answer: str, context: str, settings: Settings
) -> tuple[bool, list[str]]:
    """Second LLM pass: is every claim in the answer supported by the context?"""
    prompt = (
        f"Source snippets:\n\n{context}\n\n"
        f"Answer to verify:\n{answer}\n\n"
        "Is every claim in the answer supported by the sources?"
    )
    try:
        raw = await ollama_client.generate(
            settings.ollama_url,
            settings.generation_model,
            prompt,
            system=_GROUNDING_SYSTEM,
        )
    except (httpx.HTTPError, ValueError):
        return True, []  # fail open: don't block the answer on a failed check

    data = parse_json_object(raw)
    if data is None:
        return True, []
    return bool(data.get("grounded", True)), list(data.get("unsupported") or [])


async def _generate_answer(question: str, context_text: str, settings: Settings) -> str:
    prompt = f"Context snippets:\n\n{context_text}\n\nQuestion: {question}\n\nAnswer:"
    return await ollama_client.generate(
        settings.ollama_url, settings.generation_model, prompt, system=_ANSWER_SYSTEM
    )


async def _answer_from_bundle(
    question: str,
    bundle: context.RetrievalBundle,
    route: "router.RouteDecision",
    settings: Settings,
    *,
    corrected: bool,
) -> AnswerResponse:
    """Generate + ground an answer from a gathered context bundle."""
    if not bundle.chunks and not bundle.graph_notes and not bundle.commits and not bundle.docs:
        return AnswerResponse(
            answer=_NO_CONTEXT_ANSWER,
            sources=[],
            grounded=True,
            categories=route.categories,
            corrected=corrected,
        )

    context_text = context.format_context(bundle)
    answer = await _generate_answer(question, context_text, settings)

    grounded, unsupported = True, []
    if settings.grounding_enabled:
        grounded, unsupported = await _check_grounding(answer, context_text, settings)

    return AnswerResponse(
        answer=answer,
        sources=bundle.chunks,
        grounded=grounded,
        unsupported=unsupported,
        categories=route.categories,
        graph_used=bundle.graph_used,
        corrected=corrected,
        commits=bundle.commits,
        docs=bundle.docs,
    )


async def answer_question(
    question: str,
    *,
    k: int | None = None,
    settings: Settings | None = None,
) -> AnswerResponse:
    """Answer a question: route → gather (GraphRAG) → generate → ground → self-correct."""
    settings = settings or get_settings()
    route = await router.classify(question, settings)

    if route.trivial:
        answer = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, question, system=_TRIVIAL_SYSTEM
        )
        return AnswerResponse(
            answer=answer, sources=[], grounded=True, categories=route.categories
        )

    bundle = await context.gather(question, route, settings, k=k)
    had_context = bool(bundle.chunks or bundle.graph_notes or bundle.commits or bundle.docs)
    result = await _answer_from_bundle(question, bundle, route, settings, corrected=False)

    # Self-correction: one broaden+retry pass when the answer is weak.
    if settings.self_correct_enabled and (not had_context or not result.grounded):
        broadened = await context.gather(question, route, settings, k=k, broaden=True)
        if broadened.chunks or broadened.graph_notes or broadened.docs:
            retry = await _answer_from_bundle(
                question, broadened, route, settings, corrected=True
            )
            # Take the retry if we had nothing before, or if it is now grounded.
            if not had_context or retry.grounded:
                result = retry

    return result
