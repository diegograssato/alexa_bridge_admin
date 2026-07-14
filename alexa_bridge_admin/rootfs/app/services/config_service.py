from __future__ import annotations

import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


class ConfigService:
    def __init__(self, config_path: str | None = None) -> None:
        path = config_path or os.getenv("ALEXA_BRIDGE_CONFIG_PATH", "/homeassistant/pyscript/alexa_bridge.yaml")
        self.config_path = Path(path)

    def defaults(self) -> dict[str, Any]:
        return {
            "mqtt": {
                "input_topic": "alexa/command",
                "output_topic": "homeassistant/voice/command",
                "ack_topic": "homeassistant/voice/ack",
                "dlq_topic": "homeassistant/voice/dlq",
            },
            "commands": {
                "off_keywords": ["desliga", "desligar", "turn off"],
            },
            "devices": {},
        }

    def load(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return self.defaults()

        with self.config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if not isinstance(data, dict):
            return self.defaults()

        merged = self.defaults()
        for key, value in data.items():
            merged[key] = value
        return merged

    def load_raw(self) -> str:
        if not self.config_path.exists():
            return yaml.safe_dump(self.defaults(), sort_keys=False, allow_unicode=True)
        return self.config_path.read_text(encoding="utf-8")

    def save(self, data: dict[str, Any]) -> None:
        self._ensure_parent_dir()
        backup = self._backup_path()
        if self.config_path.exists():
            shutil.copy2(self.config_path, backup)

        raw = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        self._atomic_write(raw)

    def save_raw(self, raw_yaml: str) -> None:
        parsed = yaml.safe_load(raw_yaml) or {}
        if not isinstance(parsed, dict):
            raise ValueError("YAML precisa ser um objeto no nivel raiz")
        self.save(parsed)

    def validate_raw_yaml_schema(self, raw_yaml: str) -> dict[str, Any]:
        errors: list[str] = []
        try:
            parsed = yaml.safe_load(raw_yaml) or {}
        except yaml.YAMLError as ex:
            return {
                "ok": False,
                "errors": [f"YAML invalido: {ex}"],
            }

        if not isinstance(parsed, dict):
            return {
                "ok": False,
                "errors": ["Raiz do YAML deve ser um objeto"],
            }

        mqtt = parsed.get("mqtt")
        if not isinstance(mqtt, dict):
            errors.append("Campo mqtt deve ser um objeto")
        else:
            for key in ["input_topic", "output_topic", "ack_topic", "dlq_topic"]:
                value = mqtt.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"mqtt.{key} deve ser string nao vazia")

        commands = parsed.get("commands")
        if not isinstance(commands, dict):
            errors.append("Campo commands deve ser um objeto")
        else:
            off_keywords = commands.get("off_keywords")
            if not isinstance(off_keywords, list) or not all(isinstance(x, str) for x in off_keywords):
                errors.append("commands.off_keywords deve ser lista de strings")

        devices = parsed.get("devices", {})
        if not isinstance(devices, dict):
            errors.append("Campo devices deve ser um objeto")
        else:
            for room, entities in devices.items():
                if not isinstance(room, str) or not room.strip():
                    errors.append("Nome de room invalido em devices")
                    continue
                if not isinstance(entities, dict):
                    errors.append(f"devices.{room} deve ser um objeto")
                    continue
                for entity_id, cfg in entities.items():
                    if not isinstance(entity_id, str) or not entity_id.strip():
                        errors.append(f"Entity ID invalido em devices.{room}")
                        continue
                    if not isinstance(cfg, dict):
                        errors.append(f"devices.{room}.{entity_id} deve ser um objeto")
                        continue
                    aliases = cfg.get("aliases", [])
                    if isinstance(aliases, str):
                        continue
                    if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
                        errors.append(f"devices.{room}.{entity_id}.aliases deve ser lista de strings")

        return {
            "ok": len(errors) == 0,
            "errors": errors,
        }

    def export_devices_yaml(self) -> str:
        config = self.load()
        devices = config.get("devices", {})
        if not isinstance(devices, dict):
            devices = {}
        return yaml.safe_dump({"devices": devices}, sort_keys=False, allow_unicode=True)

    def import_devices_yaml(self, raw_yaml: str) -> dict[str, int]:
        parsed = yaml.safe_load(raw_yaml) or {}
        if not isinstance(parsed, dict):
            raise ValueError("YAML invalido para importacao")

        if "devices" in parsed:
            devices = parsed.get("devices")
        else:
            devices = parsed

        if not isinstance(devices, dict):
            raise ValueError("Campo devices deve ser um objeto")

        clean_devices: dict[str, dict[str, dict[str, list[str]]]] = {}
        total = 0
        for room, entities in devices.items():
            if not isinstance(room, str) or not isinstance(entities, dict):
                continue
            room_items: dict[str, dict[str, list[str]]] = {}
            for entity_id, cfg in entities.items():
                if not isinstance(entity_id, str):
                    continue
                aliases: list[str] = []
                if isinstance(cfg, dict):
                    raw_aliases = cfg.get("aliases", [])
                    if isinstance(raw_aliases, list):
                        aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]
                    elif isinstance(raw_aliases, str) and raw_aliases.strip():
                        aliases = [raw_aliases.strip()]
                room_items[entity_id] = {"aliases": aliases}
                total += 1
            if room_items:
                clean_devices[room] = room_items

        config = self.load()
        config["devices"] = clean_devices
        self.save(config)
        return {
            "rooms": len(clean_devices),
            "devices": total,
        }

    def create_backup(self) -> dict[str, Any]:
        config = self.load()
        if not self.config_path.exists():
            self.save(config)

        backups_dir = self._backups_dir()
        backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"alexa_bridge_backup_{timestamp}.yaml"
        target = backups_dir / filename
        shutil.copy2(self.config_path, target)
        return self._backup_meta(target)

    def list_backups(self) -> list[dict[str, Any]]:
        backups_dir = self._backups_dir()
        if not backups_dir.exists():
            return []

        items: list[dict[str, Any]] = []
        for file in backups_dir.glob("*.yaml"):
            if file.is_file():
                items.append(self._backup_meta(file))
        items.sort(key=lambda x: x["updated_at"], reverse=True)
        return items

    def read_backup(self, filename: str) -> str:
        file = self._backup_file(filename)
        return file.read_text(encoding="utf-8")

    def restore_backup(self, filename: str) -> dict[str, Any]:
        raw = self.read_backup(filename)
        self.save_raw(raw)
        return {
            "ok": True,
            "detail": "Backup restaurado",
            "filename": filename,
        }

    def delete_backup(self, filename: str) -> None:
        file = self._backup_file(filename)
        file.unlink()

    def ensure_bridge_script(self, script_target_path: str | None = None, template_path: str | None = None) -> dict[str, Any]:
        target = Path(script_target_path or os.getenv("ALEXA_BRIDGE_SCRIPT_PATH", "/homeassistant/pyscript/alexa_bridge.py"))
        source = Path(template_path or os.getenv("ALEXA_BRIDGE_SCRIPT_TEMPLATE", "/app/assets/alexa_bridge.py"))

        if target.exists():
            return {
                "ok": True,
                "copied": False,
                "detail": "script_exists",
                "target": str(target),
            }

        if not source.exists():
            return {
                "ok": False,
                "copied": False,
                "detail": "template_not_found",
                "target": str(target),
                "source": str(source),
            }

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return {
            "ok": True,
            "copied": True,
            "detail": "script_copied",
            "target": str(target),
            "source": str(source),
        }

    def ensure_bridge_yaml(self, yaml_target_path: str | None = None, template_path: str | None = None) -> dict[str, Any]:
        target = Path(yaml_target_path or os.getenv("ALEXA_BRIDGE_CONFIG_PATH", "/homeassistant/pyscript/alexa_bridge.yaml"))
        source = Path(template_path or os.getenv("ALEXA_BRIDGE_YAML_TEMPLATE", "/app/assets/alexa_bridge.yaml"))

        if target.exists():
            return {
                "ok": True,
                "copied": False,
                "detail": "yaml_exists",
                "target": str(target),
            }

        target.parent.mkdir(parents=True, exist_ok=True)

        if source.exists():
            shutil.copy2(source, target)
            return {
                "ok": True,
                "copied": True,
                "detail": "yaml_copied",
                "target": str(target),
                "source": str(source),
            }

        target.write_text(yaml.safe_dump(self.defaults(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        return {
            "ok": True,
            "copied": True,
            "detail": "yaml_generated_from_defaults",
            "target": str(target),
        }

    def append_audit(self, action: str, entity_id: str = "-", detail: str = "", user: str = "system") -> None:
        entry = {
            "created_at": datetime.now().isoformat(),
            "action": action,
            "entity_id": entity_id,
            "user": user,
            "detail": detail,
        }

        file = self._audit_file()
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def list_audits(self, limit: int = 50) -> list[dict[str, Any]]:
        file = self._audit_file()
        if not file.exists() or not file.is_file():
            return []

        rows: list[dict[str, Any]] = []
        with file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        rows.append(item)
                except json.JSONDecodeError:
                    continue

        rows.reverse()
        return rows[: max(1, min(limit, 500))]

    def list_devices(self, page: int = 1, page_size: int = 10, query: str = "") -> dict[str, Any]:
        config = self.load()
        devices = self._flatten_devices(config.get("devices", {}))

        q = query.strip().lower()
        if q:
            devices = [
                item for item in devices
                if q in item["room"].lower()
                or q in item["entity_id"].lower()
                or any(q in alias.lower() for alias in item["aliases"])
            ]

        devices.sort(key=lambda x: (x["room"], x["entity_id"]))

        total = len(devices)
        page = max(page, 1)
        page_size = max(min(page_size, 100), 1)
        start = (page - 1) * page_size
        end = start + page_size
        items = devices[start:end]

        return {
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
        }

    def get_device(self, device_key: str) -> dict[str, Any]:
        room, entity_id = self._split_device_key(device_key)
        config = self.load()
        devices = config.get("devices", {})

        room_data = devices.get(room)
        if not isinstance(room_data, dict) or entity_id not in room_data:
            raise KeyError("device_not_found")

        entry = room_data.get(entity_id)
        aliases: list[str] = []
        if isinstance(entry, dict):
            raw_aliases = entry.get("aliases", [])
            if isinstance(raw_aliases, list):
                aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]
            elif isinstance(raw_aliases, str) and raw_aliases.strip():
                aliases = [raw_aliases.strip()]

        return {
            "key": self._build_device_key(room, entity_id),
            "room": room,
            "entity_id": entity_id,
            "aliases": aliases,
        }

    def create_device(self, room: str, entity_id: str, aliases: list[str]) -> dict[str, Any]:
        room = room.strip()
        entity_id = entity_id.strip()
        aliases = [alias.strip() for alias in aliases if alias.strip()]

        if not room or not entity_id:
            raise ValueError("room_and_entity_required")

        config = self.load()
        devices = config.setdefault("devices", {})
        room_data = devices.setdefault(room, {})
        if not isinstance(room_data, dict):
            room_data = {}
            devices[room] = room_data

        if entity_id in room_data:
            raise ValueError("device_already_exists")

        room_data[entity_id] = {"aliases": aliases}
        self.save(config)
        return self.get_device(self._build_device_key(room, entity_id))

    def update_device(self, device_key: str, room: str, entity_id: str, aliases: list[str]) -> dict[str, Any]:
        current_room, current_entity = self._split_device_key(device_key)
        room = room.strip()
        entity_id = entity_id.strip()
        aliases = [alias.strip() for alias in aliases if alias.strip()]

        if not room or not entity_id:
            raise ValueError("room_and_entity_required")

        config = self.load()
        devices = config.setdefault("devices", {})

        current_room_data = devices.get(current_room)
        if not isinstance(current_room_data, dict) or current_entity not in current_room_data:
            raise KeyError("device_not_found")

        target_room_data = devices.setdefault(room, {})
        if not isinstance(target_room_data, dict):
            target_room_data = {}
            devices[room] = target_room_data

        if (room != current_room or entity_id != current_entity) and entity_id in target_room_data:
            raise ValueError("device_already_exists")

        current_room_data.pop(current_entity)
        if not current_room_data:
            devices.pop(current_room, None)

        devices.setdefault(room, {})[entity_id] = {"aliases": aliases}
        self.save(config)
        return self.get_device(self._build_device_key(room, entity_id))

    def delete_device(self, device_key: str) -> None:
        room, entity_id = self._split_device_key(device_key)
        config = self.load()
        devices = config.setdefault("devices", {})

        room_data = devices.get(room)
        if not isinstance(room_data, dict) or entity_id not in room_data:
            raise KeyError("device_not_found")

        room_data.pop(entity_id)
        if not room_data:
            devices.pop(room, None)
        self.save(config)

    def _flatten_devices(self, devices: Any) -> list[dict[str, Any]]:
        if not isinstance(devices, dict):
            return []

        rows: list[dict[str, Any]] = []
        for room, entities in devices.items():
            if not isinstance(room, str) or not isinstance(entities, dict):
                continue
            for entity_id, cfg in entities.items():
                if not isinstance(entity_id, str):
                    continue
                aliases: list[str] = []
                if isinstance(cfg, dict):
                    raw_aliases = cfg.get("aliases", [])
                    if isinstance(raw_aliases, list):
                        aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]
                    elif isinstance(raw_aliases, str) and raw_aliases.strip():
                        aliases = [raw_aliases.strip()]
                rows.append(
                    {
                        "key": self._build_device_key(room, entity_id),
                        "room": room,
                        "entity_id": entity_id,
                        "aliases": aliases,
                    }
                )
        return rows

    def _build_device_key(self, room: str, entity_id: str) -> str:
        return f"{room}|{entity_id}"

    def _split_device_key(self, device_key: str) -> tuple[str, str]:
        if "|" not in device_key:
            raise KeyError("device_not_found")
        room, entity_id = device_key.split("|", 1)
        if not room or not entity_id:
            raise KeyError("device_not_found")
        return room, entity_id

    def _backup_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.config_path.with_suffix(f".backup_{timestamp}.yaml")

    def _audit_file(self) -> Path:
        return self.config_path.parent / "alexa_bridge_audit.jsonl"

    def _backups_dir(self) -> Path:
        return self.config_path.parent / "backups"

    def _backup_file(self, filename: str) -> Path:
        safe_name = Path(filename).name
        if safe_name != filename or not safe_name.endswith(".yaml"):
            raise ValueError("Nome de backup invalido")
        file = self._backups_dir() / safe_name
        if not file.exists() or not file.is_file():
            raise FileNotFoundError(safe_name)
        return file

    def _backup_meta(self, file: Path) -> dict[str, Any]:
        stat = file.stat()
        return {
            "filename": file.name,
            "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }

    def _atomic_write(self, content: str) -> None:
        self._ensure_parent_dir()
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(self.config_path)

    def _ensure_parent_dir(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
