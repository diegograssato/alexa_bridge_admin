from __future__ import annotations

import os
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml


BACKUP_RETENTION_DAYS = 30
AUDIT_RETENTION_DAYS = 30
MAX_BACKUPS_PER_DAY = 10


class ConfigService:
    def __init__(self, config_path: str | None = None) -> None:
        path = config_path or os.getenv("ALEXA_BRIDGE_CONFIG_PATH", "/homeassistant/pyscript/alexa_bridge.yaml")
        self.config_path = Path(path)

    def defaults(self) -> dict[str, Any]:
        return {
            "transport": {
                "mqtt_enabled": True,
                "webhook_enabled": True,
            },
            "mqtt": {
                "input_topic": "alexa/command",
                "output_topic": "homeassistant/voice/command",
                "ack_topic": "homeassistant/voice/ack",
                "dlq_topic": "homeassistant/voice/dlq",
            },
            "integration": {
                "mqtt": {
                    "type": "event_bus",
                    "mqtt": {
                        "output_topic": "homeassistant/voice/command",
                        "ack_topic": "homeassistant/voice/ack",
                        "dlq_topic": "homeassistant/voice/dlq",
                    },
                    "event_bus": {
                        "event_name": "alexa_bridge.command.mqtt",
                    },
                },
                "webhook": {
                    "type": "event_bus",
                    "mqtt": {
                        "output_topic": "homeassistant/voice/command",
                        "ack_topic": "homeassistant/voice/ack",
                        "dlq_topic": "homeassistant/voice/dlq",
                    },
                    "event_bus": {
                        "event_name": "alexa_bridge.command.webhook",
                    },
                },
            },
            "security": {
                "enabled": False,
                "secret": "",
                "encrypt_payload": False,
            },
            "webhook": {
                "id": "",
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
        transport = data.get("transport") if isinstance(data, dict) else None
        if not isinstance(transport, dict):
            raise ValueError("Campo transport deve ser um objeto")
        if not isinstance(transport.get("mqtt_enabled", True), bool):
            raise ValueError("transport.mqtt_enabled deve ser booleano")
        if not isinstance(transport.get("webhook_enabled", True), bool):
            raise ValueError("transport.webhook_enabled deve ser booleano")
        if not transport.get("mqtt_enabled", True) and not transport.get("webhook_enabled", True):
            raise ValueError("Pelo menos um transporte deve estar habilitado: transport.mqtt_enabled ou transport.webhook_enabled")
        integration = data.get("integration") if isinstance(data, dict) else None
        if integration is not None and not isinstance(integration, dict):
            raise ValueError("Campo integration deve ser um objeto")

        mqtt_root = data.get("mqtt") if isinstance(data, dict) else None
        if not isinstance(mqtt_root, dict):
            raise ValueError("Campo mqtt deve ser um objeto")
        input_topic = str(mqtt_root.get("input_topic", "")).strip()
        if not self._is_valid_mqtt_topic(input_topic):
            raise ValueError("mqtt.input_topic inválido (exemplo válido: alexa/command)")

        self._validate_integration(integration or {}, mqtt_root)

        webhook = data.get("webhook") if isinstance(data, dict) else None
        if not isinstance(webhook, dict):
            raise ValueError("Campo webhook deve ser um objeto")

        webhook_id = ""
        wh_ids = webhook.get("ids")
        if isinstance(wh_ids, list) and len(wh_ids) > 1:
            raise ValueError("webhook.ids suporta no máximo 1 item")
        wh_id_raw = webhook.get("id", "")
        if wh_id_raw is not None and not isinstance(wh_id_raw, str):
            raise ValueError("webhook.id deve ser string")
        webhook_id = str(wh_id_raw).strip() if wh_id_raw is not None else ""
        if webhook_id and not self._is_valid_webhook_id(webhook_id):
            raise ValueError("webhook.id inválido (exemplo válido: alexa_command; não pode conter '/')")

        if not webhook_id and isinstance(wh_ids, list) and wh_ids:
            webhook_id = str(wh_ids[0]).strip()

        security = data.get("security") if isinstance(data, dict) else None
        if not isinstance(security, dict):
            raise ValueError("Campo security deve ser um objeto")
        enabled = security.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("security.enabled deve ser booleano")
        encrypt_payload = security.get("encrypt_payload")
        if not isinstance(encrypt_payload, bool):
            raise ValueError("security.encrypt_payload deve ser booleano")
        secret = security.get("secret")
        if not isinstance(secret, str):
            raise ValueError("security.secret deve ser string")
        if enabled and not secret.strip():
            raise ValueError("security.secret deve ser string nao vazia quando security.enabled=true")

        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, dict):
            raise ValueError("Campo devices deve ser um objeto")

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

    @staticmethod
    def _is_valid_mqtt_topic(topic: str) -> bool:
        if not isinstance(topic, str):
            return False
        value = topic.strip()
        if not value or value.startswith("/") or value.endswith("/"):
            return False
        return re.match(r"^[A-Za-z0-9_./#+-]+$", value) is not None

    @staticmethod
    def _is_valid_webhook_id(webhook_id: str) -> bool:
        if not isinstance(webhook_id, str):
            return False
        value = webhook_id.strip()
        if not value:
            return True
        if "/" in value:
            return False
        return re.match(r"^[A-Za-z0-9_-]+$", value) is not None

    @staticmethod
    def _is_valid_event_name(name: str) -> bool:
        if not isinstance(name, str):
            return False
        value = name.strip()
        if not value:
            return False
        return re.match(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$", value) is not None

    def _validate_integration(self, integration: dict[str, Any], mqtt_root: Any | None = None) -> None:
        if not isinstance(integration, dict):
            raise ValueError("Campo integration deve ser um objeto")

        for source in ["mqtt", "webhook"]:
            source_cfg = integration.get(source)
            if source_cfg is None:
                raise ValueError(f"integration.{source} é obrigatório")
            if not isinstance(source_cfg, dict):
                raise ValueError(f"integration.{source} deve ser um objeto")

            if "type" not in source_cfg:
                raise ValueError(f"integration.{source}.type é obrigatório")

            mode = str(source_cfg.get("type", "")).strip().lower()
            if mode not in {"mqtt", "event_bus"}:
                raise ValueError(f"integration.{source}.type deve ser 'mqtt' ou 'event_bus'")

            if mode == "mqtt":
                mqtt_cfg = source_cfg.get("mqtt")
                if not isinstance(mqtt_cfg, dict):
                    raise ValueError(f"integration.{source}.mqtt deve ser um objeto")
                for key in ["output_topic", "ack_topic", "dlq_topic"]:
                    value = mqtt_cfg.get(key)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(f"integration.{source}.mqtt.{key} deve ser string nao vazia")

            if mode == "event_bus":
                event_cfg = source_cfg.get("event_bus")
                if not isinstance(event_cfg, dict):
                    raise ValueError(f"integration.{source}.event_bus deve ser um objeto")
                if "event_name" not in event_cfg:
                    raise ValueError(f"integration.{source}.event_bus.event_name é obrigatório")
                event_name = event_cfg.get("event_name")
                if not self._is_valid_event_name(str(event_name)):
                    raise ValueError(
                        f"integration.{source}.event_bus.event_name inválido "
                        "(exemplos válidos: alexa_command ou alexa_bridge.command.mqtt)"
                    )

    def normalized_webhook_ids(self, config: dict[str, Any] | None = None) -> list[str]:
        """Extrai e normaliza webhook ids (apenas 1 id ativo, com fallback legado webhook.id)."""
        cfg = config if isinstance(config, dict) else {}
        webhook = cfg.get("webhook")
        if not isinstance(webhook, dict):
            return []

        raw_ids: list[Any]
        ids = webhook.get("ids")
        if isinstance(ids, list):
            raw_ids = ids
        else:
            legacy_id = str(webhook.get("id", "")).strip()
            raw_ids = [legacy_id] if legacy_id else []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_ids:
            wid = str(item).strip()
            if not wid or "/" in wid:
                continue
            if wid in seen:
                continue
            seen.add(wid)
            normalized.append(wid)
            if len(normalized) >= 1:
                break
        return normalized

    def webhook_ids_changed(self, before: dict[str, Any], after: dict[str, Any]) -> bool:
        """Retorna True quando a lista normalizada de webhook ids foi alterada."""
        return self.normalized_webhook_ids(before) != self.normalized_webhook_ids(after)

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
            if not self._is_valid_mqtt_topic(str(mqtt.get("input_topic", ""))):
                errors.append("mqtt.input_topic inválido (exemplo válido: alexa/command)")

        transport = parsed.get("transport")
        if transport is None:
            errors.append("Campo transport é obrigatório")
        elif not isinstance(transport, dict):
            errors.append("Campo transport deve ser um objeto")
        else:
            if "mqtt_enabled" not in transport:
                errors.append("transport.mqtt_enabled é obrigatório")
            mqtt_enabled = transport.get("mqtt_enabled")
            if not isinstance(mqtt_enabled, bool):
                errors.append("transport.mqtt_enabled deve ser booleano")

            if "webhook_enabled" not in transport:
                errors.append("transport.webhook_enabled é obrigatório")
            webhook_enabled = transport.get("webhook_enabled")
            if not isinstance(webhook_enabled, bool):
                errors.append("transport.webhook_enabled deve ser booleano")

            if isinstance(mqtt_enabled, bool) and isinstance(webhook_enabled, bool):
                if not mqtt_enabled and not webhook_enabled:
                    errors.append("Pelo menos um transporte deve estar habilitado: transport.mqtt_enabled ou transport.webhook_enabled")

        integration = parsed.get("integration")
        if integration is None:
            errors.append("Campo integration é obrigatório")
        elif not isinstance(integration, dict):
            errors.append("Campo integration deve ser um objeto")
        else:
            for source in ["mqtt", "webhook"]:
                source_cfg = integration.get(source)
                if source_cfg is None:
                    errors.append(f"integration.{source} é obrigatório")
                    continue
                if not isinstance(source_cfg, dict):
                    errors.append(f"integration.{source} deve ser um objeto")
                    continue

                if "type" not in source_cfg:
                    errors.append(f"integration.{source}.type é obrigatório")
                    continue

                itype = str(source_cfg.get("type", "")).strip().lower()
                if itype not in {"mqtt", "event_bus"}:
                    errors.append(f"integration.{source}.type deve ser 'mqtt' ou 'event_bus'")
                    continue

                if itype == "mqtt":
                    mqtt_cfg = source_cfg.get("mqtt")
                    if not isinstance(mqtt_cfg, dict):
                        errors.append(f"integration.{source}.mqtt deve ser um objeto")
                    else:
                        for key in ["output_topic", "ack_topic", "dlq_topic"]:
                            value = mqtt_cfg.get(key)
                            if not isinstance(value, str) or not value.strip():
                                errors.append(f"integration.{source}.mqtt.{key} deve ser string nao vazia")

                if itype == "event_bus":
                    event_cfg = source_cfg.get("event_bus")
                    if not isinstance(event_cfg, dict):
                        errors.append(f"integration.{source}.event_bus deve ser um objeto")
                    else:
                        if "event_name" not in event_cfg:
                            errors.append(f"integration.{source}.event_bus.event_name é obrigatório")
                        event_name = event_cfg.get("event_name", "")
                        if not self._is_valid_event_name(str(event_name)):
                            errors.append(
                                f"integration.{source}.event_bus.event_name inválido "
                                "(exemplos válidos: alexa_command ou alexa_bridge.command.mqtt)"
                            )

        commands = parsed.get("commands")
        if not isinstance(commands, dict):
            errors.append("Campo commands deve ser um objeto")
        else:
            off_keywords = commands.get("off_keywords")
            if not isinstance(off_keywords, list) or not all(isinstance(x, str) for x in off_keywords):
                errors.append("commands.off_keywords deve ser lista de strings")

        if "devices" not in parsed:
            errors.append("Campo devices é obrigatório")
            devices = {}
        else:
            devices = parsed.get("devices")
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

        security = parsed.get("security")
        if security is None:
            errors.append("Campo security é obrigatório")
        elif not isinstance(security, dict):
            errors.append("Campo security deve ser um objeto")
        else:
            if "enabled" not in security:
                errors.append("security.enabled é obrigatório")
            enabled = security.get("enabled")
            if not isinstance(enabled, bool):
                errors.append("security.enabled deve ser booleano")

            if "secret" not in security:
                errors.append("security.secret é obrigatório")
            secret = security.get("secret")
            if not isinstance(secret, str):
                errors.append("security.secret deve ser string")
            elif enabled is True and not secret.strip():
                errors.append("security.secret deve ser string nao vazia quando security.enabled=true")

            if "encrypt_payload" not in security:
                errors.append("security.encrypt_payload é obrigatório")
            encrypt_payload = security.get("encrypt_payload")
            if not isinstance(encrypt_payload, bool):
                errors.append("security.encrypt_payload deve ser booleano")

        webhook = parsed.get("webhook")
        if webhook is None:
            errors.append("Campo webhook é obrigatório")
        elif not isinstance(webhook, dict):
            errors.append("Campo webhook deve ser um objeto")
        else:
            if "id" not in webhook:
                errors.append("webhook.id é obrigatório")
            wh_ids = webhook.get("ids")
            if wh_ids is not None:
                if not isinstance(wh_ids, list):
                    errors.append("webhook.ids deve ser uma lista")
                else:
                    if len(wh_ids) > 1:
                        errors.append("webhook.ids suporta no máximo 1 item")
                    for wid in wh_ids:
                        w = str(wid).strip()
                        if not w:
                            errors.append("webhook.ids não pode conter itens vazios")
                        elif "/" in w:
                            errors.append(f"webhook.ids contém ID inválido '{w}' (não pode conter '/')")

            wh_id_raw = webhook.get("id", "")
            if wh_id_raw is not None and not isinstance(wh_id_raw, str):
                errors.append("webhook.id deve ser string")
            wh_id = str(wh_id_raw).strip() if wh_id_raw is not None else ""
            if wh_id and not self._is_valid_webhook_id(wh_id):
                errors.append("webhook.id inválido (exemplo válido: alexa_command; não pode conter '/')")

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

        if self._count_backups_today() >= MAX_BACKUPS_PER_DAY:
            raise ValueError("Limite diário atingido: máximo de 10 backups por dia")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"alexa_bridge_backup_{timestamp}.yaml"
        target = backups_dir / filename
        shutil.copy2(self.config_path, target)

        # Retenção: remove backups com mais de 30 dias, sem deixar o diretório vazio.
        self._prune_old_backups()

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

    def sync_bridge_script(self, script_target_path: str | None = None, template_path: str | None = None) -> dict[str, Any]:
        """Sincroniza o script do bridge com o template empacotado.

        Diferente de ensure_bridge_script, este método sempre copia o template
        para o destino, garantindo atualização após update do add-on.
        """
        target = Path(script_target_path or os.getenv("ALEXA_BRIDGE_SCRIPT_PATH", "/homeassistant/pyscript/alexa_bridge.py"))
        source = Path(template_path or os.getenv("ALEXA_BRIDGE_SCRIPT_TEMPLATE", "/app/assets/alexa_bridge.py"))

        if not source.exists():
            return {
                "ok": False,
                "copied": False,
                "detail": "template_not_found",
                "target": str(target),
                "source": str(source),
            }

        target.parent.mkdir(parents=True, exist_ok=True)
        overwritten = target.exists()
        shutil.copy2(source, target)
        return {
            "ok": True,
            "copied": True,
            "overwritten": overwritten,
            "detail": "script_updated" if overwritten else "script_copied",
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

        # Retenção: remove eventos >30 dias, preservando ao menos 1 por tipo de ação.
        self._prune_old_audits()

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

    def _last_event_file(self) -> Path:
        return self.config_path.parent / "_bridge_last_event.json"

    def get_last_event(self) -> dict[str, Any] | None:
        """Lê o último evento processado pelo bridge PyScript (sidecar JSON)."""
        f = self._last_event_file()
        if not f.exists():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return None

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

    def _prune_old_backups(self) -> None:
        backups_dir = self._backups_dir()
        if not backups_dir.exists():
            return

        files = [f for f in backups_dir.glob("*.yaml") if f.is_file()]
        if len(files) <= 1:
            return

        cutoff = datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)
        files.sort(key=lambda f: f.stat().st_mtime)

        remaining = len(files)
        for file in files:
            if remaining <= 1:
                break
            modified_at = datetime.fromtimestamp(file.stat().st_mtime)
            if modified_at < cutoff:
                try:
                    file.unlink()
                    remaining -= 1
                except FileNotFoundError:
                    continue

    def _prune_old_audits(self) -> None:
        file = self._audit_file()
        if not file.exists() or not file.is_file():
            return

        rows: list[dict[str, Any]] = []
        with file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)

        if not rows:
            return

        cutoff = datetime.now() - timedelta(days=AUDIT_RETENTION_DAYS)

        parsed_times: list[datetime | None] = []
        for row in rows:
            created_at_raw = row.get("created_at")
            parsed: datetime | None = None
            if isinstance(created_at_raw, str) and created_at_raw.strip():
                text = created_at_raw.strip()
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                try:
                    parsed = datetime.fromisoformat(text)
                except ValueError:
                    parsed = None
            parsed_times.append(parsed)

        # Sempre manter o evento mais recente de cada tipo (action), mesmo se antigo.
        keep_indexes: set[int] = set()
        latest_per_action: dict[str, int] = {}
        for idx, row in enumerate(rows):
            action = str(row.get("action") or "UNKNOWN")
            current_best_idx = latest_per_action.get(action)
            if current_best_idx is None:
                latest_per_action[action] = idx
                continue

            current_best_time = parsed_times[current_best_idx] or datetime.min
            candidate_time = parsed_times[idx] or datetime.min
            if candidate_time >= current_best_time:
                latest_per_action[action] = idx

        keep_indexes.update(latest_per_action.values())

        # Mantém também todos os eventos dentro da janela de retenção.
        for idx, parsed in enumerate(parsed_times):
            if parsed is not None and parsed >= cutoff:
                keep_indexes.add(idx)

        kept_rows = [rows[idx] for idx in range(len(rows)) if idx in keep_indexes]

        tmp = file.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for item in kept_rows:
                f.write(json.dumps(item, ensure_ascii=True) + "\n")
        tmp.replace(file)

    def _count_backups_today(self) -> int:
        backups_dir = self._backups_dir()
        if not backups_dir.exists():
            return 0

        today = datetime.now().date()
        count = 0
        for file in backups_dir.glob("*.yaml"):
            if not file.is_file():
                continue
            modified = datetime.fromtimestamp(file.stat().st_mtime)
            if modified.date() == today:
                count += 1
        return count
