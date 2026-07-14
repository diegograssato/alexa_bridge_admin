from __future__ import annotations

import sys
from pathlib import Path

import yaml

APP_ROOT = Path(__file__).resolve().parents[2] / "alexa_bridge_admin" / "rootfs" / "app"
sys.path.insert(0, str(APP_ROOT))

from services.config_service import ConfigService  # noqa: E402


def test_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    data = service.load()

    assert data["mqtt"]["input_topic"] == "alexa/command"
    assert "devices" in data


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    payload = {
        "mqtt": {
            "input_topic": "a/in",
            "output_topic": "a/out",
            "ack_topic": "a/ack",
            "dlq_topic": "a/dlq",
        },
        "commands": {
            "off_keywords": ["desliga"],
        },
        "devices": {
            "sala": {
                "media_player.echo": {
                    "aliases": ["echo"]
                }
            }
        },
    }

    service.save(payload)
    loaded = service.load()

    assert loaded["mqtt"]["input_topic"] == "a/in"
    assert loaded["devices"]["sala"]["media_player.echo"]["aliases"] == ["echo"]


def test_save_raw_validates_root_object(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    service.save_raw("mqtt:\n  input_topic: test")
    data = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))

    assert data["mqtt"]["input_topic"] == "test"


def test_devices_crud_and_pagination(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    created = service.create_device("sala", "media_player.echo", ["echo", "alexa"])
    assert created["room"] == "sala"
    assert created["entity_id"] == "media_player.echo"
    assert created["aliases"] == ["echo", "alexa"]

    updated = service.update_device(created["key"], "quarto", "media_player.echo_quarto", ["echo_quarto"])
    assert updated["room"] == "quarto"
    assert updated["entity_id"] == "media_player.echo_quarto"

    service.create_device("quarto", "media_player.fire", ["fire"])
    page_1 = service.list_devices(page=1, page_size=1)
    assert page_1["pagination"]["total"] == 2
    assert len(page_1["items"]) == 1

    filtered = service.list_devices(page=1, page_size=10, query="fire")
    assert filtered["pagination"]["total"] == 1
    assert filtered["items"][0]["entity_id"] == "media_player.fire"

    service.delete_device(updated["key"])
    remaining = service.list_devices(page=1, page_size=10)
    assert remaining["pagination"]["total"] == 1


def test_ensure_bridge_script_copies_when_missing(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    source = tmp_path / "template_alexa_bridge.py"
    source.write_text("print('bridge')\n", encoding="utf-8")
    target = tmp_path / "pyscript" / "alexa_bridge.py"

    result = service.ensure_bridge_script(str(target), str(source))

    assert result["ok"] is True
    assert result["copied"] is True
    assert result["detail"] == "script_copied"
    assert target.read_text(encoding="utf-8") == "print('bridge')\n"


def test_ensure_bridge_script_does_not_overwrite_existing(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    source = tmp_path / "template_alexa_bridge.py"
    source.write_text("print('new')\n", encoding="utf-8")
    target = tmp_path / "pyscript" / "alexa_bridge.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('existing')\n", encoding="utf-8")

    result = service.ensure_bridge_script(str(target), str(source))

    assert result["ok"] is True
    assert result["copied"] is False
    assert result["detail"] == "script_exists"
    assert target.read_text(encoding="utf-8") == "print('existing')\n"


def test_validate_raw_yaml_schema_ok(tmp_path: Path) -> None:
        cfg_file = tmp_path / "alexa_bridge.yaml"
        service = ConfigService(str(cfg_file))

        raw = """
mqtt:
    input_topic: alexa/in
    output_topic: alexa/out
    ack_topic: alexa/ack
    dlq_topic: alexa/dlq
commands:
    off_keywords:
        - desliga
devices:
    sala:
        media_player.echo:
            aliases:
                - media_player.echo
"""

        result = service.validate_raw_yaml_schema(raw)
        assert result["ok"] is True
        assert result["errors"] == []


def test_validate_raw_yaml_schema_invalid(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    raw = """
mqtt:
    input_topic: ""
commands:
    off_keywords: desliga
devices:
    sala: []
"""

    result = service.validate_raw_yaml_schema(raw)
    assert result["ok"] is False
    assert len(result["errors"]) >= 2


def test_ensure_bridge_yaml_copies_template_when_missing(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    source = tmp_path / "template_alexa_bridge.yaml"
    source.write_text("mqtt:\n  input_topic: test\n", encoding="utf-8")
    target = tmp_path / "pyscript" / "alexa_bridge.yaml"

    result = service.ensure_bridge_yaml(str(target), str(source))

    assert result["ok"] is True
    assert result["copied"] is True
    assert result["detail"] == "yaml_copied"
    assert "input_topic: test" in target.read_text(encoding="utf-8")


def test_ensure_bridge_yaml_generates_defaults_when_template_missing(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    target = tmp_path / "pyscript" / "alexa_bridge.yaml"
    missing_template = tmp_path / "missing_template.yaml"

    result = service.ensure_bridge_yaml(str(target), str(missing_template))

    assert result["ok"] is True
    assert result["copied"] is True
    assert result["detail"] == "yaml_generated_from_defaults"
    content = target.read_text(encoding="utf-8")
    assert "mqtt:" in content
    assert "devices:" in content
