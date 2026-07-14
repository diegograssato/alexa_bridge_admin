#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_dev.sh — Roda o Alexa Bridge Admin localmente, sem Home Assistant
#
# Uso:
#   ./dev/run_dev.sh               # cria venv, instala deps e sobe o servidor
#   ./dev/run_dev.sh --no-install  # pula instalação (venv já existe)
#
# Acesso após subir:
#   UI    → http://localhost:7843
#   Docs  → http://localhost:7843/api/docs
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${REPO_ROOT}/alexa_bridge_admin/rootfs/app"
VENV_DIR="${REPO_ROOT}/.venv-dev"
PORT="${PORT:-7843}"

# Diretórios que simulam /homeassistant/pyscript dentro do HA
DEV_PYSCRIPT_DIR="${SCRIPT_DIR}/.pyscript"

# ---- cores ----
C='\033[0;36m'; Y='\033[1;33m'; G='\033[0;32m'; NC='\033[0m'

echo -e "${C}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${C}║   Alexa Bridge Admin — Dev Mode (sem HA)         ║${NC}"
echo -e "${C}╚══════════════════════════════════════════════════╝${NC}"

# ---- venv e deps ----
if [[ "${1:-}" != "--no-install" ]]; then
  if [[ ! -d "${VENV_DIR}" ]]; then
    echo -e "${Y}➜ Criando virtualenv em ${VENV_DIR}...${NC}"
    python3 -m venv "${VENV_DIR}"
  fi
  echo -e "${Y}➜ Instalando dependências...${NC}"
  "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
  "${VENV_DIR}/bin/pip" install --quiet -r "${APP_DIR}/requirements.txt"
fi

# ---- diretórios de dados ----
mkdir -p "${DEV_PYSCRIPT_DIR}/backups"

# Copia o alexa_bridge.yaml de fixture apenas se ainda não existir
if [[ ! -f "${DEV_PYSCRIPT_DIR}/alexa_bridge.yaml" ]]; then
  cp "${SCRIPT_DIR}/alexa_bridge.yaml" "${DEV_PYSCRIPT_DIR}/alexa_bridge.yaml"
  echo -e "${G}✔ alexa_bridge.yaml copiado para ${DEV_PYSCRIPT_DIR}${NC}"
fi

# ---- variáveis de ambiente ----
export ALEXA_BRIDGE_CONFIG_PATH="${DEV_PYSCRIPT_DIR}/alexa_bridge.yaml"
export ALEXA_BRIDGE_SCRIPT_PATH="${DEV_PYSCRIPT_DIR}/alexa_bridge.py"
export ALEXA_BRIDGE_SCRIPT_TEMPLATE="${APP_DIR}/assets/alexa_bridge.py"
export ALEXA_BRIDGE_YAML_TEMPLATE="${APP_DIR}/assets/alexa_bridge.yaml"
export SUPERVISOR_TOKEN=""
export SUPERVISOR_URL=""
export DEV_MODE="true"
# PYTHONPATH: permite `import app.*` a partir de rootfs/
export PYTHONPATH="${APP_DIR}/..${PYTHONPATH:+:${PYTHONPATH}}"

# ---- info ----
echo -e "${G}✔ config   : ${ALEXA_BRIDGE_CONFIG_PATH}${NC}"
echo -e "${G}✔ script   : ${ALEXA_BRIDGE_SCRIPT_PATH}${NC}"
echo -e "${G}✔ UI       : http://localhost:${PORT}${NC}"
echo -e "${G}✔ API docs : http://localhost:${PORT}/api/docs${NC}"
echo ""

# ---- sobe com hot-reload ----
exec "${VENV_DIR}/bin/uvicorn" app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --reload \
  --reload-dir "${APP_DIR}" \
  --log-level info \
  --app-dir "${APP_DIR}"
