#!/bin/bash
# Add-on entrypoint: resolve model file, then start server.py.
set -e

PORT="${PORT:-19530}"
MODEL_URL="${MODEL_URL:-}"
# Default model path; sidecar mode overrides via $MODEL_PATH env (/model/best.onnx).
MODEL_PATH="${MODEL_PATH:-/data/best.onnx}"

# Options from HA Supervisor (bashio) when available.
if command -v bashio >/dev/null 2>&1; then
  OPT_PORT="$(bashio::config 'port' 2>/dev/null || echo '')"
  OPT_URL="$(bashio::config 'model_url' 2>/dev/null || echo '')"
  [ -n "$OPT_PORT" ] && PORT="$OPT_PORT"
  [ -n "$OPT_URL" ] && MODEL_URL="$OPT_URL"
fi

# Model resolution order:
# 1. $MODEL_PATH env (sidecar bind-mount /model/best.onnx)
# 2. /model/best.onnx (sidecar default mount)
# 3. /share/bambu_ai_model/best.onnx (user-provided, no re-download)
# 4. download $MODEL_URL → /data/best.onnx
if [ -n "$MODEL_PATH" ] && [ -f "$MODEL_PATH" ]; then
  echo "[run] Using model: $MODEL_PATH"
elif [ -f "/model/best.onnx" ]; then
  MODEL_PATH="/model/best.onnx"
  echo "[run] Using sidecar model: $MODEL_PATH"
elif [ -f "/share/bambu_ai_model/best.onnx" ]; then
  MODEL_PATH="/share/bambu_ai_model/best.onnx"
  echo "[run] Using shared model: $MODEL_PATH"
elif [ -n "$MODEL_URL" ]; then
  echo "[run] Downloading model from $MODEL_URL ..."
  mkdir -p "$(dirname "$MODEL_PATH")"
  curl -sSL -o "$MODEL_PATH" "$MODEL_URL"
fi

if [ ! -f "$MODEL_PATH" ]; then
  echo "[run] ERROR: model not found at $MODEL_PATH."
  echo "[run] Mount best.onnx at /model, place it at /share/bambu_ai_model/best.onnx, or set model_url option."
  exit 1
fi

echo "[run] Starting inference server on port $PORT (model: $MODEL_PATH)"
exec python3 /app/server.py --port "$PORT" --model "$MODEL_PATH"
