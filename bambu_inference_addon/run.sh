#!/bin/bash
# Add-on entrypoint: resolve model file, then start server.py.
set -e

PORT="${PORT:-19530}"
MODEL_URL="${MODEL_URL:-}"
MODEL_PATH="/data/best.onnx"

# Options from HA Supervisor (bashio) when available.
if command -v bashio >/dev/null 2>&1; then
  OPT_PORT="$(bashio::config 'port' 2>/dev/null || echo '')"
  OPT_URL="$(bashio::config 'model_url' 2>/dev/null || echo '')"
  [ -n "$OPT_PORT" ] && PORT="$OPT_PORT"
  [ -n "$OPT_URL" ] && MODEL_URL="$OPT_URL"
fi

# Allow a user-provided model via /share (no re-download).
if [ -f "/share/bambu_ai_model/best.onnx" ]; then
  MODEL_PATH="/share/bambu_ai_model/best.onnx"
  echo "[run] Using shared model: $MODEL_PATH"
elif [ ! -f "$MODEL_PATH" ] && [ -n "$MODEL_URL" ]; then
  echo "[run] Downloading model from $MODEL_URL ..."
  curl -sSL -o "$MODEL_PATH" "$MODEL_URL"
fi

if [ ! -f "$MODEL_PATH" ]; then
  echo "[run] WARNING: model not found at $MODEL_PATH."
  echo "[run] Place best.onnx at /share/bambu_ai_model/best.onnx or set model_url option."
fi

echo "[run] Starting inference server on port $PORT (model: $MODEL_PATH)"
exec python3 /app/server.py --port "$PORT" --model "$MODEL_PATH"
