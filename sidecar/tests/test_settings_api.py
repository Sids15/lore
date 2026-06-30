"""Tests for the settings API (GET/PATCH /settings) and the overrides store."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import settings_store
from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Point the overrides file at a temp data dir and start from a clean cache.
    monkeypatch.setattr(settings_store, "_overrides_path", lambda: tmp_path / "settings.json")
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_get_returns_current_values(client):
    body = client.get("/settings").json()
    # Defaults from Settings.
    assert body["mmr_enabled"] is True
    assert body["iterative_enabled"] is False
    assert body["mmr_lambda"] == pytest.approx(0.7)


def test_patch_updates_persists_and_applies_live(client, tmp_path):
    resp = client.patch("/settings", json={"iterative_enabled": True, "mmr_lambda": 0.4})
    assert resp.status_code == 200
    assert resp.json()["iterative_enabled"] is True
    assert resp.json()["mmr_lambda"] == pytest.approx(0.4)

    # Persisted to disk...
    assert settings_store.load_overrides() == {"iterative_enabled": True, "mmr_lambda": 0.4}
    # ...and applied live (cache cleared) — a fresh Settings reflects it.
    assert get_settings().iterative_enabled is True
    assert get_settings().mmr_lambda == pytest.approx(0.4)


def test_patch_merges_with_existing_overrides(client):
    client.patch("/settings", json={"iterative_enabled": True})
    client.patch("/settings", json={"mmr_enabled": False})
    merged = settings_store.load_overrides()
    assert merged == {"iterative_enabled": True, "mmr_enabled": False}


def test_patch_rejects_out_of_range(client):
    assert client.patch("/settings", json={"mmr_lambda": 2.0}).status_code == 422
    assert client.patch("/settings", json={"iterative_max_rounds": 1}).status_code == 422
    # Nothing persisted on rejection.
    assert settings_store.load_overrides() == {}


def test_invalid_persisted_value_is_dropped_not_fatal(client, tmp_path):
    # A corrupted/stale settings.json must never brick the sidecar: the bad key is
    # dropped, valid keys survive, and the UI can still read + repair settings.
    (tmp_path / "settings.json").write_text(
        '{"mmr_lambda": 5.0, "iterative_enabled": true}', encoding="utf-8"
    )
    get_settings.cache_clear()

    # GET still works (no 500); the bad mmr_lambda is ignored, the valid one applies.
    body = client.get("/settings").json()
    assert body["mmr_lambda"] == pytest.approx(0.7)  # default, bad override dropped
    assert body["iterative_enabled"] is True  # valid override kept

    # PATCH self-heals: it merges onto the sanitized set and rewrites a clean file.
    assert client.patch("/settings", json={"router_enabled": False}).status_code == 200
    assert settings_store.load_overrides() == {
        "iterative_enabled": True,
        "router_enabled": False,
    }


def test_load_overrides_gives_up_on_non_override_error(tmp_path, monkeypatch):
    # An invalid value coming from the env (not the overrides file) must not spin
    # _drop_invalid forever — it has no removable key, so it gives up and returns {}.
    monkeypatch.setattr(settings_store, "_overrides_path", lambda: tmp_path / "settings.json")
    monkeypatch.setenv("LORE_MMR_LAMBDA", "2.0")  # out of [0,1] -> validation fails
    (tmp_path / "settings.json").write_text('{"router_enabled": false}', encoding="utf-8")
    assert settings_store.load_overrides() == {}


def test_overrides_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "_overrides_path", lambda: tmp_path / "settings.json")
    assert settings_store.load_overrides() == {}  # missing file -> {}
    settings_store.save_overrides({"router_enabled": False})
    assert settings_store.load_overrides() == {"router_enabled": False}
    assert Settings(**settings_store.load_overrides()).router_enabled is False


def test_save_overrides_is_atomic_and_leaves_no_tmp(tmp_path, monkeypatch):
    # The atomic write (tmp + os.replace) must not leave a *.tmp sidecar behind.
    monkeypatch.setattr(settings_store, "_overrides_path", lambda: tmp_path / "settings.json")
    settings_store.save_overrides({"router_enabled": False})
    assert (tmp_path / "settings.json").exists()
    assert not (tmp_path / "settings.json.tmp").exists()


def test_merge_overrides_merges_persists_and_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "_overrides_path", lambda: tmp_path / "settings.json")
    settings_store.save_overrides({"iterative_enabled": True})
    merged = settings_store.merge_overrides({"mmr_enabled": False})
    assert merged == {"iterative_enabled": True, "mmr_enabled": False}
    assert settings_store.load_overrides() == {"iterative_enabled": True, "mmr_enabled": False}


def test_merge_overrides_invalid_raises_and_persists_nothing(tmp_path, monkeypatch):
    # An out-of-range merged value raises (the API maps it to 422) and writes nothing.
    monkeypatch.setattr(settings_store, "_overrides_path", lambda: tmp_path / "settings.json")
    with pytest.raises(ValidationError):
        settings_store.merge_overrides({"mmr_lambda": 5.0})
    assert not (tmp_path / "settings.json").exists()
