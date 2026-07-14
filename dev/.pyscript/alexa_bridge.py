import json
import uuid
import homeassistant.util.yaml as yaml_util
from datetime import datetime
from typing import Any

CONFIG_FILE = "/config/pyscript/alexa_bridge.yaml"

VERSION = "3.2.0"

DEFAULT_INPUT_TOPIC = "alexa/command"
DEFAULT_OUTPUT_TOPIC = "homeassistant/voice/command"
DEFAULT_ACK_TOPIC = "homeassistant/voice/ack"
DEFAULT_DLQ_TOPIC = "homeassistant/voice/dlq"
DEFAULT_OFF_KEYWORDS = ["desliga", "desligar", "turn off"]

ACTIVE_CONFIG_FILE = ""


# ==========================================================
# NORMALIZATION
# ==========================================================

def safe_str(value: Any) -> str:
    """Converte qualquer valor para string segura sem espaços extras."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_key(value: Any) -> str:
    """Normaliza chaves para comparação case-insensitive."""
    return safe_str(value).lower()


# ==========================================================
# CONFIG
# ==========================================================

def load_config():
    """Carrega a configuração YAML e aplica defaults defensivos."""
    global ACTIVE_CONFIG_FILE
    try:
        config = yaml_util.load_yaml(CONFIG_FILE)
        ACTIVE_CONFIG_FILE = CONFIG_FILE
        if not isinstance(config, dict):
            log.warning(
                "[AlexaBridge] YAML inválido, usando padrão"
            )
            config = {}
        # Defaults defensivos para evitar KeyError em runtime.
        config.setdefault("mqtt", {})
        config.setdefault("commands", {})
        config.setdefault("devices", {})
        config["mqtt"].setdefault(
            "input_topic",
            DEFAULT_INPUT_TOPIC
        )
        config["mqtt"].setdefault(
            "output_topic",
            DEFAULT_OUTPUT_TOPIC
        )
        config["mqtt"].setdefault(
            "ack_topic",
            DEFAULT_ACK_TOPIC
        )
        config["mqtt"].setdefault(
            "dlq_topic",
            DEFAULT_DLQ_TOPIC
        )
        config["commands"].setdefault(
            "off_keywords",
            DEFAULT_OFF_KEYWORDS
        )
        log.info(
            f"[AlexaBridge] Configuração carregada "
            f"de {ACTIVE_CONFIG_FILE}"
        )
        return config
    except Exception as ex:
        log.error(
            f"[AlexaBridge] Erro lendo YAML: {ex}"
        )
        return {}


def build_device_index(config):
    """Monta índice de entidades e aliases para resolução rápida de DEVICE."""
    index = {}
    devices = config.get("devices", {})
    if not isinstance(devices, dict):
        log.warning(
            "[AlexaBridge] devices inválido no YAML"
        )
        return index
    for room, entities in devices.items():
        if not isinstance(entities, dict):
            continue
        for entity, entity_cfg in entities.items():
            key = normalize_key(entity)
            if key == "":
                continue
            index[key] = {
                "room": room,
                "entity": entity
            }
            aliases = []
            if isinstance(entity_cfg, dict):
                aliases = entity_cfg.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            for alias in aliases:
                alias_key = normalize_key(alias)
                if alias_key == "":
                    continue
                index[alias_key] = {
                    "room": room,
                    "entity": entity
                }
    log.info(
        f"[AlexaBridge] "
        f"{len(index)} aliases carregados"
    )
    return index


CONFIG = load_config()
DEVICE_INDEX = build_device_index(CONFIG)
INPUT_TOPIC = CONFIG.get("mqtt", {}).get(
    "input_topic",
    DEFAULT_INPUT_TOPIC
)
OUTPUT_TOPIC = CONFIG.get("mqtt", {}).get(
    "output_topic",
    DEFAULT_OUTPUT_TOPIC
)
ACK_TOPIC = CONFIG.get("mqtt", {}).get(
    "ack_topic",
    DEFAULT_ACK_TOPIC
)
DLQ_TOPIC = CONFIG.get("mqtt", {}).get(
    "dlq_topic",
    DEFAULT_DLQ_TOPIC
)


# ==========================================================
# HELPERS
# ==========================================================

def parse_payload(payload):
    """Valida e normaliza payload MQTT aceitando JSON direto ou encapsulado."""
    if payload is None:
        log.warning(
            "[AlexaBridge] Payload vazio"
        )
        return None
    if isinstance(payload, dict):
        data = payload
    else:
        payload = str(payload).strip()
        if payload == "":
            log.warning(
                "[AlexaBridge] Payload vazio"
            )
            return None
        try:
            data = json.loads(payload)
        except Exception as ex:
            log.warning(
                f"[AlexaBridge] Payload ignorado: {payload}"
            )
            log.error(
                f"[AlexaBridge] JSON inválido: {ex}"
            )
            return None
    if not isinstance(data, dict):
        log.warning(
            "[AlexaBridge] Payload fora do formato esperado"
        )
        return None
    if "content" in data:
        log.info(
            "[AlexaBridge] Payload encapsulado em content"
        )
        content = data["content"]
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except Exception:
                pass
        if isinstance(content, dict):
            data = content
    return data


def get_device_info(device):
    """Busca metadados do dispositivo normalizando a chave de entrada."""
    return DEVICE_INDEX.get(
        normalize_key(device)
    )


def normalize_command(command):
    """Transforma comando textual em identificador de cena amigável."""
    normalized = (
        safe_str(command)
        .replace(" ", "_")
        .replace("__", "_")
        .lower()
    )
    return normalized.strip("_")


def get_state(command):
    """Determina estado on/off com base em palavras-chave configuradas."""
    cmd = normalize_key(command)
    if cmd == "":
        return "off"
    for keyword in CONFIG.get("commands", {}).get(
        "off_keywords",
        []
    ):
        if normalize_key(keyword) in cmd:
            return "off"
    return "on"


def ensure_list(value):
    """Garante que um valor seja tratado como lista de tópicos."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def topic_matches(filter_topic, actual_topic):
    """Compara tópico real com filtro MQTT suportando + e #."""
    filter_levels = safe_str(filter_topic).split("/")
    topic_levels = safe_str(actual_topic).split("/")
    i = 0
    j = 0
    while i < len(filter_levels) and j < len(topic_levels):
        fl = filter_levels[i]
        tl = topic_levels[j]
        if fl == "#":
            return True
        if fl != "+" and fl != tl:
            return False
        i += 1
        j += 1
    if i < len(filter_levels) and filter_levels[i] == "#":
        return True
    return i == len(filter_levels) and j == len(topic_levels)


