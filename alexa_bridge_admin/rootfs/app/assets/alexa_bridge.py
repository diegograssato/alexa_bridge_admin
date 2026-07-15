import json
import hmac
import time
import uuid
import homeassistant.util.yaml as yaml_util
from base64 import urlsafe_b64encode
from hashlib import sha256
from datetime import datetime
from typing import Any
from cryptography.fernet import Fernet, InvalidToken

CONFIG_FILE = "/config/pyscript/alexa_bridge.yaml"

VERSION = "3.3.0"

# ----------------------------------------------------------
# Idempotência — cache de correlation_ids já processados
# Estrutura: {correlation_id: timestamp_unix}
# TTL padrão de 300 s (5 min); entradas expiradas são limpas
# na recepção de cada nova mensagem.
# ----------------------------------------------------------
_IDEMPOTENCY_TTL_SECONDS = 300
_processed_ids: dict[str, float] = {}

# ----------------------------------------------------------
# Retry — publicação MQTT com backoff exponencial
# ----------------------------------------------------------
_PUBLISH_MAX_RETRIES = 3
_PUBLISH_INITIAL_DELAY = 0.2  # segundos

# ----------------------------------------------------------
# Tipos de mensagem aceitos em TYPE (sempre uppercase)
# ----------------------------------------------------------
VALID_TYPES = frozenset({
    "TYPING",
    "PASSWORD",
    "TEMPERATURE",
    "NOTIFICATION",
    "COMMAND",
})

DEFAULT_INPUT_TOPIC = "alexa/command"
DEFAULT_OUTPUT_TOPIC = "homeassistant/voice/command"
DEFAULT_ACK_TOPIC = "homeassistant/voice/ack"
DEFAULT_DLQ_TOPIC = "homeassistant/voice/dlq"
DEFAULT_OFF_KEYWORDS = ["desliga", "desligar", "turn off"]
MAX_WEBHOOK_IDS = 20

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
# SECRET
# ==========================================================
def get_secret():
    return CONFIG.get(
        "security",
        {}
    ).get(
        "secret",
        ""
    )


def _build_fernet():
    """Deriva chave Fernet estável a partir de security.secret."""
    secret = get_secret()
    if not secret:
        return None
    key = urlsafe_b64encode(sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _extract_signing_base(outer: Any) -> Any:
    """Normaliza a base de assinatura para envelopes plaintext e cifrados."""
    if not isinstance(outer, dict):
        return outer

    if "ciphertext" in outer:
        return {
            "enc": safe_str(outer.get("enc", "fernet-v1")),
            "ciphertext": safe_str(outer.get("ciphertext", "")),
        }

    content = outer.get("content", {})
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            pass
    return content

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


def extract_webhook_ids(config):
    """Extrai, normaliza e limita IDs de webhook (máx. 20)."""
    webhook_cfg = config.get("webhook", {})
    raw_ids = []

    if isinstance(webhook_cfg, dict):
        ids = webhook_cfg.get("ids")
        if isinstance(ids, list):
            raw_ids = ids
        else:
            legacy_id = webhook_cfg.get("id", "")
            if safe_str(legacy_id):
                raw_ids = [legacy_id]

    normalized = []
    seen = set()
    for item in raw_ids:
        webhook_id = safe_str(item)
        if not webhook_id or "/" in webhook_id:
            continue
        if webhook_id in seen:
            continue
        seen.add(webhook_id)
        normalized.append(webhook_id)
        if len(normalized) >= MAX_WEBHOOK_IDS:
            break
    return normalized


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
SECURITY = CONFIG.get("security", {})

# ----------------------------------------------------------
# Webhook — registrado automaticamente para cada webhook.id/webhook.ids.
# O @webhook_trigger é registrado apenas no boot do PyScript;
# para alterar os ids é preciso recarregar o PyScript completo.
# ----------------------------------------------------------
WEBHOOK_IDS = extract_webhook_ids(CONFIG)

log.info(
    f"[AlexaBridge] Seguranca: enabled={SECURITY.get('enabled', False)}"
)
if WEBHOOK_IDS:
    log.info(f"[AlexaBridge] Webhook ativo: ids={WEBHOOK_IDS}")
else:
    log.info("[AlexaBridge] Webhook inativo (webhook.id/webhook.ids não configurado)")


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

def verify_hmac(raw_payload, correlation_id=""):
    """Verifica assinatura HMAC-SHA256 do payload quando presente.

    Aceita payloads sem assinatura (retrocompatível) mas rejeita payloads com
    assinatura inválida. Usa hmac.compare_digest para prevenir timing attacks.
    Retorna True se válida, ausente ou segurança desabilitada.
    Retorna False se assinatura presente e inválida.
    """
    security = CONFIG.get("security", {})
    if not security.get("enabled", False):
        return True

    # Parse mínimo apenas para extrair signature + content
    if isinstance(raw_payload, dict):
        outer = raw_payload
    else:
        try:
            outer = json.loads(safe_str(raw_payload))
        except Exception:
            return True  # será tratado por parse_payload

    if not isinstance(outer, dict) or "signature" not in outer:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [HMAC] "
            f"Payload sem assinatura — aceito (modo retrocompatível)"
        )
        return True

    received_sig = safe_str(outer.get("signature", ""))
    signing_base = _extract_signing_base(outer)

    secret = get_secret()
    if not secret:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [HMAC] "
            f"Secret não configurado — verificação ignorada"
        )
        return True

    expected = hmac.new(
        secret.encode("utf-8"),
        json.dumps(signing_base, sort_keys=True).encode("utf-8"),
        sha256
    ).hexdigest()

    if not hmac.compare_digest(received_sig, expected):
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [HMAC] "
            f"Assinatura inválida — payload rejeitado"
        )
        return False

    log.info(f"[{correlation_id}] [AlexaBridge] [HMAC] Assinatura válida")
    return True


