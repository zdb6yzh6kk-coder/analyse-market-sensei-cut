#!/usr/bin/env bash
set -euo pipefail

LABEL="com.senseicut.analyse-market.evening"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ -f "$PLIST_PATH" ]]; then
  launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  rm "$PLIST_PATH"
  echo "Evening Job entfernt: $PLIST_PATH"
else
  echo "Kein Evening Job gefunden: $PLIST_PATH"
fi
