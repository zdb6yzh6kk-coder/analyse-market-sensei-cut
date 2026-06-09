#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/maithai/Sensei Cut/analyse-market-sensei-cut"

cd "$PROJECT_DIR"

PORT="$(python3 -c 'import json; print(json.load(open("config.json")).get("ports_and_integrations", {}).get("streamlit_port", 8501))' 2>/dev/null || echo 8501)"

PIDS="$(lsof -ti tcp:${PORT} || true)"

if [[ -z "$PIDS" ]]; then
  echo "Keine laufende Analyse Market Sensei Cut App auf Port ${PORT} gefunden."
  exit 0
fi

echo "Stoppe Analyse Market Sensei Cut auf Port ${PORT}..."
kill $PIDS
echo "Gestoppt."
