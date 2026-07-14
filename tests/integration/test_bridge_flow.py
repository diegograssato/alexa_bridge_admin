"""Testes de integração do fluxo completo do Alexa Bridge.

Cobre:
  - payload v2 (TYPE/VALUE/AGENT) → output_topic + ack ok
  - payload inválido → dlq (invalid_payload)
  - TYPE inválido   → dlq (invalid_type)
  - DEVICE ausente  → dlq + ack error
  - VALUE ausente   → dlq + ack error
  - dispositivo não mapeado → dlq + ack error
  - AGENT propagado no output payload
  - idempotência    → segunda mensagem igual descartada
  - retry de publish → falhas transientes recuperadas
"""
from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Re-usa o helper de importação do test_bridge (sem duplicar código)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))
from test_bridge import _import_bridge  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture compartilhada
# ---------------------------------------------------------------------------

_DEFAULT_CFG = {
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
                "aliases": ["luz da sala", "sala"]
            }
        }
    },
}


@pytest.fixture()
def ctx(tmp_path):
    """Retorna (módulo bridge, mock_mqtt) prontos para uso."""
    cfg_file = tmp_path / "alexa_bridge.yaml"
    cfg_file.write_text(yaml.safe_dump(_DEFAULT_CFG, allow_unicode=True), encoding="utf-8")
    mod, _log, _mqtt = _import_bridge(cfg_file)
    # Override CONFIG_FILE so load_config() reads from tmp_path
    mod.CONFIG_FILE = str(cfg_file)
    mod.CONFIG = mod.load_config()
    mod.DEVICE_INDEX = mod.build_device_index(mod.CONFIG)
    mod.INPUT_TOPIC  = mod.CONFIG["mqtt"]["input_topic"]
    mod.OUTPUT_TOPIC = mod.CONFIG["mqtt"]["output_topic"]
    mod.ACK_TOPIC    = mod.CONFIG["mqtt"]["ack_topic"]
    mod.DLQ_TOPIC    = mod.CONFIG["mqtt"]["dlq_topic"]
    mod._processed_ids.clear()
    return mod, _mqtt


def _payload(**kwargs) -> str:
    """Gera payload no formato v2 (TYPE/VALUE/AGENT)."""
    base = {
        "DEVICE": "media_player.echo_sala",
        "TYPE": "COMMAND",
        "VALUE": "ligar tv",
        "AGENT": "echo_sala_fonetico",
        "ORIGIN": "echo_sala_fonetico",
        "INTENT": "CustomIntent",
        "CORRELATION_ID": "test-cid-001",
    }
    base.update(kwargs)
    return json.dumps(base)


def _published_topics(mock_mqtt) -> list[str]:
    """Extrai lista de tópicos de todas as chamadas mqtt.publish."""
    return [c.kwargs.get("topic") or c.args[0] for c in mock_mqtt.publish.call_args_list]


def _published_payload(mock_mqtt, topic: str) -> dict:
    """Retorna o payload (dict) da primeira publicação no tópico dado."""
    for c in mock_mqtt.publish.call_args_list:
        t = c.kwargs.get("topic") or c.args[0]
        if t == topic:
            raw = c.kwargs.get("payload") or c.args[1]
            return json.loads(raw)
    raise AssertionError(f"Nenhuma publicação encontrada no tópico {topic!r}")


# ---------------------------------------------------------------------------
# Fluxo feliz — payload válido
# ---------------------------------------------------------------------------

