#!/usr/bin/env bash
set -euo pipefail

if [ -f "$HOME/.bashrc" ]; then
  . "$HOME/.bashrc"
fi

export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  . "$NVM_DIR/nvm.sh"
  nvm use --lts >/dev/null 2>&1 || true
fi

# Git Bash on Windows uses nvm-windows, which installs under %LOCALAPPDATA%\nvm
# and exposes node/npm as plain binaries rather than a bash nvm.sh loader.
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  if [ -n "${LOCALAPPDATA:-}" ] && [ -d "${LOCALAPPDATA}/nvm" ]; then
    NVM_ROOT="${LOCALAPPDATA}/nvm"
    for candidate in "$NVM_ROOT"/v*; do
      if [ -d "$candidate" ] && [ -x "$candidate/node.exe" ]; then
        export NVM_BIN="$candidate"
        export PATH="$NVM_BIN:$PATH"
        break
      fi
    done
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f ./.venv/Scripts/activate ]; then
  . ./.venv/Scripts/activate
elif [ -f ./.venv/bin/activate ]; then
  . ./.venv/bin/activate
fi

if [ -f ./.env ]; then
  set -a
  . ./.env
  set +a
fi

if ! python -c "import process_engine_api" >/dev/null 2>&1; then
  python -m pip install -r requirements-dev.txt
fi

python -m process_engine_api &
API_PID=$!

python -m process_engine &
WORKER_PID=$!

choose_free_port() {
  local port="${1:-5173}"
  while [ "$port" -le 5199 ]; do
    if python - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
else:
    raise SystemExit(0)
finally:
    s.close()
PY
    then
      echo "$port"
      return 0
    fi
    port=$((port + 1))
  done
  echo "No free port found in range 5173-5199" >&2
  return 1
}

cd "$SCRIPT_DIR/designer"
if [ ! -d node_modules ]; then
  npm install
fi
VITE_PORT="$(choose_free_port 5173)"
npm run dev -- --host 127.0.0.1 --port "$VITE_PORT" &
DESIGNER_PID=$!

cd "$SCRIPT_DIR"

cleanup() {
  local exit_code=$?
  if kill -0 "$API_PID" >/dev/null 2>&1; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
  if kill -0 "$WORKER_PID" >/dev/null 2>&1; then
    kill "$WORKER_PID" >/dev/null 2>&1 || true
  fi
  if kill -0 "$DESIGNER_PID" >/dev/null 2>&1; then
    kill "$DESIGNER_PID" >/dev/null 2>&1 || true
  fi
  wait "$API_PID" "$WORKER_PID" "$DESIGNER_PID" >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup INT TERM EXIT

echo "API PID: $API_PID"
echo "Worker PID: $WORKER_PID"
echo "Designer PID: $DESIGNER_PID"
echo "API: http://127.0.0.1:8000"
echo "Worker: local background job"
echo "Designer: http://127.0.0.1:${VITE_PORT}"

echo "Press Ctrl+C to stop all processes."
wait "$API_PID" "$WORKER_PID" "$DESIGNER_PID"
