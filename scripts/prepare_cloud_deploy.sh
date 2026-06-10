#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="python3"
if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
fi

echo "1/5 Projektcheck"
./scripts/check_project.sh

echo "2/5 Security-Check"
./scripts/security_check.sh

echo "3/5 Lokaler Smoke-Test"
APP_ENV=local "$PYTHON_BIN" scripts/smoke_app.py

echo "4/5 Cloud-Smoke-Test"
APP_ENV=cloud APP_PASSWORD=deploy-smoke-test "$PYTHON_BIN" scripts/smoke_app.py

echo "5/5 Upload-Zip bauen"
mkdir -p deploy
ZIP_PATH="deploy/analyse-market-sensei-cut-streamlit-cloud.zip"
TMP_DIR="$(mktemp -d)"
mkdir -p "$TMP_DIR/app"

rsync -a \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.pycache/' \
  --exclude '.pytest_cache/' \
  --exclude '.pip-cache/' \
  --exclude '.DS_Store' \
  --exclude '.streamlit/secrets.toml' \
  --exclude 'data/' \
  --exclude 'reports/' \
  --exclude 'logs/' \
  --exclude 'backups/' \
  --exclude 'updates/' \
  --exclude 'deploy/' \
  --exclude 'src/' \
  --exclude 'tests/' \
  ./ "$TMP_DIR/app/"

rm -f "$ZIP_PATH"
(cd "$TMP_DIR" && zip -qr "$OLDPWD/$ZIP_PATH" app)
rm -rf "$TMP_DIR"

"$PYTHON_BIN" - <<'PY'
from pathlib import Path
from zipfile import ZipFile

zip_path = Path("deploy/analyse-market-sensei-cut-streamlit-cloud.zip")
with ZipFile(zip_path) as zf:
    names = zf.namelist()
    forbidden = [
        ".git/",
        ".venv/",
        "__pycache__/",
        ".pycache/",
        ".pip-cache/",
        "secrets.toml",
        "data/",
        "reports/",
        "logs/",
        "backups/",
        "updates/",
    ]
    bad = [name for name in names if any(part in name for part in forbidden)]
    required = [
        "app/app.py",
        "app/config.json",
        "app/requirements.txt",
        "app/runtime.txt",
        "app/README.md",
        "app/modules/online_ops.py",
    ]
    missing = [name for name in required if name not in names]
    if bad or missing:
        raise SystemExit(f"Zip nicht sauber. bad={bad[:5]} missing={missing}")
    print(f"Zip OK: {zip_path} ({len(names)} Dateien)")
PY

echo "Cloud-Deploy-Vorbereitung OK"
