"""Testes unitários das funções puras de alexa_bridge.py.

Estratégia: injeta stubs dos globais de PyScript (log, mqtt,
homeassistant.util.yaml) antes de importar o módulo, permitindo
testar toda a lógica sem depender do runtime do HA.
"""
from __future__ import annotations

import json
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

    # Globais injetados pelo pyscript: log, mqtt, @service, @mqtt_trigger
    _log = MagicMock()
    _mqtt = MagicMock()
    _mqtt.publish = MagicMock()

    def _service(fn):
        return fn

    def _mqtt_trigger(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

    return _log, _mqtt, _service, _mqtt_trigger


def _import_bridge(tmp_yaml_path: Path):
    """Importa alexa_bridge com stubs, retornando o módulo e os mocks."""
    _log, _mqtt, _service, _mqtt_trigger = _make_ha_stubs(tmp_yaml_path)

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
    mod.service = _service
    mod.mqtt_trigger = _mqtt_trigger

    # Patch builtins que o pyscript provê como built-ins globais
    with (
        patch.object(mod, "log", _log, create=True),
        patch.object(mod, "mqtt", _mqtt, create=True),
    ):
        # Precisamos executar o loader com os globals corretos
        spec.loader.exec_module(mod)

    return mod, _log, _mqtt


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

    mod, _log, _mqtt = _import_bridge(cfg_file)
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
