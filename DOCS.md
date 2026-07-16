# DOCS - AlexaBridgeAddon Configuration Matrix

This document lists supported configuration combinations for AlexaBridgeAddon.

## 1) Transport combinations

| transport.mqtt_enabled | transport.webhook_enabled | Status | Notes |
|---|---|---|---|
| true | true | Valid | Both listeners active |
| true | false | Valid | MQTT-only input |
| false | true | Valid | Webhook-only input |
| false | false | Invalid | Blocked by schema validation |

## 2) Integration type combinations by source

`integration.<source>.type` supports `mqtt` or `event_bus` for each source independently.

| integration.mqtt.type | integration.webhook.type | Valid | Output behavior |
|---|---|---|---|
| mqtt | mqtt | Valid | Both sources publish to MQTT output topics |
| mqtt | event_bus | Valid | MQTT source -> MQTT, Webhook source -> Event Bus |
| event_bus | mqtt | Valid | MQTT source -> Event Bus, Webhook source -> MQTT |
| event_bus | event_bus | Valid | Both sources publish to Event Bus |

## 3) Required fields by integration type

### 3.1 type = mqtt

Required fields:
- `integration.<source>.mqtt.output_topic`
- `integration.<source>.mqtt.ack_topic`
- `integration.<source>.mqtt.dlq_topic`

### 3.2 type = event_bus

Required fields:
- `integration.<source>.event_bus.event_name`

Format:
- `event_name` accepts `alexa_command` or dotted names like `alexa_bridge.command.webhook`

## 4) Webhook settings

- Listener registration uses only `webhook.id`.
- Changing `webhook.id` triggers automatic `pyscript.reload` on save.
- If auto reload fails, UI/API reports failure and requires manual reload.

## 5) Event Bus payload metadata

When publishing to Event Bus, bridge adds:
- `provided_by`: `mqtt` or `webhook`
- `transport_source`: `mqtt` or `webhook`

## 6) Field validation summary

### Transport
- `transport.mqtt_enabled`: required boolean
- `transport.webhook_enabled`: required boolean
- At least one must be `true`

### MQTT root
- `mqtt.input_topic`: required, topic format validation

### Webhook
- `webhook.id`: required key, optional value, if set must match allowed pattern and cannot contain `/`

### Integration
- `integration.mqtt` and `integration.webhook`: required objects
- `integration.<source>.type`: required, must be `mqtt` or `event_bus`
- Type-specific required fields enforced as described above
