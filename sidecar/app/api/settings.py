"""Settings API: read and live-edit a curated subset of the retrieval/agent knobs.

Only quality/behaviour toggles are exposed — never ports, paths, URLs, model names,
or CORS. A PATCH validates against the real :class:`Settings` bounds, persists the
overrides to the data dir, and clears the settings cache so the change takes effect
on the next request (no restart).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.settings_store import load_overrides, save_overrides

router = APIRouter(tags=["settings"])


class SettingsView(BaseModel):
    """Current effective values of the UI-exposed settings."""

    rerank_enabled: bool
    mmr_enabled: bool
    mmr_lambda: float
    parent_expansion_enabled: bool
    query_expansion_enabled: bool
    query_expansion_n: int
    self_correct_enabled: bool
    iterative_enabled: bool
    iterative_max_rounds: int
    grounding_enabled: bool
    router_enabled: bool
    graphrag_enabled: bool
    conversation_enabled: bool
    retrieval_top_k: int


class SettingsPatch(BaseModel):
    """Partial update — only provided fields change. Bounds mirror Settings."""

    rerank_enabled: bool | None = None
    mmr_enabled: bool | None = None
    mmr_lambda: float | None = Field(default=None, ge=0.0, le=1.0)
    parent_expansion_enabled: bool | None = None
    query_expansion_enabled: bool | None = None
    query_expansion_n: int | None = Field(default=None, ge=1)
    self_correct_enabled: bool | None = None
    iterative_enabled: bool | None = None
    iterative_max_rounds: int | None = Field(default=None, ge=2, le=6)
    grounding_enabled: bool | None = None
    router_enabled: bool | None = None
    graphrag_enabled: bool | None = None
    conversation_enabled: bool | None = None
    retrieval_top_k: int | None = Field(default=None, ge=1)


# The knobs the UI may read/write — the single source of truth is SettingsView.
EXPOSED_FIELDS = tuple(SettingsView.model_fields)


def _view(settings: Settings) -> SettingsView:
    return SettingsView(**{name: getattr(settings, name) for name in EXPOSED_FIELDS})


@router.get("/settings", response_model=SettingsView)
def read_settings() -> SettingsView:
    """Return the current effective values of the UI-exposed settings."""
    return _view(get_settings())


@router.patch("/settings", response_model=SettingsView)
def update_settings(patch: SettingsPatch) -> SettingsView:
    """Merge the patch into the persisted overrides and apply it live.

    The patch is validated by ``SettingsPatch`` (bad values 422 before we get
    here); the merged result is validated again by constructing ``Settings`` so a
    cross-field issue can't be persisted. On success the cache is cleared so the
    next request rebuilds with the new values.
    """
    changes = patch.model_dump(exclude_none=True)
    merged = {**load_overrides(), **changes}
    # Re-validate the whole override set so a cross-field issue can't be persisted.
    try:
        Settings(**merged)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    save_overrides(merged)
    get_settings.cache_clear()
    return _view(get_settings())