def decrypt_payload(data, correlation_id=""):
    """Descriptografa envelope Fernet quando presente, mantendo retrocompatibilidade.

    Formatos aceitos:
    - Plaintext legado: {"content": {...}} ou payload direto {...}
    - Cifrado: {"enc":"fernet-v1","ciphertext":"..."}
    """
    if not isinstance(data, dict):
        return data

    if "ciphertext" not in data:
        return data

    enc = safe_str(data.get("enc", "fernet-v1"))
    if enc not in {"fernet-v1", "fernet"}:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [ENC] Algoritmo não suportado: '{enc}'"
        )
        return None

    ciphertext = safe_str(data.get("ciphertext", ""))
    if not ciphertext:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [ENC] ciphertext vazio"
        )
        return None

    fernet = _build_fernet()
    if fernet is None:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [ENC] security.secret ausente para descriptografia"
        )
        return None

    try:
        plain = fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        parsed = json.loads(plain)
        if not isinstance(parsed, dict):
            log.warning(
                f"[{correlation_id}] [AlexaBridge] [ENC] conteúdo descriptografado inválido"
            )
            return None
        log.info(f"[{correlation_id}] [AlexaBridge] [ENC] Payload descriptografado")
        return parsed
    except InvalidToken:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] [ENC] token inválido (secret incorreto ou payload adulterado)"
        )
        return None
    except Exception as ex:
        log.error(
            f"[{correlation_id}] [AlexaBridge] [ENC] falha ao descriptografar: {ex}"
        )
        return None

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


def publish_event(topic, payload, correlation_id=""):
    """Publica evento normalizado com retry e backoff exponencial."""
    delay = _PUBLISH_INITIAL_DELAY
    last_ex = None
    for attempt in range(1, _PUBLISH_MAX_RETRIES + 1):
        try:
            mqtt.publish(
                topic=topic,
                payload=json.dumps(payload),
                qos=0,
                retain=False
            )
            if attempt > 1:
                log.info(
                    f"[{correlation_id}] [AlexaBridge] Publicação bem-sucedida na tentativa {attempt}"
                )
            return True
        except Exception as ex:
            last_ex = ex
            log.warning(
                f"[{correlation_id}] [AlexaBridge] Tentativa {attempt}/{_PUBLISH_MAX_RETRIES} falhou: {ex}"
            )
            if attempt < _PUBLISH_MAX_RETRIES:
                time.sleep(delay)
                delay *= 2
    log.error(
        f"[{correlation_id}] [AlexaBridge] Todas as {_PUBLISH_MAX_RETRIES} tentativas falharam: {last_ex}"
    )
    return False


def _purge_expired_ids() -> None:
    """Remove correlation_ids expirados do cache de idempotência."""
    now = time.time()
    expired = [
        cid for cid, ts in _processed_ids.items()
        if now - ts > _IDEMPOTENCY_TTL_SECONDS
    ]
    for cid in expired:
        del _processed_ids[cid]


def _is_duplicate(correlation_id: str) -> bool:
    """Retorna True se a mensagem já foi processada dentro do TTL."""
    _purge_expired_ids()
    if correlation_id in _processed_ids:
        log.warning(
            f"[AlexaBridge] Mensagem duplicada ignorada: correlation_id={correlation_id}"
        )
        return True
    return False


def _mark_processed(correlation_id: str) -> None:
    """Registra correlation_id como processado com timestamp atual."""
    _processed_ids[correlation_id] = time.time()


