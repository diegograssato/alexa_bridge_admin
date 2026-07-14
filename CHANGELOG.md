# Changelog

All notable changes to **Alexa Bridge Admin** are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

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
