"""Testes unitários das funções puras de alexa_bridge.py.

Estratégia: injeta stubs dos globais de PyScript (log, mqtt,
homeassistant.util.yaml) antes de importar o módulo, permitindo
testar toda a lógica sem depender do runtime do HA.
"""
from __future__ import annotations

import json
import hmac
import sys
import time
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Stubs do ambiente PyScript / Home Assistant
# ---------------------------------------------------------------------------

def _make_ha_stubs(tmp_yaml_path: Path):
    """Cria módulos stub para homeassistant e pyscript globals."""

    # homeassistant.util.yaml stub
    ha_pkg = types.ModuleType("homeassistant")
    ha_util = types.ModuleType("homeassistant.util")
    ha_yaml = types.ModuleType("homeassistant.util.yaml")

    def load_yaml(path):
        p = Path(path)
        if not p.exists():
            return {}
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    ha_yaml.load_yaml = load_yaml
    ha_pkg.util = ha_util
    ha_util.yaml = ha_yaml
    sys.modules.setdefault("homeassistant", ha_pkg)
    sys.modules.setdefault("homeassistant.util", ha_util)
    sys.modules.setdefault("homeassistant.util.yaml", ha_yaml)

    # Globais injetados pelo pyscript: log, mqtt, event, decorators
    _log = MagicMock()
    _mqtt = MagicMock()
    _mqtt.publish = MagicMock()
    _event = MagicMock()
    _event.fire = MagicMock()

    def _service(fn):
        return fn

    def _mqtt_trigger(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    def _webhook_trigger(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    return _log, _mqtt, _event, _service, _mqtt_trigger, _webhook_trigger


def _import_bridge(tmp_yaml_path: Path):
    """Importa alexa_bridge com stubs, retornando o módulo e os mocks."""
    _log, _mqtt, _event, _service, _mqtt_trigger, _webhook_trigger = _make_ha_stubs(tmp_yaml_path)

    bridge_path = (
        Path(__file__).resolve().parents[2]
        / "alexa_bridge_admin" / "rootfs" / "app" / "assets"
    )

    # Remove cache de import anterior para recarregar o módulo limpo
    sys.modules.pop("alexa_bridge", None)

    import importlib.util as ilu

    spec = ilu.spec_from_file_location(
        "alexa_bridge",
        bridge_path / "alexa_bridge.py",
        submodule_search_locations=[],
    )
    mod = ilu.module_from_spec(spec)

    # Injeta globais do pyscript no namespace do módulo antes de exec
    mod.log = _log
    mod.mqtt = _mqtt
    mod.event = _event
    mod.service = _service
    mod.mqtt_trigger = _mqtt_trigger
    mod.webhook_trigger = _webhook_trigger

    # Patch builtins que o pyscript provê como built-ins globais
    with (
        patch.object(mod, "log", _log, create=True),
        patch.object(mod, "mqtt", _mqtt, create=True),
    ):
        # Precisamos executar o loader com os globals corretos
        spec.loader.exec_module(mod)

    return mod, _log, _mqtt, _event


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def bridge(tmp_path):
    """Retorna o módulo bridge carregado com YAML de fixtures."""
    cfg = {
        "mqtt": {
            "input_topic": "alexa/command",
            "output_topic": "homeassistant/voice/command",
            "ack_topic": "homeassistant/voice/ack",
            "dlq_topic": "homeassistant/voice/dlq",
        },
        "commands": {"off_keywords": ["desliga", "desligar", "turn off"]},
        "devices": {
            "sala": {
                "media_player.echo_sala": {
                    "aliases": ["luz da sala", "sala", "echo sala"]
                }
            },
            "quarto": {
                "media_player.echo_quarto": {
                    "aliases": ["quarto", "luz do quarto"]
                }
            },
        },
    }
    cfg_file = tmp_path / "alexa_bridge.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    mod, _log, _mqtt, _event = _import_bridge(cfg_file)
    # Override CONFIG_FILE so load_config() reads from tmp_path
    mod.CONFIG_FILE = str(cfg_file)
    mod.CONFIG = mod.load_config()
    mod.DEVICE_INDEX = mod.build_device_index(mod.CONFIG)
    mod.INPUT_TOPIC  = mod.CONFIG["mqtt"]["input_topic"]
    mod.OUTPUT_TOPIC = mod.CONFIG["mqtt"]["output_topic"]
    mod.ACK_TOPIC    = mod.CONFIG["mqtt"]["ack_topic"]
    mod.DLQ_TOPIC    = mod.CONFIG["mqtt"]["dlq_topic"]
    mod._log = _log
    mod._mqtt_mock = _mqtt
    mod._event_mock = _event
    return mod


# ---------------------------------------------------------------------------
# safe_str / normalize_key
# ---------------------------------------------------------------------------

class TestSafeStr:
    def test_none_returns_empty(self, bridge):
        assert bridge.safe_str(None) == ""

    def test_strips_whitespace(self, bridge):
        assert bridge.safe_str("  hello  ") == "hello"

    def test_converts_int(self, bridge):
        assert bridge.safe_str(42) == "42"


class TestNormalizeKey:
    def test_lowercases(self, bridge):
        assert bridge.normalize_key("SALA") == "sala"

    def test_strips_and_lower(self, bridge):
        assert bridge.normalize_key("  Echo Sala  ") == "echo sala"


# ---------------------------------------------------------------------------
# parse_payload
# ---------------------------------------------------------------------------

class TestParsePayload:
    def test_valid_json_string(self, bridge):
        data = bridge.parse_payload('{"DEVICE": "d", "COMANDO": "ligar"}')
        assert data["DEVICE"] == "d"

    def test_dict_passthrough(self, bridge):
        raw = {"DEVICE": "d", "COMANDO": "cmd"}
        assert bridge.parse_payload(raw) is raw

    def test_content_envelope_unwrapped(self, bridge):
        payload = json.dumps({"content": {"DEVICE": "d", "COMANDO": "ligar"}})
        data = bridge.parse_payload(payload)
        assert data["DEVICE"] == "d"

    def test_content_string_envelope(self, bridge):
        inner = json.dumps({"DEVICE": "x", "COMANDO": "c"})
        payload = json.dumps({"content": inner})
        data = bridge.parse_payload(payload)
        assert data["DEVICE"] == "x"

    def test_invalid_json_returns_none(self, bridge):
        assert bridge.parse_payload("not json {{") is None

    def test_empty_string_returns_none(self, bridge):
        assert bridge.parse_payload("") is None

    def test_none_returns_none(self, bridge):
        assert bridge.parse_payload(None) is None

    def test_non_dict_root_returns_none(self, bridge):
        assert bridge.parse_payload("[1, 2, 3]") is None


# ---------------------------------------------------------------------------
# build_device_index / get_device_info
# ---------------------------------------------------------------------------

class TestDeviceIndex:
    def test_entity_id_resolved(self, bridge):
        info = bridge.get_device_info("media_player.echo_sala")
        assert info is not None
        assert info["room"] == "sala"
        assert info["entity"] == "media_player.echo_sala"

    def test_alias_resolved(self, bridge):
        info = bridge.get_device_info("luz da sala")
        assert info is not None
        assert info["room"] == "sala"

    def test_alias_case_insensitive(self, bridge):
        info = bridge.get_device_info("LUZ DA SALA")
        assert info is not None

    def test_unknown_device_returns_none(self, bridge):
        assert bridge.get_device_info("media_player.nao_existe") is None

    def test_multiple_rooms(self, bridge):
        info = bridge.get_device_info("quarto")
        assert info["room"] == "quarto"


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------

class TestGetState:
    def test_on_by_default(self, bridge):
        assert bridge.get_state("ligar luz") == "on"

    def test_off_keyword_desliga(self, bridge):
        assert bridge.get_state("desliga a luz") == "off"

    def test_off_keyword_desligar(self, bridge):
        assert bridge.get_state("desligar ventilador") == "off"

    def test_off_keyword_turn_off(self, bridge):
        assert bridge.get_state("turn off the tv") == "off"

    def test_empty_command_is_off(self, bridge):
        assert bridge.get_state("") == "off"

    def test_case_insensitive(self, bridge):
        assert bridge.get_state("DESLIGA TV") == "off"


# ---------------------------------------------------------------------------
# normalize_command
# ---------------------------------------------------------------------------

class TestNormalizeCommand:
    def test_spaces_replaced(self, bridge):
        assert bridge.normalize_command("ligar luz") == "ligar_luz"

    def test_lowercased(self, bridge):
        assert bridge.normalize_command("LIGAR LUZ") == "ligar_luz"

    def test_double_underscores_collapsed(self, bridge):
        result = bridge.normalize_command("ligar  luz")
        assert "__" not in result

    def test_empty_returns_empty(self, bridge):
        assert bridge.normalize_command("") == ""


# ---------------------------------------------------------------------------
# topic_matches
# ---------------------------------------------------------------------------

class TestTopicMatches:
    def test_exact_match(self, bridge):
        assert bridge.topic_matches("alexa/command", "alexa/command")

    def test_no_match(self, bridge):
        assert not bridge.topic_matches("alexa/command", "alexa/other")

    def test_single_level_wildcard(self, bridge):
        assert bridge.topic_matches("alexa/+", "alexa/command")

    def test_multi_level_wildcard(self, bridge):
        assert bridge.topic_matches("alexa/#", "alexa/command/extra")

    def test_hash_at_root(self, bridge):
        assert bridge.topic_matches("#", "any/topic/here")

    def test_wildcard_does_not_match_different_prefix(self, bridge):
        assert not bridge.topic_matches("alexa/+", "other/command")


# ---------------------------------------------------------------------------
# build_correlation_id
# ---------------------------------------------------------------------------

class TestBuildCorrelationId:
    def test_uses_existing_correlation_id(self, bridge):
        data = {"correlation_id": "my-id-123"}
        assert bridge.build_correlation_id(data) == "my-id-123"

    def test_uses_request_id_fallback(self, bridge):
        data = {"request_id": "req-456"}
        assert bridge.build_correlation_id(data) == "req-456"

    def test_generates_uuid_when_absent(self, bridge):
        cid = bridge.build_correlation_id({})
        # Must be a valid UUID
        uuid.UUID(cid)

    def test_uppercase_key_accepted(self, bridge):
        data = {"CORRELATION_ID": "upper-id"}
        assert bridge.build_correlation_id(data) == "upper-id"


# ---------------------------------------------------------------------------
# Idempotência
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_first_call_not_duplicate(self, bridge):
        bridge._processed_ids.clear()
        assert not bridge._is_duplicate("new-id-001")

    def test_second_call_is_duplicate(self, bridge):
        bridge._processed_ids.clear()
        bridge._mark_processed("dup-id-001")
        assert bridge._is_duplicate("dup-id-001")

    def test_expired_id_not_duplicate(self, bridge):
        bridge._processed_ids.clear()
        cid = "old-id-001"
        # Registra com timestamp expirado
        bridge._processed_ids[cid] = time.time() - (bridge._IDEMPOTENCY_TTL_SECONDS + 1)
        assert not bridge._is_duplicate(cid)

    def test_purge_removes_expired(self, bridge):
        bridge._processed_ids.clear()
        bridge._processed_ids["exp"] = time.time() - 9999
        bridge._processed_ids["fresh"] = time.time()
        bridge._purge_expired_ids()
        assert "exp" not in bridge._processed_ids
        assert "fresh" in bridge._processed_ids


class TestIntegrationAndTransport:
    def test_transport_enabled_defaults_true(self, bridge):
        bridge.CONFIG["transport"] = {}
        assert bridge.is_transport_enabled("mqtt") is True
        assert bridge.is_transport_enabled("webhook") is True

    def test_transport_enabled_flags(self, bridge):
        bridge.CONFIG["transport"] = {"mqtt_enabled": False, "webhook_enabled": True}
        assert bridge.is_transport_enabled("mqtt") is False
        assert bridge.is_transport_enabled("webhook") is True

    def test_get_integration_config_defaults(self, bridge):
        bridge.CONFIG["integration"] = {}
        cfg = bridge.get_integration_config("mqtt")
        assert cfg["type"] in {"mqtt", "event_bus"}
        assert cfg["mqtt"]["output_topic"]
        assert cfg["event_bus"]["event_name"].endswith(".mqtt")


class TestSecurityAndEventBus:
    def test_verify_hmac_with_forced_signature(self, bridge):
        bridge.CONFIG["security"] = {"enabled": True, "secret": "abc"}
        body = {"content": {"DEVICE": "d", "VALUE": "v"}}
        signing_base = bridge._extract_signing_base(body)
        expected = hmac.new(
            b"abc",
            json.dumps(signing_base, sort_keys=True).encode("utf-8"),
            bridge.sha256,
        ).hexdigest()
        assert bridge.verify_hmac(body, correlation_id="cid", forced_signature=expected) is True

    def test_publish_internal_event_adds_source_metadata(self, bridge):
        payload = {"name": "cmd"}
        ok = bridge.publish_internal_event("alexa_bridge.command.test", payload, "cid-1", source="webhook")
        assert ok is True
        bridge._event_mock.fire.assert_called_once()
        _, kwargs = bridge._event_mock.fire.call_args
        assert kwargs["provided_by"] == "webhook"
        assert kwargs["transport_source"] == "webhook"


class TestProcessCommandBranches:
    def test_process_command_invalid_payload_goes_to_dlq(self, bridge, monkeypatch):
        calls = []

        monkeypatch.setattr(bridge, "parse_payload", lambda raw: None)
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": calls.append((topic, reason, source)),
        )

        bridge._process_command("mqtt", "not-json", "alexa/command")
        assert calls == [("alexa/command", "invalid_payload", "mqtt")]

    def test_process_command_invalid_signature_emits_dlq_and_ack(self, bridge, monkeypatch):
        dlq_calls = []
        ack_calls = []

        monkeypatch.setattr(bridge, "parse_payload", lambda raw: {"DEVICE": "sala", "VALUE": "ligar", "correlation_id": "cid-1"})
        monkeypatch.setattr(bridge, "verify_hmac", lambda raw, correlation_id, forced_signature=None: False)
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": dlq_calls.append((reason, correlation_id, source)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_ack",
            lambda topic, correlation_id, status, detail="", source="mqtt": ack_calls.append((status, detail, correlation_id, source)),
        )

        bridge._process_command("mqtt", "raw", "alexa/command")
        assert dlq_calls == [("invalid_signature", "cid-1", "mqtt")]
        assert ack_calls == [("error", "invalid_signature", "cid-1", "mqtt")]

    def test_process_command_decrypt_failed_emits_dlq_and_ack(self, bridge, monkeypatch):
        dlq_calls = []
        ack_calls = []

        monkeypatch.setattr(bridge, "parse_payload", lambda raw: {"DEVICE": "sala", "VALUE": "ligar", "correlation_id": "cid-2"})
        monkeypatch.setattr(bridge, "verify_hmac", lambda raw, correlation_id, forced_signature=None: True)
        monkeypatch.setattr(bridge, "decrypt_payload", lambda data, correlation_id="": None)
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": dlq_calls.append((reason, correlation_id, source)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_ack",
            lambda topic, correlation_id, status, detail="", source="mqtt": ack_calls.append((status, detail, correlation_id, source)),
        )

        bridge._process_command("mqtt", "raw", "alexa/command")
        assert dlq_calls == [("decrypt_failed", "cid-2", "mqtt")]
        assert ack_calls == [("error", "decrypt_failed", "cid-2", "mqtt")]

    def test_process_command_invalid_type_sends_dlq_and_ack(self, bridge, monkeypatch):
        dlq_calls = []
        ack_calls = []

        monkeypatch.setattr(bridge, "verify_hmac", lambda raw, correlation_id, forced_signature=None: True)
        monkeypatch.setattr(bridge, "decrypt_payload", lambda data, correlation_id="": data)
        monkeypatch.setattr(bridge, "_is_duplicate", lambda correlation_id: False)
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": dlq_calls.append((reason, correlation_id, source)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_ack",
            lambda topic, correlation_id, status, detail="", source="mqtt": ack_calls.append((status, detail, correlation_id, source)),
        )

        raw = {"DEVICE": "echo sala", "TYPE": "invalid", "VALUE": "ligar", "correlation_id": "cid-type"}
        bridge._process_command("mqtt", raw, "alexa/command")

        assert dlq_calls == [("invalid_type", "cid-type", "mqtt")]
        assert ack_calls == [("error", "invalid_type", "cid-type", "mqtt")]

    def test_process_command_missing_device_sends_dlq_and_ack(self, bridge, monkeypatch):
        dlq_calls = []
        ack_calls = []

        monkeypatch.setattr(bridge, "verify_hmac", lambda raw, correlation_id, forced_signature=None: True)
        monkeypatch.setattr(bridge, "decrypt_payload", lambda data, correlation_id="": data)
        monkeypatch.setattr(bridge, "_is_duplicate", lambda correlation_id: False)
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": dlq_calls.append((reason, correlation_id, source)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_ack",
            lambda topic, correlation_id, status, detail="", source="mqtt": ack_calls.append((status, detail, correlation_id, source)),
        )

        raw = {"TYPE": "COMMAND", "VALUE": "ligar", "correlation_id": "cid-device"}
        bridge._process_command("mqtt", raw, "alexa/command")

        assert dlq_calls == [("missing_device", "cid-device", "mqtt")]
        assert ack_calls == [("error", "missing_device", "cid-device", "mqtt")]

    def test_process_command_event_bus_success_marks_processed_and_acks(self, bridge, monkeypatch):
        marks = []
        writes = []
        ack_calls = []
        dlq_calls = []

        bridge.CONFIG["integration"]["mqtt"] = {
            "type": "event_bus",
            "event_bus": {"event_name": "alexa_bridge.command.mqtt"},
            "mqtt": {
                "output_topic": "homeassistant/voice/command",
                "ack_topic": "homeassistant/voice/ack",
                "dlq_topic": "homeassistant/voice/dlq",
            },
        }

        monkeypatch.setattr(bridge, "verify_hmac", lambda raw, correlation_id, forced_signature=None: True)
        monkeypatch.setattr(bridge, "decrypt_payload", lambda data, correlation_id="": data)
        monkeypatch.setattr(bridge, "_is_duplicate", lambda correlation_id: False)
        monkeypatch.setattr(bridge, "get_device_info", lambda device: {"room": "sala", "entity": "media_player.echo_sala"})
        monkeypatch.setattr(bridge, "publish_internal_event", lambda event_name, payload, correlation_id="", source="": True)
        monkeypatch.setattr(bridge, "publish_event", lambda topic, payload, correlation_id="": False)
        monkeypatch.setattr(bridge, "_mark_processed", lambda correlation_id: marks.append(correlation_id))
        monkeypatch.setattr(
            bridge,
            "_write_last_event",
            lambda agent, msg_type, device, room, correlation_id: writes.append((agent, msg_type, device, room, correlation_id)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_ack",
            lambda topic, correlation_id, status, detail="", source="mqtt": ack_calls.append((status, detail, correlation_id, source)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": dlq_calls.append((reason, correlation_id, source)),
        )

        raw = {"DEVICE": "echo sala", "TYPE": "command", "VALUE": "ligar", "AGENT": "Jarvis", "correlation_id": "cid-evt"}
        bridge._process_command("mqtt", raw, "alexa/command")

        assert marks == ["cid-evt"]
        assert writes == [("Jarvis", "COMMAND", "echo sala", "sala", "cid-evt")]
        assert ack_calls == [("ok", "published", "cid-evt", "mqtt")]
        assert dlq_calls == []

    def test_process_command_publish_failure_sends_ack_error_and_dlq(self, bridge, monkeypatch):
        ack_calls = []
        dlq_calls = []

        bridge.CONFIG["integration"]["mqtt"] = {
            "type": "mqtt",
            "mqtt": {
                "output_topic": "homeassistant/voice/command",
                "ack_topic": "homeassistant/voice/ack",
                "dlq_topic": "homeassistant/voice/dlq",
            },
            "event_bus": {"event_name": "alexa_bridge.command.mqtt"},
        }

        monkeypatch.setattr(bridge, "verify_hmac", lambda raw, correlation_id, forced_signature=None: True)
        monkeypatch.setattr(bridge, "decrypt_payload", lambda data, correlation_id="": data)
        monkeypatch.setattr(bridge, "_is_duplicate", lambda correlation_id: False)
        monkeypatch.setattr(bridge, "get_device_info", lambda device: {"room": "sala", "entity": "media_player.echo_sala"})
        monkeypatch.setattr(bridge, "publish_event", lambda topic, payload, correlation_id="": False)
        monkeypatch.setattr(
            bridge,
            "publish_ack",
            lambda topic, correlation_id, status, detail="", source="mqtt": ack_calls.append((status, detail, correlation_id, source)),
        )
        monkeypatch.setattr(
            bridge,
            "publish_dlq",
            lambda topic, raw, reason, correlation_id="", source="mqtt": dlq_calls.append((reason, correlation_id, source)),
        )

        raw = {"DEVICE": "echo sala", "TYPE": "command", "VALUE": "ligar", "AGENT": "Jarvis", "correlation_id": "cid-mqtt"}
        bridge._process_command("mqtt", raw, "alexa/command")

        assert ack_calls == [("error", "publish_failed", "cid-mqtt", "mqtt")]
        assert dlq_calls == [("publish_failed", "cid-mqtt", "mqtt")]
