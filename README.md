# Alexa Bridge (PyScript)

Bridge em PyScript para integrar Alexa Skill e Home Assistant via MQTT.

O fluxo recebe mensagens da skill em um topico de entrada, resolve dispositivo por alias no YAML e publica evento normalizado para automacoes do Home Assistant.

Este repositorio tambem contem o addon AlexaBridge Admin, que fornece interface web para operar o YAML e o ciclo de runtime do bridge.

## Visao Geral

- Entrada MQTT: mqtt.input_topic
- Saida MQTT principal: mqtt.output_topic
- Saida MQTT de confirmacao: mqtt.ack_topic
- Saida MQTT de erro: mqtt.dlq_topic
- Mapeamento de dispositivos: secao devices no YAML
- Reload de configuracao em runtime: servico pyscript.alexa_bridge_reload
- Versao atual do wrapper: 3.2.0

## Estrutura do Projeto

- repository.yaml: metadata do repositorio de addons
- alexa_bridge_admin/: addon instalavel Home Assistant
  - config.yaml: metadata do addon
  - Dockerfile
  - rootfs/app/: backend FastAPI + frontend
  - rootfs/app/assets/alexa_bridge.py: template do script PyScript
  - rootfs/app/assets/alexa_bridge.yaml: template do YAML padrao
- tests/: testes unitarios do backend do addon

Arquivos operacionais do bridge (alvo final no Home Assistant):

- alexa_bridge.py: script PyScript principal
- alexa_bridge.yaml: configuracao do bridge

## Requisitos

- Home Assistant com MQTT configurado
- PyScript instalado e habilitado
- Arquivo de configuracao no caminho:
  - /config/pyscript/alexa_bridge.yaml

Observacoes:

- O script usa um unico arquivo de configuracao.
- Se voce estiver usando alexa.bridge.yaml, copie/renomeie para alexa_bridge.yaml em /config/pyscript.
- O addon tenta auto-provisionar alexa_bridge.py e alexa_bridge.yaml no startup quando ausentes.

## Instalacao

1. Adicione o repositorio do addon no Home Assistant.
2. Instale AlexaBridge Admin.
3. Abra o addon via Ingress.
4. Verifique no diagnostico se bridge_script_setup e bridge_yaml_setup estao ok.
5. Execute o servico pyscript.alexa_bridge_reload para aplicar configuracao em runtime.

## Configuracao YAML

Exemplo:

```yaml
mqtt:
  input_topic: alexa/command
  output_topic: homeassistant/voice/command
  ack_topic: homeassistant/voice/ack
  dlq_topic: homeassistant/voice/dlq

commands:
  off_keywords:
    - desliga
    - desligar
    - turn off

devices:
  sala:
    media_player.echo_show:
      aliases:
        - media_player.echo_show
        - amzn1.ask.device.EXEMPLO
```

Defaults aplicados automaticamente quando nao configurado:

- mqtt.input_topic = alexa/command
- mqtt.output_topic = homeassistant/voice/command
- mqtt.ack_topic = homeassistant/voice/ack
- mqtt.dlq_topic = homeassistant/voice/dlq
- commands.off_keywords = [desliga, desligar, turn off]

## Contrato de Entrada MQTT

Mensagem esperada:

```json
{
  "DEVICE": "media_player.echo_show",
  "COMANDO": "ligar tv",
  "ORIGEM": "alexa",
  "INTENT": "CustomIntent",
  "correlation_id": "req-123"
}
```

Tambem aceita envelope com content:

```json
{
  "content": {
    "DEVICE": "media_player.echo_show",
    "COMANDO": "desliga tv",
    "ORIGEM": "alexa",
    "INTENT": "CustomIntent"
  }
}
```

## Contrato de Saida Principal

Publicado em mqtt.output_topic:

```json
{
  "scene": "desliga_tv",
  "name": "desliga tv",
  "source_entity": "media_player.echo_show",
  "source_device_id": "media_player.echo_show",
  "destination": "sala",
  "state": "off",
  "origin": "alexa",
  "intent": "CustomIntent",
  "correlation_id": "req-123",
  "received_topic": "alexa/command",
  "time": "2026-07-13 21:00:00",
  "wrapper_version": "3.2.0"
}
```

Regras:

- state = off quando COMANDO contem qualquer termo de commands.off_keywords
- caso contrario, state = on
- correlation_id vem do payload de entrada quando presente
- se correlation_id nao vier, o wrapper gera um UUID

## Contrato de ACK

Publicado em mqtt.ack_topic:

```json
{
  "status": "ok",
  "detail": "published",
  "received_topic": "alexa/command",
  "correlation_id": "req-123",
  "time": "2026-07-13 21:00:00",
  "wrapper_version": "3.2.0"
}
```

Cenarios de erro usam status = error e detail com o motivo.

## Contrato de DLQ

Publicado em mqtt.dlq_topic quando ocorre rejeicao de entrada:

```json
{
  "reason": "missing_device",
  "raw_payload": "{...}",
  "received_topic": "alexa/command",
  "correlation_id": "req-123",
  "time": "2026-07-13 21:00:00",
  "wrapper_version": "3.2.0"
}
```

Motivos atuais:

- invalid_payload
- missing_device
- missing_command
- device_not_mapped
- publish_failed

## Interface AlexaBridge Admin

Abas da interface:

- Dashboard
- Configuracao
- Entidades
- Raw YAML
- Backup / Restore
- Diagnostico
- Auditoria

Recursos principais:

- Entidades com CRUD via pop-up
- aliases multiplos por dispositivo
- autocomplete de entity_id para media_player.*
- importacao/exportacao de devices em YAML
- paginacao e filtros
- editor Raw YAML com Recarregar, Validar schema e Salvar
- Backup / Restore com criar, baixar, restaurar e remover
- Auditoria de operacoes
- Diagnostico com status de setup do script e do YAML

## Comportamento de Runtime

- O trigger MQTT escuta o topico configurado em mqtt.input_topic no boot do script.
- O filtro interno valida se a mensagem recebida pertence aos topicos permitidos.
- Em alteracao de YAML, execute pyscript.alexa_bridge_reload para recarregar mapeamentos e topicos em memoria.
- Se alterar mqtt.input_topic, recarregue o PyScript para re-assinar o novo topico de entrada.

## Operacao e Troubleshooting

Verifique logs para:

- erro de leitura YAML
- payload invalido
- dispositivo nao mapeado
- erro de publicacao MQTT

Acoes operacionais:

1. Alterou YAML: execute pyscript.alexa_bridge_reload.
2. Alterou estrutura do script: recarregue o PyScript.
3. Falha de processamento: inspecione mqtt.dlq_topic e mqtt.ack_topic.
4. Falha no reload pela UI: confira aba Auditoria e o detalhe de erro HTTP.

## Seguranca e Boas Praticas

- Restrinja ACL dos topicos MQTT por produtor e consumidor.
- Evite dados sensiveis em payload e logs.
- Padronize correlation_id para rastreabilidade fim a fim.
- Use monitoramento de erros no topico de DLQ.

## Desenvolvimento local

```bash
cd AlexaBridgeAddon
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn alexa_bridge_admin.rootfs.app.main:app --reload --port 8099
```

## Testes

```bash
cd AlexaBridgeAddon
pytest
```

## Roadmap Recomendado

- Idempotencia por correlation_id/request_id para evitar reprocessamento.
- Retry com backoff na publicacao MQTT em falhas transientes.
- Testes unitarios para parser, mapeamento e regras de estado.
- Testes de integracao para fluxo completo entrada, saida, ack e dlq.
