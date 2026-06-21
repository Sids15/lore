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
from app.llm import ollama_client
from app.llm.parsing import parse_json_object
from app.retrieval import hybrid
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

_NO_CONTEXT_ANSWER = (
    "I couldn't find anything relevant in the indexed code. "
    "Make sure the repository has been indexed, then try again."
)


class AnswerResponse(BaseModel):
    """A grounded answer plus the sources it was built from."""

    answer: str
    sources: list[RetrievedChunk]
    grounded: bool
    unsupported: list[str] = []


def _format_context(chunks: list[RetrievedChunk]) -> str:
    """Render chunks as numbered, citable snippets for the prompt."""
    blocks = []
    for index, chunk in enumerate(chunks, start=1):
        header = (
            f"[{index}] {chunk.file_path}:{chunk.start_line}-{chunk.end_line} "
            f"({chunk.kind} {chunk.symbol})"
        )
        blocks.append(f"{header}\n{chunk.code}")
    return "\n\n".join(blocks)


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


async def answer_question(
    question: str,
    *,
    k: int | None = None,
    settings: Settings | None = None,
) -> AnswerResponse:
    """Answer a question about the indexed code, with a grounding check."""
    settings = settings or get_settings()

    retrieved = await hybrid.retrieve(question, k=k, settings=settings)
    context_chunks = retrieved[: settings.answer_context_k]
    if not context_chunks:
        return AnswerResponse(answer=_NO_CONTEXT_ANSWER, sources=[], grounded=True)

    context = _format_context(context_chunks)
    prompt = f"Context snippets:\n\n{context}\n\nQuestion: {question}\n\nAnswer:"
    answer = await ollama_client.generate(
        settings.ollama_url,
        settings.generation_model,
        prompt,
        system=_ANSWER_SYSTEM,
    )

    grounded, unsupported = True, []
    if settings.grounding_enabled:
        grounded, unsupported = await _check_grounding(answer, context, settings)

    return AnswerResponse(
        answer=answer,
        sources=context_chunks,
        grounded=grounded,
        unsupported=unsupported,
    )
