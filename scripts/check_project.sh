#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m json.tool config.json
python3 -m json.tool version.json
grep -qx "python-3.11" runtime.txt
PYTHONPYCACHEPREFIX=.pycache python3 -m py_compile \
  main.py \
  app.py \
  modules/__init__.py \
  modules/app_env.py \
  modules/auth.py \
  modules/data_provider.py \
  modules/database.py \
  modules/indicators.py \
  modules/market_analyzer.py \
  modules/portfolio_tracker.py \
  modules/power_check.py \
  modules/risk_management.py \
  modules/score_engine.py \
  modules/report_generator.py \
  modules/updater.py \
  modules/workspace_store.py

bash -n install_evening_job.sh
bash -n uninstall_evening_job.sh
bash -n desktop_start.command
bash -n desktop_stop.command
bash -n scripts/security_check.sh

if grep -R "Trade Republic\\|orders_enabled.: true\\|broker_enabled.: true\\|execute_api_calls.: true\\|auth.*enabled.: false\\|two_factor.*enabled.: false\\|require_password_for_sensitive_settings.: false" \
  app.py main.py modules config.json README.md; then
  echo "Found forbidden broker/order/security text"
  exit 1
fi

grep -q '"require_allowed_emails_in_cloud": true' config.json
grep -q '"sensitive_unlock_minutes": 15' config.json

echo "Analyse Market Sensei Cut check OK"
