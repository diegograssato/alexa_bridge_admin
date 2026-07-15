# Changelog

All notable changes to **Alexa Bridge Admin** are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [0.6.0] — 2026-07-15

### Added
- **Confidencialidade ponta a ponta**: suporte a payload cifrado com `Fernet` entre Skill e bridge (`security.encrypt_payload`).
- **Envelope cifrado**: novo formato `{ "enc": "fernet-v1", "ciphertext": "...", "signature": "..." }`.
- **Validação de schema** para `security.encrypt_payload` no backend de configuração.
- **Controle na interface admin**: opção para ativar/desativar cifragem de payload.

### Changed
- Verificação HMAC atualizada para assinar/verificar a mesma base em payload plaintext e cifrado.
- Template de configuração `alexa_bridge.yaml` atualizado com `security.encrypt_payload`.

### Fixed
- Fluxo de processamento agora rejeita payload cifrado inválido com rastreabilidade (`decrypt_failed`).

### Tests
- Suíte atualizada e validada com sucesso (`77 passed`).

## [0.5.0] — 2026-07-15

### Added
- **Webhook multi-ID**: suporte a `webhook.ids` (até 20 IDs) no bridge PyScript e na interface admin.
- **UX de configuração**: cadastro de Webhook IDs no padrão input+botão com listagem em tabela.
- **Validações com modal padronizado**: mensagens de limite/duplicidade usando o mesmo modal da aplicação.
- **Limites operacionais**:
  - Máximo de 5 aliases por entidade no modal de cadastro/edição.
  - Máximo de 10 backups por dia na API (`POST /api/backups`).
- **Retenção automática de dados**:
  - Backups: remove arquivos com mais de 30 dias ao criar novo backup, preservando ao menos 1 backup.
  - Auditoria: remove eventos com mais de 30 dias ao inserir novo evento, preservando ao menos 1 evento por `action`.

### Changed
- Fluxo de Webhook simplificado: remove toggle `webhook.enabled` e ativa listeners automaticamente quando houver `webhook.id`/`webhook.ids`.
- UI de aliases migrada de pills para tabela com ações e confirmação de remoção.
- Mensagens de erro de backup (incluindo limite diário) agora também exibidas em modal padronizado.

### Fixed
- Correção de consistência de assinatura HTTP (`X-Signature`) para evitar divergência entre conteúdo assinado e body enviado.

### Tests
- Ampliação da suíte unitária para retenção e limite diário de backups.
- Execução da suíte completa com sucesso (`76 passed`).

## [0.4.0] — 2026-07-15

### Added
- **Assinatura HMAC-SHA256** (`verify_hmac`): autentica a origem do payload antes de processar. Usa `hmac.compare_digest` para prevenir timing attacks. Payloads sem assinatura são aceitos no modo retrocompatível.
- **Webhook HTTP trigger** opcional (`@webhook_trigger`): permite receber comandos via HTTP POST com verificação de assinatura no header `X-Signature`. Registrado condicionalmente via `webhook.enabled + webhook.id` no YAML.
- Seção **`webhook`** no `alexa_bridge.yaml` e na interface admin (aba Configuração): campos `enabled` e `id`.
- Função `_process_command(source, raw_payload, topic, ...)`: núcleo de processamento compartilhado entre trigger MQTT e Webhook, eliminando duplicidade.
- Validação de schema para `webhook.enabled` e `webhook.id` no `config_service.py`.
- DLQ reason `invalid_signature` para payloads com assinatura inválida.
- Bridge script version: `3.3.0`.

### Changed
- `alexa_bridge()` MQTT handler simplificado: agora delega para `_process_command`.
- Interface admin — aba Configuração: inclui campos de Webhook.
- Defaults do `config_service.py` incluem a seção `webhook`.
- READMEs atualizados: seções de Segurança (HMAC), Webhook e motivos de DLQ.

---

## [0.3.0] — 2026-07-15

### Added
- **Rastreabilidade completa via `correlation_id`**: propagado por `decrypt_payload`, `publish_event`, `log_received` e `log_published`.
- `build_correlation_id` executado antes de `decrypt_payload` para garantir o ID em todos os logs de descriptografia.
- Prefixo `[{correlation_id}] [TAG]` em todos os logs do fluxo MQTT.
- `_is_duplicate` e `_mark_processed` passam a logar com `correlation_id`.

### Changed
- `log_received` e `log_published` aceitam `correlation_id` como parâmetro.
- `publish_event` aceita `correlation_id` para logs de retry/erro.
- `publish_dlq` e `publish_ack` propagam `correlation_id` para `publish_event`.

---

## [0.2.9] — 2026-07-14

### Added
- Persistência do KPI **Último Reload** recuperado do histórico de auditoria.
- Persistência do KPI **Último Agent** via endpoint `/api/bridge/last-event` e sidecar de evento no bridge.
- Endpoint GET `/api/bridge/last-event` na API de administração.
- Helper `write_last_event` / `get_last_event` no `ConfigService`.

