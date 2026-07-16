from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "alexa_bridge_admin" / "rootfs" / "app"
sys.path.insert(0, str(APP_ROOT))

from services.reload_service import ReloadService  # noqa: E402


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def test_reload_pyscript_runtime_dev_mode(monkeypatch) -> None:
    monkeypatch.setenv("DEV_MODE", "true")
    svc = ReloadService()
    ret = svc.reload_pyscript_runtime()
    assert ret["ok"] is True
    assert "[DEV]" in ret["detail"]


def test_reload_pyscript_runtime_without_token(monkeypatch) -> None:
    monkeypatch.delenv("DEV_MODE", raising=False)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    svc = ReloadService()
    ret = svc.reload_pyscript_runtime()
    assert ret["ok"] is False
    assert "SUPERVISOR_TOKEN" in ret["detail"]


def test_reload_pyscript_runtime_success(monkeypatch) -> None:
    monkeypatch.delenv("DEV_MODE", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")

    called = {"url": ""}

    def _post(url, headers=None, json=None, timeout=None):
        called["url"] = url
        return _Resp(200, "ok")

    monkeypatch.setattr("services.reload_service.requests.post", _post)
    svc = ReloadService()
    ret = svc.reload_pyscript_runtime()
    assert ret["ok"] is True
    assert called["url"].endswith("/core/api/services/pyscript/reload")


def test_reload_pyscript_runtime_failure(monkeypatch) -> None:
    monkeypatch.delenv("DEV_MODE", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")

    def _post(url, headers=None, json=None, timeout=None):
        return _Resp(500, "boom")

    monkeypatch.setattr("services.reload_service.requests.post", _post)
    svc = ReloadService()
    ret = svc.reload_pyscript_runtime()
    assert ret["ok"] is False
    assert "HTTP 500" in ret["detail"]


def test_reload_pyscript_service_fallback_success(monkeypatch) -> None:
    monkeypatch.delenv("DEV_MODE", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")

    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if url.endswith("/pyscript/alexa_bridge_reload"):
            return _Resp(404, "not found")
        return _Resp(200, "ok")

    monkeypatch.setattr("services.reload_service.requests.post", _post)
    svc = ReloadService()
    ret = svc.reload_pyscript()
    assert ret["ok"] is True
    assert any(url.endswith("/pyscript/alexa_wrapper_reload") for url in calls)


def test_reload_pyscript_service_failure(monkeypatch) -> None:
    monkeypatch.delenv("DEV_MODE", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")

    def _post(url, headers=None, json=None, timeout=None):
        return _Resp(500, "error")

    monkeypatch.setattr("services.reload_service.requests.post", _post)
    svc = ReloadService()
    ret = svc.reload_pyscript()
    assert ret["ok"] is False
    assert "HTTP 500" in ret["detail"]