def _write_last_event(agent: str, msg_type: str, device: str, room: str, correlation_id: str) -> None:
    """Grava sidecar JSON com dados do último evento processado.

    O arquivo fica ao lado do alexa_bridge.yaml e é lido pela interface
    admin para exibir 'Último Agent' e outros KPIs em tempo real.
    """
    try:
        from pathlib import Path as _Path
        sidecar = _Path(CONFIG_FILE).parent / "_bridge_last_event.json"
        entry = {
            "agent":          agent,
            "type":           msg_type,
            "device":         device,
            "room":           room,
            "correlation_id": correlation_id,
            "time":           datetime.now().isoformat(),
        }
        sidecar.write_text(json.dumps(entry), encoding="utf-8")
    except Exception as ex:
        log.warning(f"[AlexaBridge] Erro ao gravar last event: {ex}")


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
    return publish_event(DLQ_TOPIC, payload, correlation_id)


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
    return publish_event(ACK_TOPIC, payload, correlation_id)


def log_received(device, entity, room, command, agent="", msg_type="", correlation_id=""):
    """Registra no log os dados principais do comando recebido."""
    log.info(
        f"[{correlation_id}] [AlexaBridge] [RECEIVED] "
        f"TYPE='{msg_type}' VALUE='{command}' ROOM='{room}' "
        f"ENTITY='{entity}' DEVICE='{device}' AGENT='{agent}'"
    )