def is_allowed_topic(topic):
    """Valida se o tópico recebido está permitido na configuração."""
    input_topics = ensure_list(INPUT_TOPIC)
    if not input_topics:
        return False
    for allowed in input_topics:
        if topic_matches(allowed, topic):
            return True
    return False


def publish_event(topic, payload):
    """Publica evento normalizado no tópico MQTT de saída."""
    try:
        mqtt.publish(
            topic=topic,
            payload=json.dumps(payload),
            qos=0,
            retain=False
        )
        
        return True
    except Exception as ex:
        log.error(
            f"[AlexaBridge] Erro ao publicar em MQTT: {ex}"
        )
        return False


def build_correlation_id(data):
    """Gera correlation_id por mensagem para rastreabilidade ponta a ponta."""
    for key in [
        "correlation_id",
        "CORRELATION_ID",
        "request_id",
        "REQUEST_ID"
    ]:
        value = safe_str(data.get(key))
        if value != "":
            return value
    return str(uuid.uuid4())


def publish_dlq(topic, raw_payload, reason, correlation_id=""):
    """Publica mensagens inválidas em DLQ para análise e reprocessamento."""
    payload = {
        "reason": reason,
        "raw_payload": safe_str(raw_payload),
        "received_topic": safe_str(topic),
        "correlation_id": safe_str(correlation_id),
        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "bridge_version": VERSION
    }
    return publish_event(DLQ_TOPIC, payload)


def publish_ack(topic, correlation_id, status, detail=""):
    """Publica ACK de processamento para observabilidade do fluxo."""
    payload = {
        "status": safe_str(status),
        "detail": safe_str(detail),
        "received_topic": safe_str(topic),
        "correlation_id": safe_str(correlation_id),
        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "bridge_version": VERSION
    }
    return publish_event(ACK_TOPIC, payload)


def log_received(device, entity, room, command):
    """Registra no log os dados principais do comando recebido."""
    log.info(
        f"[AlexaBridge] "
        f"COMANDO='{command}' "
        f"ROOM='{room}' "
        f"ENTITY='{entity}' "
        f"DEVICE='{device}'"
    )


