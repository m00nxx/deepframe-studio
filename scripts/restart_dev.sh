#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[DeepFrame] stopping old dev processes..."
for pidfile in /tmp/deepframe-backend.pid /tmp/deepframe-vite.pid /tmp/deepframe-tauri.pid; do
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
  fi
done
python - <<'PY'
import os
import signal

needles = [
    "uvicorn deepframe_api.app:app",
    "/mnt/c/_codex_progetti/DeepFrame Studio/node_modules/.bin/vite",
    "/mnt/c/_codex_progetti/DeepFrame Studio/node_modules/.bin/tauri",
    "target/debug/deepframe-studio",
]
skip = {os.getpid(), os.getppid()}
for name in os.listdir("/proc"):
    if not name.isdigit():
        continue
    pid = int(name)
    if pid in skip:
        continue
    try:
        cmdline = (
            open(f"/proc/{pid}/cmdline", "rb")
            .read()
            .replace(b"\0", b" ")
            .decode("utf-8", "ignore")
        )
    except OSError:
        continue
    if any(needle in cmdline for needle in needles):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
PY
sleep 1

echo "[DeepFrame] starting backend on http://127.0.0.1:8765 ..."
setsid bash -lc "cd '$ROOT' && npm run backend:dev" > /tmp/deepframe-backend.log 2>&1 &
echo $! > /tmp/deepframe-backend.pid

for _ in {1..60}; do
  if curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

echo "[DeepFrame] starting Vite on http://127.0.0.1:5173 ..."
setsid bash -lc "cd '$ROOT' && npm run dev" > /tmp/deepframe-vite.log 2>&1 &
echo $! > /tmp/deepframe-vite.pid

for _ in {1..80}; do
  if curl -fsS http://127.0.0.1:5173/index.html >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS http://127.0.0.1:5173/index.html >/dev/null 2>&1; then
  echo "[DeepFrame] Vite failed to start. See /tmp/deepframe-vite.log" >&2
  exit 1
fi

echo "[DeepFrame] starting Tauri on http://127.0.0.1:5173/index.html ..."
TAURI_DEV_CONFIG='{"build":{"beforeDevCommand":"","devUrl":"http://127.0.0.1:5173/index.html"}}'
setsid bash -lc "cd '$ROOT' && NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost WEBKIT_DISABLE_DMABUF_RENDERER=1 WEBKIT_DISABLE_COMPOSITING_MODE=1 LIBGL_ALWAYS_SOFTWARE=1 DEEPFRAME_API_URL=http://127.0.0.1:8765 npx tauri dev --config '$TAURI_DEV_CONFIG'" > /tmp/deepframe-tauri.log 2>&1 &
echo $! > /tmp/deepframe-tauri.pid

echo "[DeepFrame] started."
echo "  backend log: /tmp/deepframe-backend.log"
echo "  vite log:    /tmp/deepframe-vite.log"
echo "  tauri log:   /tmp/deepframe-tauri.log"
