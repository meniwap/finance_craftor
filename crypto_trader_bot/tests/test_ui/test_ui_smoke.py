from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _repo_root() -> Path:
    # tests/test_ui/test_ui_smoke.py -> crypto_trader_bot/
    return Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Ensure sqlite files are created in temp dir (ui_server uses relative "data/*.sqlite3")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UI_TOKEN", "test-token")
    monkeypatch.setenv("UI_MODE", "paper_only")
    monkeypatch.setenv("UI_REQUIRE_LIVE_CONFIRM", "true")

    # Reload module to pick up env + cwd
    sys.modules.pop("src.app.ui_server", None)
    ui_server = importlib.import_module("src.app.ui_server")
    importlib.reload(ui_server)
    return TestClient(ui_server.app)


def test_ui_meta(client: TestClient) -> None:
    r = client.get("/ui_meta")
    assert r.status_code == 200
    data = r.json()
    assert "ui_mode" in data
    assert "token_required" in data
    assert "require_live_confirm" in data


def test_registry_smoke(client: TestClient) -> None:
    r = client.get("/registry/indicators")
    assert r.status_code == 200
    assert isinstance(r.json().get("items"), list)

    r2 = client.get("/registry/sizing")
    assert r2.status_code == 200
    assert isinstance(r2.json().get("items"), list)


def test_create_session_requires_token(client: TestClient) -> None:
    cfg_path = str((_repo_root() / "configs" / "live_scanner_top40_5m_5rounds_1usd_20c.yaml").resolve())

    # Missing token -> 401
    r = client.post("/sessions/from_ui", json={"base_config_path": cfg_path, "overrides": {}})
    assert r.status_code == 401

    # With token -> OK
    r2 = client.post(
        "/sessions/from_ui",
        headers={"X-UI-TOKEN": "test-token"},
        json={"base_config_path": cfg_path, "overrides": {}},
    )
    assert r2.status_code == 200
    data = r2.json()
    assert "session_id" in data

    r3 = client.get("/sessions")
    assert r3.status_code == 200
    items = r3.json().get("items")
    assert isinstance(items, list)
    assert len(items) >= 1

