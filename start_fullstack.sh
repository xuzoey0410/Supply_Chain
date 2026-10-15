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
export SUPPLY_API_URL="http://127.0.0.1:${SUPPLY_API_PORT:-8000}"
export SUPPLY_MODE=public
mkdir -p .local
"$SUPPLY_RUNTIME" -m uvicorn api_server:app_factory --factory \
  --host 127.0.0.1 --port "${SUPPLY_API_PORT:-8000}" > .local/api-server.log 2>&1 &
SUPPLY_API_PID=$!
cleanup() { kill "$SUPPLY_API_PID" 2>/dev/null || true; wait "$SUPPLY_API_PID" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
SUPPLY_API_READY=false
for SUPPLY_ATTEMPT in {1..40}; do
  if ! kill -0 "$SUPPLY_API_PID" 2>/dev/null; then
    cat .local/api-server.log
    exit 1
  fi
  if "$SUPPLY_RUNTIME" -c 'import json,os,urllib.request; r=json.load(urllib.request.urlopen(os.environ["SUPPLY_API_URL"]+"/health",timeout=1)); assert r["service"]=="supply-studio-api"' 2>/dev/null; then
    SUPPLY_API_READY=true
    break
  fi
  sleep 0.5
done
if [[ "$SUPPLY_API_READY" != true ]]; then
  echo 'API 启动超时，请查看 .local/api-server.log'
  exit 1
fi
printf 'API 文档：http://127.0.0.1:%s/docs\n' "${SUPPLY_API_PORT:-8000}"
"$SUPPLY_RUNTIME" -m streamlit run Agent_App.py \
  --server.address 127.0.0.1 --server.port "${SUPPLY_PORT:-8504}" \
  --server.fileWatcherType poll --server.headless true --browser.gatherUsageStats false
