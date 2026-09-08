# Bambu Inference Add-on image (Debian/glibc → onnxruntime works).
# NOTE: server.py is synced from
#   custom_components/bambu_ai_monitor/inference_server/server.py
# Keep both files identical when updating.
ARG BUILD_FROM=python:3.11-slim
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir onnxruntime pillow numpy

WORKDIR /app
COPY server.py /app/server.py
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 19530

CMD ["/run.sh"]
