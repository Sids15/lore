"""Grounded question answering over the Code Index.

Pipeline: retrieve the most relevant chunks -> assemble them into a context ->
ask the LLM to answer **only** from that context with inline citations -> run a
second LLM pass that checks whether the answer is actually supported by the
sources (faithfulness/grounding). The grounding pass fails open: if it errors or
returns unparseable output, the answer is still returned (marked grounded) so a
flaky check never blocks a useful response.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.docs.retrieval import DocHit
from app.history.retrieval import CommitHit
from app.llm import ollama_client
from app.llm.parsing import parse_json_object
from app.query import context, router
from app.query.condense import ConversationTurn, condense_question, format_history
from app.query.expand import expand_query
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


def _build_prompt(question: str, context_text: str, conversation: str) -> str:
    convo = f"Conversation so far:\n{conversation}\n\n" if conversation else ""
    return f"{convo}Context snippets:\n\n{context_text}\n\nQuestion: {question}\n\nAnswer:"


async def _generate_answer(
    question: str, context_text: str, settings: Settings, *, conversation: str = ""
) -> str:
    prompt = _build_prompt(question, context_text, conversation)
    return await ollama_client.generate(
        settings.ollama_url, settings.generation_model, prompt, system=_ANSWER_SYSTEM
    )


async def _answer_from_bundle(
    question: str,
    bundle: context.RetrievalBundle,
    route: router.RouteDecision,
    settings: Settings,
    *,
    corrected: bool,
    conversation: str = "",
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
    answer = await _generate_answer(question, context_text, settings, conversation=conversation)

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
    history: list[ConversationTurn] | None = None,
) -> AnswerResponse:
    """Answer a question: condense → route → gather → generate → ground → self-correct.

    ``history`` (prior turns) enables follow-ups: it is condensed into a standalone
    question for routing/retrieval and shown to generation as conversation context.
    """
    settings = settings or get_settings()
    history = history or []
    # Resolve follow-ups ("explain that") into a standalone retrieval question.
    retrieval_q = await condense_question(question, history, settings)
    conversation = format_history(history, settings.conversation_max_turns) if history else ""
    route = await router.classify(retrieval_q, settings)

    if route.trivial:
        answer = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, question, system=_TRIVIAL_SYSTEM
        )
        return AnswerResponse(
            answer=answer, sources=[], grounded=True, categories=route.categories
        )

    expansions = await expand_query(retrieval_q, settings)
    bundle = await context.gather(retrieval_q, route, settings, k=k, extra_queries=expansions)
    had_context = bool(bundle.chunks or bundle.graph_notes or bundle.commits or bundle.docs)
    result = await _answer_from_bundle(
        question, bundle, route, settings, corrected=False, conversation=conversation
    )

    # Self-correction: re-retrieve using the grounding pass's unsupported claims and
    # regenerate. Normally one round; with iterative mode on, up to
    # iterative_max_rounds-1 rounds, each driven by the latest answer's claims.
    # Best-effort: any failure here keeps the current result rather than failing.
    if settings.self_correct_enabled and (not had_context or not result.grounded):
        max_corrections = (
            settings.iterative_max_rounds - 1 if settings.iterative_enabled else 1
        )
        # `result` is the answer we'll return (conservatively the first pass);
        # `claims_source` is whose unsupported claims drive the next retrieval.
        claims_source = result
        for _ in range(max_corrections):
            try:
                claims = claims_source.unsupported[: settings.correction_max_claims]
                broadened = await context.gather(
                    retrieval_q, route, settings, k=k, broaden=True, extra_queries=claims
                )
                if not (broadened.chunks or broadened.graph_notes or broadened.docs):
                    break  # nothing new to add
                retry = await _answer_from_bundle(
                    question, broadened, route, settings, corrected=True, conversation=conversation
                )
            except (httpx.HTTPError, ValueError):
                break  # any failure here keeps the current result, not a 500
            if not had_context:
                # We had nothing before; any answer beats none. Adopt it and keep
                # seeking grounding in further rounds.
                result = retry
                had_context = True
            elif retry.grounded:
                result = retry
            if retry.grounded:
                break  # success
            # Still ungrounded: drive the next round off the retry's fresh claims.
            claims_source = retry

    return result


# --- Streaming variant --------------------------------------------------------
#
# Emits the same answer as `answer_question`, but as a sequence of NDJSON events
# (see the protocol below) so the UI can render tokens as they arrive. The
# retrieval/grounding stack is reused unchanged; only generation is streamed.
#
#   meta    -> {categories, graph_used, sources, commits, docs}  (before tokens)
#   status  -> {stage: "generating"|"verifying"|"refining"}
#   token   -> {text}                                            (answer delta)
#   replace -> {}                  (self-correction restarts the answer)
#   final   -> {grounded, unsupported, corrected}               (terminal)


def _meta_event(route: router.RouteDecision, bundle: context.RetrievalBundle) -> dict:
    """Build the early `meta` event: tags + sources the UI can show immediately."""
    return {
        "type": "meta",
        "categories": route.categories,
        "graph_used": bundle.graph_used,
        "sources": [c.model_dump() for c in bundle.chunks],
        "commits": [c.model_dump() for c in bundle.commits],
        "docs": [d.model_dump() for d in bundle.docs],
    }


async def _stream_and_ground(
    question: str,
    bundle: context.RetrievalBundle,
    route: router.RouteDecision,
    settings: Settings,
    result: dict,
    *,
    conversation: str = "",
) -> AsyncIterator[dict]:
    """Stream meta + answer tokens for one pass, then ground into ``result``.

    Yields the public events for the pass (meta, status, token) but not the
    terminal ``final`` — the caller emits that after deciding on self-correction.
    The grounding outcome is written to ``result`` (keys: grounded, unsupported).
    """
    yield _meta_event(route, bundle)
    yield {"type": "status", "stage": "generating"}

    context_text = context.format_context(bundle)
    prompt = _build_prompt(question, context_text, conversation)
    parts: list[str] = []
    async for delta in ollama_client.generate_stream(
        settings.ollama_url, settings.generation_model, prompt, system=_ANSWER_SYSTEM
    ):
        parts.append(delta)
        yield {"type": "token", "text": delta}

    grounded, unsupported = True, []
    if settings.grounding_enabled:
        yield {"type": "status", "stage": "verifying"}
        grounded, unsupported = await _check_grounding("".join(parts), context_text, settings)
    result["grounded"] = grounded
    result["unsupported"] = unsupported


def _final(grounded: bool, unsupported: list[str], corrected: bool) -> dict:
    return {
        "type": "final",
        "grounded": grounded,
        "unsupported": unsupported,
        "corrected": corrected,
    }


def _empty_meta(route: router.RouteDecision) -> dict:
    return {
        "type": "meta",
        "categories": route.categories,
        "graph_used": False,
        "sources": [],
        "commits": [],
        "docs": [],
    }


async def answer_question_stream(
    question: str,
    *,
    k: int | None = None,
    settings: Settings | None = None,
    history: list[ConversationTurn] | None = None,
) -> AsyncIterator[dict]:
    """Answer a question as a stream of NDJSON events (see protocol above).

    ``history`` enables follow-ups (condensed for retrieval, shown to generation).
    """
    settings = settings or get_settings()
    history = history or []
    retrieval_q = await condense_question(question, history, settings)
    conversation = format_history(history, settings.conversation_max_turns) if history else ""
    route = await router.classify(retrieval_q, settings)

    # Trivial: no retrieval — stream a short reply directly.
    if route.trivial:
        yield _empty_meta(route)
        yield {"type": "status", "stage": "generating"}
        async for delta in ollama_client.generate_stream(
            settings.ollama_url, settings.generation_model, question, system=_TRIVIAL_SYSTEM
        ):
            yield {"type": "token", "text": delta}
        yield _final(True, [], False)
        return

    expansions = await expand_query(retrieval_q, settings)
    bundle = await context.gather(retrieval_q, route, settings, k=k, extra_queries=expansions)
    had_context = bool(bundle.chunks or bundle.graph_notes or bundle.commits or bundle.docs)

    # Nothing retrieved: try one broaden pass, else emit the canned message.
    if not had_context:
        broadened = (
            await context.gather(retrieval_q, route, settings, k=k, broaden=True)
            if settings.self_correct_enabled
            else None
        )
        if broadened and (broadened.chunks or broadened.graph_notes or broadened.docs):
            res: dict = {}
            async for event in _stream_and_ground(
                question, broadened, route, settings, res, conversation=conversation
            ):
                yield event
            yield _final(res["grounded"], res["unsupported"], True)
            return
        yield _empty_meta(route)
        yield {"type": "token", "text": _NO_CONTEXT_ANSWER}
        yield _final(True, [], False)
        return

    # First pass.
    first: dict = {}
    async for event in _stream_and_ground(
        question, bundle, route, settings, first, conversation=conversation
    ):
        yield event

    # Self-correction: re-retrieve using the grounding pass's unsupported claims and
    # regenerate. Normally one round; with iterative mode on, up to
    # iterative_max_rounds-1 rounds, each driven by the latest pass's claims. A
    # correction is committed (swapping the displayed answer) ONLY if it grounds —
    # otherwise the first pass stays, matching the conservative blocking path so
    # /query and /query/stream agree. Best-effort: a failure keeps the first pass.
    if settings.self_correct_enabled and not first["grounded"]:
        max_corrections = (
            settings.iterative_max_rounds - 1 if settings.iterative_enabled else 1
        )
        claims = first["unsupported"]
        for _ in range(max_corrections):
            try:
                broadened = await context.gather(
                    retrieval_q, route, settings, k=k, broaden=True,
                    extra_queries=claims[: settings.correction_max_claims],
                )
                if not (broadened.chunks or broadened.graph_notes or broadened.docs):
                    break  # nothing new to add
                retry = await _answer_from_bundle(
                    question, broadened, route, settings, corrected=True, conversation=conversation
                )
            except (httpx.HTTPError, ValueError):
                break  # keep the first pass
            if retry.grounded:
                # Commit the grounded improvement: swap the answer + sources.
                yield {"type": "status", "stage": "refining"}
                yield {"type": "replace"}
                yield _meta_event(route, broadened)
                yield {"type": "token", "text": retry.answer}
                yield _final(True, retry.unsupported, True)
                return
            claims = retry.unsupported  # still ungrounded: drive the next round

    yield _final(first["grounded"], first["unsupported"], False)  # no round grounded
