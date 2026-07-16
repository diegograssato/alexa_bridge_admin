from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

APP_ROOT = Path(__file__).resolve().parents[2] / "alexa_bridge_admin" / "rootfs"
sys.path.insert(0, str(APP_ROOT))

from app.api.routes import backup as backup_route  # noqa: E402
from app.api.routes import config as config_route  # noqa: E402
from app.api.routes import devices as devices_route  # noqa: E402
from app.api.routes import reload as reload_route  # noqa: E402


def _client_for(router) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_config_put_triggers_auto_reload_on_webhook_change(monkeypatch):
    class FakeConfigService:
        def __init__(self):
            self.audit = []

        def load(self):
            return {"webhook": {"id": "old"}}

        def webhook_ids_changed(self, before, after):
            return True

        def save(self, payload):
            return None

        def append_audit(self, action, detail="", **kwargs):
            self.audit.append((action, detail))

        def load_raw(self):
            return "yaml: ok\n"

        def validate_raw_yaml_schema(self, raw):
            return {"ok": True, "errors": []}

        def save_raw(self, raw):
            return None

    class FakeReloadService:
        def reload_pyscript_runtime(self):
            return {"ok": True, "detail": "pyscript.reload executado"}

    fake_service = FakeConfigService()
    monkeypatch.setattr(config_route, "service", fake_service)
    monkeypatch.setattr(config_route, "reload_service", FakeReloadService())

    client = _client_for(config_route.router)
    resp = client.get("/api/config")
    assert resp.status_code == 200

    resp = client.put("/api/config", json={"webhook": {"id": "new"}, "transport": {"mqtt_enabled": True, "webhook_enabled": True}, "mqtt": {"input_topic": "alexa/command"}, "integration": {"mqtt": {"type": "event_bus", "event_bus": {"event_name": "alexa_bridge.command.mqtt"}}, "webhook": {"type": "event_bus", "event_bus": {"event_name": "alexa_bridge.command.webhook"}}}, "security": {"enabled": False, "secret": "", "encrypt_payload": False}, "commands": {"off_keywords": ["desliga"]}, "devices": {}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_pyscript_reload"] is True
    assert body["pyscript_reload_ok"] is True

    yaml_resp = client.get("/api/config/yaml")
    assert yaml_resp.status_code == 200

    validate_resp = client.post("/api/config/yaml/validate", json={"yaml": "x: 1\n"})
    assert validate_resp.status_code == 200
    assert validate_resp.json()["ok"] is True


def test_config_put_yaml_auto_reload_failure(monkeypatch):
    class FakeConfigService:
        def __init__(self):
            self.audit = []

        def load(self):
            return {"webhook": {"id": "old"}}

        def save_raw(self, raw):
            return None

        def webhook_ids_changed(self, before, after):
            return True

        def append_audit(self, action, detail="", **kwargs):
            self.audit.append((action, detail))

        def validate_raw_yaml_schema(self, raw):
            return {"ok": False, "errors": ["invalid"]}

        def load_raw(self):
            return "x: 1\n"

        def save(self, payload):
            raise ValueError("invalid_payload")

    class FakeReloadService:
        def reload_pyscript_runtime(self):
            return {"ok": False, "detail": "HTTP 500"}

    fake_service = FakeConfigService()
    monkeypatch.setattr(config_route, "service", fake_service)
    monkeypatch.setattr(config_route, "reload_service", FakeReloadService())

    client = _client_for(config_route.router)
    bad_config = client.put("/api/config", json={"bad": True})
    assert bad_config.status_code == 400

    validate_bad = client.post("/api/config/yaml/validate", json={"yaml": "bad: true\n"})
    assert validate_bad.status_code == 200
    assert validate_bad.json()["ok"] is False

    resp = client.put("/api/config/yaml", json={"yaml": "x: 1\n"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_pyscript_restart"] is True
    assert body["pyscript_reload_ok"] is False


def test_reload_route_audits_success_and_failure(monkeypatch):
    class FakeReloadService:
        def __init__(self, ok):
            self.ok = ok

        def reload_pyscript(self):
            if self.ok:
                return {"ok": True, "detail": "ok"}
            return {"ok": False, "detail": "fail"}

    class FakeConfigService:
        def __init__(self):
            self.audit = []

        def append_audit(self, action, detail="", **kwargs):
            self.audit.append((action, detail))

        def get_last_event(self):
            return {"agent": "Jarvis"}

    fake_cfg = FakeConfigService()
    monkeypatch.setattr(reload_route, "service", FakeReloadService(ok=True))
    monkeypatch.setattr(reload_route, "config_service", fake_cfg)

    client = _client_for(reload_route.router)
    resp = client.post("/api/reload")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    monkeypatch.setattr(reload_route, "service", FakeReloadService(ok=False))
    resp2 = client.post("/api/reload")
    assert resp2.status_code == 200
    assert resp2.json()["ok"] is False

    last = client.get("/api/bridge/last-event")
    assert last.status_code == 200
    assert last.json()["agent"] == "Jarvis"


def test_devices_routes_create_and_conflict(monkeypatch):
    class FakeService:
        def __init__(self):
            self.audit = []

        def list_devices(self, page, page_size, query):
            return {"items": [], "pagination": {"total": 0}}

        def export_devices_yaml(self):
            return "devices: {}\n"

        def import_devices_yaml(self, raw):
            return {"rooms": 1, "devices": 1}

        def get_device(self, key):
            return {"key": key, "entity_id": "media_player.echo"}

        def create_device(self, room, entity_id, aliases):
            if entity_id == "dup":
                raise ValueError("device_already_exists")
            return {"room": room, "entity_id": entity_id, "aliases": aliases}

        def update_device(self, key, room, entity_id, aliases):
            return {"key": key, "room": room, "entity_id": entity_id, "aliases": aliases}

        def delete_device(self, key):
            return None

        def append_audit(self, action, detail="", entity_id="-", **kwargs):
            self.audit.append((action, detail, entity_id))

    monkeypatch.setattr(devices_route, "service", FakeService())
    client = _client_for(devices_route.router)

    list_resp = client.get("/api/devices?page=1&page_size=10&query=")
    assert list_resp.status_code == 200

    yaml_export = client.get("/api/devices/yaml")
    assert yaml_export.status_code == 200

    import_resp = client.post("/api/devices/import", json={"yaml": "devices: {}\n"})
    assert import_resp.status_code == 200

    get_resp = client.get("/api/devices/media_player.echo")
    assert get_resp.status_code == 200

    ok = client.post("/api/devices", json={"room": "sala", "entity_id": "media_player.echo", "aliases": ["echo"]})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True

    dup = client.post("/api/devices", json={"room": "sala", "entity_id": "dup", "aliases": []})
    assert dup.status_code == 409

    upd = client.put("/api/devices/media_player.echo", json={"room": "sala", "entity_id": "media_player.echo", "aliases": ["echo", "sala"]})
    assert upd.status_code == 200

    delete_ok = client.delete("/api/devices/media_player.echo")
    assert delete_ok.status_code == 200


def test_backup_routes_create_download_delete_and_errors(monkeypatch):
    class FakeService:
        def __init__(self):
            self.audit = []

        def list_backups(self):
            return [{"filename": "b1.yaml"}]

        def create_backup(self):
            return {"filename": "b1.yaml"}

        def read_backup(self, filename):
            if filename == "missing.yaml":
                raise FileNotFoundError(filename)
            return "mqtt:\n  input_topic: alexa/command\n"

        def restore_backup(self, filename):
            if filename == "bad.yaml":
                raise ValueError("bad")
            return {"ok": True, "detail": "restored"}

        def save_raw(self, raw):
            if "invalid" in raw:
                raise ValueError("invalid")
            return None

        def delete_backup(self, filename):
            if filename == "missing.yaml":
                raise FileNotFoundError(filename)
            return None

        def append_audit(self, action, detail="", **kwargs):
            self.audit.append((action, detail))

    monkeypatch.setattr(backup_route, "service", FakeService())
    client = _client_for(backup_route.router)

    lst = client.get("/api/backups")
    assert lst.status_code == 200
    assert len(lst.json()["items"]) == 1

    crt = client.post("/api/backups")
    assert crt.status_code == 200

    dwn = client.get("/api/backups/b1.yaml/download")
    assert dwn.status_code == 200

    rst_bad = client.post("/api/backups/restore", json={"filename": "bad.yaml"})
    assert rst_bad.status_code == 400

    rst_yaml_bad = client.post("/api/backups/restore-yaml", json={"yaml": "invalid: true"})
    assert rst_yaml_bad.status_code == 400

    delete_missing = client.delete("/api/backups/missing.yaml")
    assert delete_missing.status_code == 404


def test_devices_and_backup_error_branches(monkeypatch):
    class FakeDevicesErrorService:
        def list_devices(self, page, page_size, query):
            return {"items": [], "pagination": {"total": 0}}

        def export_devices_yaml(self):
            return "devices: {}\n"

        def import_devices_yaml(self, raw):
            raise ValueError("yaml_invalido")

        def get_device(self, key):
            raise KeyError(key)

        def create_device(self, room, entity_id, aliases):
            raise ValueError("payload_invalid")

        def update_device(self, key, room, entity_id, aliases):
            raise KeyError(key)

        def delete_device(self, key):
            raise KeyError(key)

        def append_audit(self, action, detail="", entity_id="-", **kwargs):
            return None

    class FakeBackupErrorService:
        def list_backups(self):
            return []

        def create_backup(self):
            raise ValueError("invalid_backup")

        def read_backup(self, filename):
            raise ValueError("invalid_name")

        def restore_backup(self, filename):
            raise FileNotFoundError(filename)

        def save_raw(self, raw):
            return None

        def delete_backup(self, filename):
            raise ValueError("invalid_name")

        def append_audit(self, action, detail="", **kwargs):
            return None

    monkeypatch.setattr(devices_route, "service", FakeDevicesErrorService())
    dev_client = _client_for(devices_route.router)

    assert dev_client.post("/api/devices/import", json={"yaml": "broken"}).status_code == 400
    assert dev_client.get("/api/devices/unknown").status_code == 404
    assert dev_client.post("/api/devices", json={"room": "sala", "entity_id": "x", "aliases": []}).status_code == 400
    assert dev_client.put("/api/devices/unknown", json={"room": "sala", "entity_id": "x", "aliases": []}).status_code == 404
    assert dev_client.delete("/api/devices/unknown").status_code == 404

    monkeypatch.setattr(backup_route, "service", FakeBackupErrorService())
    bkp_client = _client_for(backup_route.router)

    assert bkp_client.post("/api/backups").status_code == 400
    assert bkp_client.get("/api/backups/bad.yaml/download").status_code == 400
    assert bkp_client.post("/api/backups/restore", json={"filename": "x.yaml"}).status_code == 404
    assert bkp_client.delete("/api/backups/bad.yaml").status_code == 400