def log_published(topic, payload, correlation_id=""):
    """Registra no log o tópico e payload publicados."""
    log.info(
        f"[{correlation_id}] [AlexaBridge] [PUBLISHED] "
        f"Tópico: '{topic}'"
    )
    log.info(
        f"[{correlation_id}] [AlexaBridge] [PUBLISHED] "
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
    global SECURITY
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
    SECURITY = CONFIG.get("security", {})
    # Nota: WEBHOOK_IDS não é recarregado aqui porque
    # o @webhook_trigger só é registrado no boot. Para alterar os webhook IDs,
    # recarregue o PyScript completo.
    log.info(
        "[AlexaBridge] Configuração recarregada"
    )
    log.info(
        f"[AlexaBridge] INPUT_TOPIC={INPUT_TOPIC} OUTPUT_TOPIC={OUTPUT_TOPIC} ACK_TOPIC={ACK_TOPIC} DLQ_TOPIC={DLQ_TOPIC}"
    )
    log.info(
        f"[AlexaBridge] Segurança: enabled={SECURITY.get('enabled', False)}"
    )


@service
def alexa_wrapper_reload():
    """Alias legado para compatibilidade retroativa."""
    alexa_bridge_reload()


# ==========================================================
# NÚCLEO DE PROCESSAMENTO (compartilhado por MQTT e Webhook)
# ==========================================================

def _process_command(source, raw_payload, topic, correlation_id_hint=None, hmac_verified=False):
    """Processa um comando recebido de qualquer fonte (MQTT ou Webhook).

    Args:
        source:              Origem ('mqtt' ou 'webhook') para logging.
        raw_payload:         Payload bruto recebido.
        topic:               Tópico usado em ACK/DLQ ('webhook' para origem HTTP).
        correlation_id_hint: correlation_id pré-extraído (usado pelo webhook).
        hmac_verified:       True se a assinatura já foi verificada pelo caller.
    """
    data = parse_payload(raw_payload)
    if not data:
        publish_dlq(topic, raw_payload, "invalid_payload")
        return

    correlation_id = correlation_id_hint or build_correlation_id(data)
    log.info(f"[{correlation_id}] [AlexaBridge] [{source.upper()}] Payload recebido")

    if not hmac_verified:
        if not verify_hmac(raw_payload, correlation_id):
            publish_dlq(topic, raw_payload, "invalid_signature", correlation_id)
            publish_ack(topic, correlation_id, "error", "invalid_signature")
            return

    data = decrypt_payload(data, correlation_id)
    if not data:
        publish_dlq(topic, raw_payload, "decrypt_failed", correlation_id)
        publish_ack(topic, correlation_id, "error", "decrypt_failed")
        return

    # --- Idempotência: descarta reprocessamento dentro do TTL ---
    if _is_duplicate(correlation_id):
        return

    device   = safe_str(data.get("DEVICE"))
    raw_type = data.get("TYPE")
    msg_type = safe_str(raw_type)
    value    = safe_str(data.get("VALUE"))
    agent    = safe_str(data.get("AGENT") or data.get("ORIGIN", ""))
    origin   = safe_str(data.get("ORIGIN") or data.get("ORIGEM", "alexa"))
    intent   = safe_str(data.get("INTENT", ""))
    command  = value

    if raw_type is not None:
        normalized_type = safe_str(raw_type).upper()
        if normalized_type not in VALID_TYPES:
            log.warning(
                f"[{correlation_id}] [AlexaBridge] TYPE inválido: '{raw_type}'. "
                f"Aceitos: {sorted(VALID_TYPES)}"
            )
            publish_dlq(topic, raw_payload, "invalid_type", correlation_id)
            publish_ack(topic, correlation_id, "error", "invalid_type")
            return
        msg_type = normalized_type

    if not device:
        log.warning(f"[{correlation_id}] [AlexaBridge] DEVICE não informado")
        publish_dlq(topic, raw_payload, "missing_device", correlation_id)
        publish_ack(topic, correlation_id, "error", "missing_device")
        return

    if not command:
        log.warning(f"[{correlation_id}] [AlexaBridge] VALUE não informado")
        publish_dlq(topic, raw_payload, "missing_command", correlation_id)
        publish_ack(topic, correlation_id, "error", "missing_command")
        return

    info = get_device_info(device)
    if not info:
        log.warning(
            f"[{correlation_id}] [AlexaBridge] "
            f"Dispositivo não mapeado: '{device}'"
        )
        publish_dlq(topic, raw_payload, "device_not_mapped", correlation_id)
        publish_ack(topic, correlation_id, "error", "device_not_mapped")
        return

    room   = info["room"]
    entity = info["entity"]
    state  = get_state(command)
    scene  = normalize_command(command)
    if scene == "":
        scene = "default"

    result = {
        "type":             msg_type,
        "scene":            scene,
        "name":             command,
        "value":            value,
        "agent":            agent,
        "source_entity":    entity,
        "source_device_id": device,
        "destination":      room,
        "state":            state,
        "origin":           origin,
        "intent":           intent,
        "correlation_id":   correlation_id,
        "received_topic":   topic,
        "time":             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bridge_version":   VERSION
    }

    log_received(device, entity, room, command, agent=agent, msg_type=msg_type, correlation_id=correlation_id)

    published = publish_event(OUTPUT_TOPIC, result, correlation_id)
    if published:
        _mark_processed(correlation_id)
        _write_last_event(agent, msg_type, device, room, correlation_id)
        publish_ack(topic, correlation_id, "ok", "published")
    else:
        publish_ack(topic, correlation_id, "error", "publish_failed")
        publish_dlq(topic, raw_payload, "publish_failed", correlation_id)
        return

    log_published(OUTPUT_TOPIC, result, correlation_id)


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
    """Recebe mensagens MQTT e delega o processamento para _process_command."""
    log.info(
        f"[AlexaBridge] "
        f"Mensagem recebida em '{topic}'"
    )
    if not is_allowed_topic(topic):
        return
    _process_command("mqtt", payload, topic)


# ==========================================================
# WEBHOOK TRIGGER (ativo para cada webhook.id/webhook.ids configurado no YAML)
# ==========================================================

def _handle_webhook(payload=None, headers=None, webhook_id=""):
    """Processa requisição de webhook (compartilhado por todos os IDs)."""
    correlation_id = str(uuid.uuid4())
    log.info(
        f"[{correlation_id}] [AlexaBridge] [WEBHOOK] Requisição recebida id='{webhook_id}'"
    )

    if SECURITY.get("enabled", False):
        received_sig = safe_str((headers or {}).get("X-Signature", ""))
        if not received_sig:
            log.warning(
                f"[{correlation_id}] [AlexaBridge] [WEBHOOK] "
                f"Header X-Signature ausente — rejeitado"
            )
            return

        secret = get_secret()
        if not secret:
            log.warning(
                f"[{correlation_id}] [AlexaBridge] [WEBHOOK] "
                f"Secret não configurado — verificando sem autenticação"
            )
        else:
            # Extrai base de assinatura (content plaintext ou envelope cifrado).
            try:
                outer = json.loads(safe_str(payload))
                signing_base = _extract_signing_base(outer)
            except Exception:
                signing_base = payload
            expected = hmac.new(
                secret.encode("utf-8"),
                json.dumps(signing_base, sort_keys=True).encode("utf-8"),
                sha256
            ).hexdigest()

            if not hmac.compare_digest(received_sig, expected):
                log.warning(
                    f"[{correlation_id}] [AlexaBridge] [WEBHOOK] "
                    f"Assinatura inválida — rejeitado"
                )
                return

            log.info(
                f"[{correlation_id}] [AlexaBridge] [WEBHOOK] Assinatura válida"
            )

    _process_command(
        "webhook",
        payload,
        "webhook",
        correlation_id_hint=correlation_id,
        hmac_verified=True
    )


for _webhook_id in WEBHOOK_IDS:
    @webhook_trigger(_webhook_id)
    def _alexa_webhook(payload=None, headers=None, _webhook_id=_webhook_id):
        """Recebe comandos via Webhook HTTP e delega para _process_command.

        Verifica a assinatura HMAC-SHA256 no header X-Signature antes de
        processar. A assinatura deve ser computada sobre o payload body inteiro
        usando o mesmo secret configurado em security.secret.
        """
        _handle_webhook(payload=payload, headers=headers, webhook_id=_webhook_id)