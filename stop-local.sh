#!/usr/bin/env bash
set -euo pipefail

for pid in $(ps -eo pid,cmd --no-headers | awk '$0 ~ /python -m process_engine_api/ {print $1}'); do
  kill "$pid" 2>/dev/null || true
done

for pid in $(ps -eo pid,cmd --no-headers | awk '$0 ~ /python -m process_engine/ {print $1}'); do
  kill "$pid" 2>/dev/null || true
done

for pid in $(ps -eo pid,cmd --no-headers | awk '$0 ~ /vite --host 127.0.0.1/ {print $1}'); do
  kill "$pid" 2>/dev/null || true
done

echo "Local API, worker and designer processes stopped."