### Changed
- `_write_last_event` chamado no bridge após publish bem-sucedido.
- Dashboard agora inicializa KPIs corretamente mesmo após reload da página.

---

## [0.2.8] — 2026-07-14

### Added
- Ícone SVG de ponte inline no header da interface web.
- Seção **Segurança** na aba Configuração: ativar criptografia de campos, campo `secret` e seleção de `encrypted_fields` (VALUE, TYPE, DEVICE, AGENT, ORIGIN, INTENT).

### Changed
- Favicon inline (SVG base64) em todas as páginas da interface.
- Grid do Dashboard ampliado para 5 colunas para acomodar o card **Último Agent**.

---

## [0.2.7] — 2026-07-14

### Added
- **Segurança**: seção `security` no `alexa_bridge.yaml` com suporte a criptografia Fernet de campos do payload MQTT (`enabled`, `secret`, `encrypted_fields`).
- `VALID_TYPES`: validação do campo `TYPE` — aceita apenas `COMMAND`, `TYPING`, `PASSWORD`, `TEMPERATURE`, `NOTIFICATION` (sempre uppercase). Payload com TYPE inválido vai para DLQ com razão `invalid_type`.
- Novo campo **`AGENT`** no payload de entrada e saída: nome fonético do agente/skill Alexa.
- Novo card KPI **🎤 Último Agent** no Dashboard.
- Defaults automáticos para `security` no `config_service.py`.
- Validação de schema da seção `security` (tipo dos campos, secret obrigatório quando enabled).
- Dependência `cryptography>=42.0` adicionada ao grupo `dev` do `pyproject.toml`.

### Changed
- **Estrutura do payload MQTT**:
  - Campo `COMANDO` **removido** — substituído por `TYPE` (tipo da mensagem) e `VALUE` (valor do comando).
  - `ORIGIN` agora aceito como fallback de `AGENT`.
- `log_received()` atualizado para incluir `TYPE`, `VALUE` e `AGENT` nos logs.
- Payload de saída (`output_topic`) agora inclui os campos `type`, `value` e `agent`.
- `alexa_bridge.py` carrega e loga a configuração `security` no boot e no reload.
- Correção de bugs na leitura de `TYPE`/`AGENT`/`ORIGIN` (chave duplicada nos fallbacks).
- Testes de retrocompatibilidade com `COMANDO` removidos.

### Fixed
- Fallback `data.get("TYPE")` duplicado em vez de `data.get("COMANDO")` — corrigido para uso exclusivo de `TYPE`.
- `agent` e `origin` usavam a mesma chave como fallback — corrigido.

---

## [0.2.6] — 2026-07-14

### Added
- **Idempotência**: cache TTL (300 s) de `correlation_id` processados em `alexa_bridge.py` — mensagens duplicadas são descartadas automaticamente.
- **Retry com backoff exponencial** na publicação MQTT: 3 tentativas com delays `0.2 s → 0.4 s → 0.8 s`.
- Suite de **testes unitários** (`tests/unit/test_bridge.py`): 36 casos cobrindo `parse_payload`, `build_device_index`, `get_state`, `normalize_command`, `topic_matches`, `build_correlation_id`, idempotência.
- Suite de **testes de integração** (`tests/integration/test_bridge_flow.py`): 18 casos cobrindo fluxo feliz, rejeições (DLQ), idempotência end-to-end e retry.
- Ambiente de desenvolvimento local sem Home Assistant: `dev/run_dev.sh`, `dev/docker-compose.dev.yml` e `dev/alexa_bridge.yaml` (fixture).
- Variável de ambiente `DEV_MODE=true` para stub do `ReloadService` sem Supervisor.
- **Favicon** SVG de ponte inline (base64) no `index.html`.
- **KPI Cômodos** no Dashboard.
- Seção **"Implementações e Cenários de Uso"** no README com diagramas Mermaid (3 cenários + 4 exemplos de automação HA).

### Changed
- Layout da interface redesenhado: tema dark azul-marinho neutro (`#1b1f2b`/`#1f2330`), tabs e botões com hover consistente, tabela com toolbar (Total + Itens por página), status bars tonais.
- Versão do bridge PyScript: `3.2.0 → 3.3.0`.
- `VERSION` no `alexa_bridge.py` do `alexaBridge/` sincronizada com a versão do addon.

---

## [0.2.5] — 2026-07-14 *(first commit baseline)*

### Added
- Backend FastAPI com rotas: `config`, `devices`, `backup`, `audit`, `diagnostics`, `reload`, `ha`.
- Frontend single-page com abas: Dashboard, Configuração, Entidades, Raw YAML, Backup/Restore, Diagnóstico, Auditoria.
- `ConfigService` com CRUD de devices, backup/restore, validação de schema YAML e auditoria.
- `ReloadService` para acionar `pyscript.alexa_bridge_reload` via Supervisor API.
- `alexa_bridge.py` PyScript: parser de payload, índice de aliases, publicação em output/ack/dlq topics.
- Testes unitários do `ConfigService`.
- Dockerfile baseado em `ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.22`.
- `repository.yaml` para instalação como add-on do Home Assistant.
