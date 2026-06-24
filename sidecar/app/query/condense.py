"""Conversation memory: condense a follow-up into a standalone question.

A follow-up like "explain that further" has almost no retrieval signal on its
own. Before routing/retrieval we rewrite it into a self-contained question using
the recent turns (the classic conversational-RAG "condense" step). The recent
turns are also formatted into a short block that generation can reference.

Best-effort: with no history, when disabled, or on any LLM failure, the original
question is returned unchanged so answering always proceeds.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.llm import ollama_client

# Cap each remembered answer so the prompt stays bounded regardless of length.
_MAX_ANSWER_CHARS = 600

_CONDENSE_SYSTEM = (
    "You rewrite a user's follow-up question into a standalone question using the "
    "conversation for context. Resolve pronouns and references (e.g. 'that', 'it') "
    "to what they refer to. If the question is already standalone, return it "
    "unchanged. Respond with ONLY the rewritten question, no preamble."
)


class ConversationTurn(BaseModel):
    """One prior exchange in the conversation."""

    question: str
    answer: str


def format_history(history: list[ConversationTurn], max_turns: int) -> str:
    """Render the most-recent turns as a compact 'User:/Lore:' transcript."""
    lines: list[str] = []
    for turn in history[-max_turns:]:
        answer = turn.answer.strip()
        if len(answer) > _MAX_ANSWER_CHARS:
            answer = answer[:_MAX_ANSWER_CHARS] + "…"
        lines.append(f"User: {turn.question.strip()}")
        lines.append(f"Lore: {answer}")
    return "\n".join(lines)


async def condense_question(
    question: str, history: list[ConversationTurn], settings: Settings
) -> str:
    """Rewrite a follow-up into a standalone question. Never raises."""
    if not history or not settings.conversation_enabled:
        return question

    conversation = format_history(history, settings.conversation_max_turns)
    prompt = (
        f"Conversation:\n{conversation}\n\n"
        f"Follow-up question: {question}\n\nStandalone question:"
    )
    try:
        raw = await ollama_client.generate(
            settings.ollama_url, settings.generation_model, prompt, system=_CONDENSE_SYSTEM
        )
    except (httpx.HTTPError, ValueError):
        return question
    return raw.strip() or question
