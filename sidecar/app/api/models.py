"""Model management API: pull an Ollama model from inside the app.

Proxies Ollama's streaming ``/api/pull`` so the desktop UI can install the
required models (and show download progress) without dropping to a terminal.
Model *status* (installed / missing) is already reported by ``/health``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import get_settings
from app.llm import ollama_client

router = APIRouter(tags=["models"])


class PullRequest(BaseModel):
    """Request body for pulling a model."""

    model: str


@router.post("/models/pull")
async def pull_model(request: PullRequest) -> StreamingResponse:
    """Pull an Ollama model, streaming progress as newline-delimited JSON.

    Events: ``progress`` (``status`` + ``completed``/``total``), a terminal
    ``done``, or ``error`` if the Ollama service fails mid-pull.
    """
    model = request.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="Model name must not be empty")
    settings = get_settings()

    async def ndjson() -> AsyncIterator[str]:
        try:
            async for record in ollama_client.pull_model(settings.ollama_url, model):
                event = {
                    "type": "progress",
                    "status": record.get("status", ""),
                    "completed": record.get("completed"),
                    "total": record.get("total"),
                }
                yield json.dumps(event) + "\n"
                if record.get("status") == "success":
                    break
            yield json.dumps({"type": "done"}) + "\n"
        except httpx.HTTPError as error:
            payload = {"type": "error", "detail": f"Model pull failed: {error}"}
            yield json.dumps(payload) + "\n"

    return StreamingResponse(ndjson(), media_type="application/x-ndjson")