class TestValidPayload:
    def test_publishes_to_output_topic(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(topic="alexa/command", payload=_payload())
        assert "homeassistant/voice/command" in _published_topics(mqtt_mock)

    def test_publishes_ack_ok(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(topic="alexa/command", payload=_payload())
        ack = _published_payload(mqtt_mock, "homeassistant/voice/ack")
        assert ack["status"] == "ok"
        assert ack["correlation_id"] == "test-cid-001"

    def test_output_payload_fields(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(topic="alexa/command", payload=_payload())
        out = _published_payload(mqtt_mock, "homeassistant/voice/command")
        assert out["destination"] == "sala"
        assert out["state"] == "on"
        assert out["scene"] == "ligar_tv"
        assert out["correlation_id"] == "test-cid-001"

    def test_new_fields_in_output(self, ctx):
        """TYPE, VALUE e AGENT devem estar presentes no payload de saída."""
        mod, mqtt_mock = ctx
        mod.alexa_bridge(topic="alexa/command", payload=_payload())
        out = _published_payload(mqtt_mock, "homeassistant/voice/command")
        assert out["type"]  == "COMMAND"
        assert out["value"] == "ligar tv"
        assert out["agent"] == "echo_sala_fonetico"

    def test_agent_populated_from_agent_field(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=_payload(AGENT="skill_hall", CORRELATION_ID="agent-001"),
        )
        out = _published_payload(mqtt_mock, "homeassistant/voice/command")
        assert out["agent"] == "skill_hall"

    def test_state_off_for_off_keyword(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=_payload(VALUE="desliga a tv", CORRELATION_ID="off-001"),
        )
        out = _published_payload(mqtt_mock, "homeassistant/voice/command")
        assert out["state"] == "off"

    def test_content_envelope_accepted(self, ctx):
        mod, mqtt_mock = ctx
        wrapped = json.dumps({
            "content": {
                "DEVICE": "media_player.echo_sala",
                "TYPE": "COMMAND",
                "VALUE": "ligar",
                "AGENT": "echo_env",
                "CORRELATION_ID": "env-001",
            }
        })
        mod.alexa_bridge(topic="alexa/command", payload=wrapped)
        out = _published_payload(mqtt_mock, "homeassistant/voice/command")
        assert out["agent"] == "echo_env"

    def test_alias_resolves_correctly(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=_payload(DEVICE="luz da sala", CORRELATION_ID="alias-001"),
        )
        out = _published_payload(mqtt_mock, "homeassistant/voice/command")
        assert out["destination"] == "sala"
        assert out["source_entity"] == "media_player.echo_sala"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Rejeições → DLQ
# ---------------------------------------------------------------------------

class TestRejections:
    def test_invalid_payload_goes_to_dlq(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(topic="alexa/command", payload="NOT JSON {{")
        dlq = _published_payload(mqtt_mock, "homeassistant/voice/dlq")
        assert dlq["reason"] == "invalid_payload"

    def test_missing_device_goes_to_dlq(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=json.dumps({"TYPE": "COMMAND", "VALUE": "ligar", "CORRELATION_ID": "miss-dev"}),
        )
        dlq = _published_payload(mqtt_mock, "homeassistant/voice/dlq")
        assert dlq["reason"] == "missing_device"
        ack = _published_payload(mqtt_mock, "homeassistant/voice/ack")
        assert ack["status"] == "error"

    def test_missing_command_goes_to_dlq(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=json.dumps({"DEVICE": "media_player.echo_sala", "TYPE": "COMMAND", "CORRELATION_ID": "miss-cmd"}),
        )
        dlq = _published_payload(mqtt_mock, "homeassistant/voice/dlq")
        assert dlq["reason"] == "missing_command"

    def test_unmapped_device_goes_to_dlq(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=_payload(DEVICE="media_player.nao_existe", CORRELATION_ID="unmap-001"),
        )
        dlq = _published_payload(mqtt_mock, "homeassistant/voice/dlq")
        assert dlq["reason"] == "device_not_mapped"

    def test_invalid_type_goes_to_dlq(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(
            topic="alexa/command",
            payload=_payload(TYPE="INVALID_TYPE", CORRELATION_ID="inv-type-001"),
        )
        dlq = _published_payload(mqtt_mock, "homeassistant/voice/dlq")
        assert dlq["reason"] == "invalid_type"
        ack = _published_payload(mqtt_mock, "homeassistant/voice/ack")
        assert ack["status"] == "error"


# ---------------------------------------------------------------------------
# Idempotência
# ---------------------------------------------------------------------------

class TestIdempotencyFlow:
    def test_duplicate_message_not_processed_twice(self, ctx):
        mod, mqtt_mock = ctx
        p = _payload(CORRELATION_ID="dup-flow-001")

        mod.alexa_bridge(topic="alexa/command", payload=p)
        first_call_count = mqtt_mock.publish.call_count

        # Segunda mensagem com mesmo correlation_id deve ser ignorada
        mod.alexa_bridge(topic="alexa/command", payload=p)
        assert mqtt_mock.publish.call_count == first_call_count

    def test_different_correlation_id_processed(self, ctx):
        mod, mqtt_mock = ctx
        mod.alexa_bridge(topic="alexa/command", payload=_payload(CORRELATION_ID="first"))
        count_after_first = mqtt_mock.publish.call_count

        mod.alexa_bridge(topic="alexa/command", payload=_payload(CORRELATION_ID="second"))
        assert mqtt_mock.publish.call_count > count_after_first

    def test_expired_duplicate_is_reprocessed(self, ctx):
        mod, mqtt_mock = ctx
        cid = "exp-reprocess"
        # Simula ID processado há muito tempo (expirado)
        mod._processed_ids[cid] = time.time() - (mod._IDEMPOTENCY_TTL_SECONDS + 10)

        mod.alexa_bridge(topic="alexa/command", payload=_payload(correlation_id=cid))
        assert "homeassistant/voice/command" in _published_topics(mqtt_mock)


# ---------------------------------------------------------------------------
# Retry com backoff
# ---------------------------------------------------------------------------

class TestRetryBackoff:
    def test_succeeds_on_second_attempt(self, ctx):
        mod, mqtt_mock = ctx
        # Falha na 1ª tentativa, sucesso na 2ª
        mqtt_mock.publish.side_effect = [Exception("timeout"), None]

        result = mod.publish_event("test/topic", {"key": "value"})

        assert result is True
        assert mqtt_mock.publish.call_count == 2

    def test_succeeds_on_third_attempt(self, ctx):
        mod, mqtt_mock = ctx
        mqtt_mock.publish.side_effect = [
            Exception("err1"),
            Exception("err2"),
            None,
        ]
        result = mod.publish_event("test/topic", {"key": "value"})
        assert result is True
        assert mqtt_mock.publish.call_count == 3

    def test_fails_after_all_retries(self, ctx):
        mod, mqtt_mock = ctx
        mqtt_mock.publish.side_effect = Exception("persistent error")

        with patch.object(mod, "time") as mock_time:
            mock_time.sleep = MagicMock()
            mock_time.time = time.time
            result = mod.publish_event("test/topic", {"k": "v"})

        assert result is False
        assert mqtt_mock.publish.call_count == mod._PUBLISH_MAX_RETRIES

    def test_publish_failed_goes_to_dlq(self, ctx):
        mod, mqtt_mock = ctx
        # Todas as tentativas de publicação falham (incluindo DLQ/ACK)
        # mas só queremos verificar que o fluxo tenta o DLQ
        attempt = 0
        original_publish = mqtt_mock.publish

        def fail_output_only(*args, **kwargs):
            nonlocal attempt
            topic = kwargs.get("topic") or args[0]
            if topic == "homeassistant/voice/command" and attempt < mod._PUBLISH_MAX_RETRIES:
                attempt += 1
                raise Exception("publish failed")

        mqtt_mock.publish.side_effect = fail_output_only

        with patch.object(mod, "time") as mock_time:
            mock_time.sleep = MagicMock()
            mock_time.time = time.time
            mod.alexa_bridge(
                topic="alexa/command",
                payload=_payload(correlation_id="fail-pub-001"),
            )

        dlq_calls = [
            c for c in mqtt_mock.publish.call_args_list
            if (c.kwargs.get("topic") or c.args[0]) == "homeassistant/voice/dlq"
        ]
        assert len(dlq_calls) >= 1
