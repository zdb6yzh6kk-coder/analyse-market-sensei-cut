#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.senseicut.analyse-market.evening"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

mkdir -p "$LAUNCH_AGENTS_DIR" "$PROJECT_DIR/logs"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$PROJECT_DIR/main.py</string>
    <string>--mode</string>
    <string>evening-analysis</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>22</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>$PROJECT_DIR/logs/evening_job_stdout.log</string>

  <key>StandardErrorPath</key>
  <string>$PROJECT_DIR/logs/evening_job_stderr.log</string>
</dict>
</plist>
PLIST

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Evening Job installiert: $PLIST_PATH"
echo "Startzeit: taeglich 22:30 Uhr"
echo "Hinweis: Der Python-Job bricht ab, wenn der Mac nicht am Netzteil haengt."
