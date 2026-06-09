#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/maithai/Sensei Cut/analyse-market-sensei-cut"

cd "$PROJECT_DIR"

PORT="$(python3 -c 'import json; print(json.load(open("config.json")).get("ports_and_integrations", {}).get("streamlit_port", 8501))' 2>/dev/null || echo 8501)"
URL="http://localhost:${PORT}"

echo "Analyse Market Sensei Cut startet lokal auf dem Desktop."
echo "Modus: APP_ENV=local"
echo "Login: In der App registrieren, E-Mail bestaetigen, Passwort selbst erstellen."
echo ""

if lsof -ti tcp:${PORT} >/dev/null 2>&1; then
  echo "App laeuft bereits auf ${URL}. Browser wird geoeffnet."
  open "$URL"
  exit 0
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Virtuelle Python-Umgebung wird erstellt..."
  python3 -m venv .venv
fi

if ! .venv/bin/python -c "import streamlit" >/dev/null 2>&1; then
  echo "Abhaengigkeiten werden installiert..."
  .venv/bin/python -m pip install -r requirements.txt
fi

open "$URL" >/dev/null 2>&1 || true

echo "App startet. Zum Beenden dieses Fenster schliessen oder Ctrl+C druecken."
echo ""

APP_ENV=local .venv/bin/streamlit run app.py \
  --server.port "${PORT}" \
  --server.headless true \
  --browser.gatherUsageStats false