def log_published(topic, payload):
    """Registra no log o tópico e payload publicados."""
    log.info(
        f"[AlexaBridge] "
        f"Publicado em '{topic}'"
    )

    log.info(
        f"[AlexaBridge] "
        f"Payload: {json.dumps(payload, ensure_ascii=False)}"
    )


# ==========================================================
# RELOAD MANUAL
# ==========================================================

@service
def alexa_bridge_reload():
    """Recarrega configuração e índice de dispositivos em runtime."""
    global CONFIG
    global DEVICE_INDEX
    global INPUT_TOPIC
    global OUTPUT_TOPIC
    global ACK_TOPIC
    global DLQ_TOPIC
    CONFIG = load_config()
    DEVICE_INDEX = build_device_index(CONFIG)
    INPUT_TOPIC = CONFIG.get("mqtt", {}).get(
        "input_topic",
        DEFAULT_INPUT_TOPIC
    )
    OUTPUT_TOPIC = CONFIG.get("mqtt", {}).get(
        "output_topic",
        DEFAULT_OUTPUT_TOPIC
    )
    ACK_TOPIC = CONFIG.get("mqtt", {}).get(
        "ack_topic",
        DEFAULT_ACK_TOPIC
    )
    DLQ_TOPIC = CONFIG.get("mqtt", {}).get(
        "dlq_topic",
        DEFAULT_DLQ_TOPIC
    )
    log.info(
        "[AlexaBridge] Configuração recarregada"
    )
    log.info(
        f"[AlexaBridge] INPUT_TOPIC={INPUT_TOPIC} OUTPUT_TOPIC={OUTPUT_TOPIC} ACK_TOPIC={ACK_TOPIC} DLQ_TOPIC={DLQ_TOPIC}"
    )


@service
def alexa_wrapper_reload():
    """Alias legado para compatibilidade retroativa."""
    alexa_bridge_reload()


# ==========================================================
# MQTT TRIGGER
# ==========================================================

# Assina apenas o tópico de entrada configurado do bridge.
# Isso evita capturar payloads binários de outros fluxos MQTT (ex.: Frigate snapshot).
@mqtt_trigger(f"{INPUT_TOPIC}")
def alexa_bridge(
    topic=None,
    payload=None,
    qos=None
):
    """Processa mensagens MQTT de entrada e publica evento normalizado."""
    log.info(
        f"[AlexaBridge] "
        f"Mensagem recebida em '{topic}'"
    )
    if not is_allowed_topic(topic):
        return
    data = parse_payload(payload)
    if not data:
        publish_dlq(topic, payload, "invalid_payload")
        return
    correlation_id = build_correlation_id(data)
    device = safe_str(data.get("DEVICE"))
    command = safe_str(data.get("COMANDO"))
    origin = safe_str(data.get("ORIGIN", "alexa"))
    intent = safe_str(data.get("INTENT", ""))
    if not device:
        log.warning(
            "[AlexaBridge] DEVICE não informado"
        )
        publish_dlq(topic, payload, "missing_device", correlation_id)
        publish_ack(topic, correlation_id, "error", "missing_device")
        return
    if not command:
        log.warning(
            "[AlexaBridge] COMANDO não informado"
        )
        publish_dlq(topic, payload, "missing_command", correlation_id)
        publish_ack(topic, correlation_id, "error", "missing_command")
        return
    info = get_device_info(device)
    if not info:
        log.warning(
            f"[AlexaBridge] "
            f"Dispositivo não mapeado: {device}"
        )
        publish_dlq(topic, payload, "device_not_mapped", correlation_id)
        publish_ack(topic, correlation_id, "error", "device_not_mapped")
        return
    room = info["room"]
    entity = info["entity"]
    state = get_state(command)
    scene = normalize_command(command)
    if scene == "":
        scene = "default"
    result = {
        "scene": scene,
        "name": command,
        "source_entity": entity,
        "source_device_id": device,
        "destination": room,
        "state": state,
        "origin": origin,
        "intent": intent,
        "correlation_id": correlation_id,
        "received_topic": topic,
        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "bridge_version": VERSION
    }
    log_received(
        device,
        entity,
        room,
        command
    )
    published = publish_event(
        OUTPUT_TOPIC,
        result
    )
    if published:
        publish_ack(topic, correlation_id, "ok", "published")
    else:
        publish_ack(topic, correlation_id, "error", "publish_failed")
        publish_dlq(topic, payload, "publish_failed", correlation_id)
        return
    log_published(
        OUTPUT_TOPIC,
        result
    )