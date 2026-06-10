#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

./scripts/check_project.sh

if find . -maxdepth 3 -name secrets.toml -print | grep -q .; then
  echo "Found .streamlit/secrets.toml or another secrets.toml file. Do not commit secrets."
  exit 1
fi

if rg -n -- \
  "eval\\(|exec\\(|pickle|marshal|os\\.system|Popen|shell=True|yaml\\.load|execute_api_calls.: true|orders_enabled.: true|broker_enabled.: true" \
  app.py main.py modules config.json README.md SECURITY.md; then
  echo "Found forbidden execution or broker/order pattern."
  exit 1
fi

if rg -n \
  -g '!data/**' \
  -g '!logs/**' \
  -g '!reports/**' \
  -g '!backups/**' \
  -g '!updates/**' \
  -g '!.venv/**' \
  -g '!__pycache__/**' \
  -g '!.pycache/**' \
  -g '!scripts/security_check.sh' \
  -- "-----BEGIN|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|password\\s*=\\s*['\\\"][^<]|token\\s*=\\s*['\\\"][^<]|api[_-]?key\\s*=\\s*['\\\"][^<]|secret\\s*=\\s*['\\\"][^<]"; then
  echo "Found possible hard-coded secret."
  exit 1
fi

if command -v pip-audit >/dev/null 2>&1; then
  pip-audit -r requirements.txt
else
  echo "pip-audit not installed; skipping dependency vulnerability scan."
fi

echo "Analyse Market Sensei Cut security check OK"
