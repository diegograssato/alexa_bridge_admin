from __future__ import annotations

import json
from datetime import datetime, timedelta
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


def test_validate_raw_yaml_schema_invalid_encrypt_payload_type(tmp_path: Path) -> None:
        cfg_file = tmp_path / "alexa_bridge.yaml"
        service = ConfigService(str(cfg_file))

        raw = """
mqtt:
    input_topic: alexa/in
    output_topic: alexa/out
    ack_topic: alexa/ack
    dlq_topic: alexa/dlq
commands:
    off_keywords: [desliga]
devices: {}
security:
    enabled: true
    secret: abc
    encrypt_payload: "yes"
"""

        result = service.validate_raw_yaml_schema(raw)
        assert result["ok"] is False
        assert "security.encrypt_payload deve ser booleano" in result["errors"]


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


def test_create_backup_prunes_files_older_than_30_days(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    cfg_file.write_text("mqtt:\n  input_topic: alexa/command\n", encoding="utf-8")
    service = ConfigService(str(cfg_file))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    old_1 = backups_dir / "alexa_bridge_backup_old_1.yaml"
    old_2 = backups_dir / "alexa_bridge_backup_old_2.yaml"
    old_1.write_text("old1\n", encoding="utf-8")
    old_2.write_text("old2\n", encoding="utf-8")

    old_ts = (datetime.now() - timedelta(days=40)).timestamp()
    old_1.touch()
    old_2.touch()
    import os
    os.utime(old_1, (old_ts, old_ts))
    os.utime(old_2, (old_ts, old_ts))

    created = service.create_backup()
    files_after = sorted([f.name for f in backups_dir.glob("*.yaml")])

    assert created["filename"] in files_after
    assert "alexa_bridge_backup_old_1.yaml" not in files_after
    assert "alexa_bridge_backup_old_2.yaml" not in files_after
    assert len(files_after) >= 1


def test_backup_prune_never_deletes_last_file(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    cfg_file.write_text("mqtt:\n  input_topic: alexa/command\n", encoding="utf-8")
    service = ConfigService(str(cfg_file))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    only_file = backups_dir / "alexa_bridge_backup_only.yaml"
    only_file.write_text("only\n", encoding="utf-8")

    old_ts = (datetime.now() - timedelta(days=60)).timestamp()
    import os
    os.utime(only_file, (old_ts, old_ts))

    service._prune_old_backups()
    assert only_file.exists()


def test_audit_prune_keeps_latest_per_action_even_if_older_than_30_days(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    service = ConfigService(str(cfg_file))

    audit_file = tmp_path / "alexa_bridge_audit.jsonl"
    old_40 = (datetime.now() - timedelta(days=40)).isoformat()
    old_35 = (datetime.now() - timedelta(days=35)).isoformat()

    seed_rows = [
        {"created_at": old_40, "action": "UPDATE_CONFIG", "entity_id": "-", "user": "system", "detail": "old"},
        {"created_at": old_40, "action": "RELOAD", "entity_id": "-", "user": "system", "detail": "very old"},
        {"created_at": old_35, "action": "RELOAD", "entity_id": "-", "user": "system", "detail": "less old"},
    ]
    with audit_file.open("w", encoding="utf-8") as f:
        for row in seed_rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")

    service.append_audit(action="BACKUP", detail="new backup")

    rows_after = service.list_audits(limit=500)
    actions = [str(x.get("action")) for x in rows_after]

    assert "BACKUP" in actions
    assert "UPDATE_CONFIG" in actions
    assert "RELOAD" in actions

    # Para RELOAD antigo, mantém apenas o mais recente desse tipo.
    reload_rows = [r for r in rows_after if r.get("action") == "RELOAD"]
    assert len(reload_rows) == 1
    assert reload_rows[0].get("detail") == "less old"


def test_create_backup_limits_to_10_per_day(tmp_path: Path) -> None:
    cfg_file = tmp_path / "alexa_bridge.yaml"
    cfg_file.write_text("mqtt:\n  input_topic: alexa/command\n", encoding="utf-8")
    service = ConfigService(str(cfg_file))

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    for idx in range(10):
        f = backups_dir / f"alexa_bridge_backup_seed_{idx}.yaml"
        f.write_text(f"seed {idx}\n", encoding="utf-8")

    try:
        service.create_backup()
        assert False, "Era esperado erro de limite diário"
    except ValueError as ex:
        assert "máximo de 10 backups por dia" in str(ex)
