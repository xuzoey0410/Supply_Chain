#!/usr/bin/env bash
set -euo pipefail
SUPPLY_APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -n "${SUPPLY_PYTHON:-}" ]]; then
  SUPPLY_RUNTIME="$SUPPLY_PYTHON"
elif [[ -x "$SUPPLY_APP_DIR/.venv/bin/python" ]]; then
  SUPPLY_RUNTIME="$SUPPLY_APP_DIR/.venv/bin/python"
elif [[ -x "$SUPPLY_APP_DIR/../.venv/bin/python" ]]; then
  SUPPLY_RUNTIME="$SUPPLY_APP_DIR/../.venv/bin/python"
else
  SUPPLY_RUNTIME="python3"
fi
cd "$SUPPLY_APP_DIR"
exec "$SUPPLY_RUNTIME" -m streamlit run "$SUPPLY_APP_DIR/Agent_App.py" \
  --server.address 127.0.0.1 \
  --server.port "${SUPPLY_PORT:-8503}" \
  --server.fileWatcherType poll \
  --server.headless true \
  --browser.gatherUsageStats false
