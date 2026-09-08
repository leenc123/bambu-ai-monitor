"""Inference server status monitor and auto-deployer.

No host systemd / chroot / manual bash required:

1. Docker socket available (``/var/run/docker.sock``) → pull/run a
   sidecar inference container (Debian/glibc based, onnxruntime works)
   with ``RestartPolicy: always``. Fully automatic, zero user action.
2. No Docker socket (HA OS etc.) → the user installs the companion
   Add-on once from the Add-on Store (UI click, no SSH). This manager
   then just waits for ``/health`` to become reachable.

The HA container itself is Alpine/musl based, so onnxruntime cannot run
in-process — that is why inference lives in a sidecar/Add-on instead of
``manifest.json`` requirements.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 19530
SCRIPT_DIR = Path(__file__).parent
MODEL_SRC = SCRIPT_DIR / "model" / "best.onnx"
DOCKER_SOCKET = "/var/run/docker.sock"
DOCKER_API = "http://localhost"

# Prebuilt inference image (Debian/glibc + onnxruntime + server.py).
# Advanced users may override via env var, e.g. a local mirror.
INFERENCE_IMAGE = os.environ.get(
    "BAMBU_INFERENCE_IMAGE",
    "ghcr.io/leenc123/bambu-inference:latest",
)
CONTAINER_NAME = "bambu-ai-inference"

# Staged model dir shared with the sidecar container.
# /config is on a Docker volume, so the sidecar can bind-mount it.
MODEL_DIR = Path("/config/bambu_ai_model")
MODEL_DST = MODEL_DIR / "best.onnx"

# Where the Add-on / sidecar is expected to listen (informational).
ADDON_DOC_URL = "https://github.com/leenc123/bambu-ai-monitor/tree/main/bambu_inference_addon"


class InferenceServerManager:
    """Check inference server health; auto-deploy sidecar via Docker socket."""

    def __init__(
        self,
        inference_host: str = "127.0.0.1",
        inference_port: int = DEFAULT_PORT,
        model_path: str = "",
    ) -> None:
        self._inference_host = inference_host
        self._inference_port = inference_port
        self._base_url = f"http://{inference_host}:{inference_port}"
        self._last_known_running = False
        self._model_path = model_path or str(MODEL_SRC)
        # "external" | "sidecar" | "addon_required"
        self._deploy_mode = "external"

    @property
    def is_running(self) -> bool:
        return self._last_known_running

    @property
    def port(self) -> int:
        return self._inference_port

    @property
    def deploy_mode(self) -> str:
        """How inference is provided: external / sidecar / addon_required."""
        return self._deploy_mode

    @property
    def docker_available(self) -> bool:
        return os.path.exists(DOCKER_SOCKET)

    async def async_check_health(self) -> bool:
        """Check if inference server is reachable via HTTP /health.

        Accepts both "ok" and "model_not_loaded" as running — the model
        is loaded lazily on the first /analyze request, so an unloaded
        model does not mean the server is down.
        """
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        status = data.get("status", "")
                        self._last_known_running = (
                            status == "ok" or status == "model_not_loaded"
                        )
                        return self._last_known_running
        except Exception:
            pass
        self._last_known_running = False
        return False

    async def async_ensure_running(self) -> bool:
        """Check server; if not running, auto-deploy sidecar if possible."""
        if await self.async_check_health():
            _LOGGER.info("Inference server running at %s", self._base_url)
            return True

        # Strategy 1: Docker socket → run sidecar container (zero user action)
        if self.docker_available:
            _LOGGER.info(
                "Docker socket found, deploying sidecar container %s ...",
                CONTAINER_NAME,
            )
            self._deploy_mode = "sidecar"
            if await self._async_ensure_sidecar():
                for _ in range(60):
                    if await self.async_check_health():
                        _LOGGER.info("Sidecar inference server is running!")
                        return True
                    await asyncio.sleep(2)
                _LOGGER.warning(
                    "Sidecar started but /health not ready yet, will retry later"
                )
                return False
            _LOGGER.error("Failed to deploy sidecar container")
            return False

        # Strategy 2: no socket → user installs the Add-on once (UI click).
        self._deploy_mode = "addon_required"
        _LOGGER.warning(
            "Inference server not running and no Docker socket. "
            "Install the 'Bambu Inference' Add-on from the Add-on Store once "
            "(%s), then it starts automatically. Waiting for %s ...",
            ADDON_DOC_URL,
            self._base_url,
        )
        return False

    async def async_restart(self) -> bool:
        """Restart the sidecar container (no-op without Docker socket)."""
        if not self.docker_available:
            _LOGGER.warning("No Docker socket, cannot restart sidecar automatically")
            return False
        if not await self._docker_post(f"/containers/{CONTAINER_NAME}/restart"):
            return False
        for _ in range(15):
            if await self.async_check_health():
                return True
            await asyncio.sleep(1)
        return False

    # ── Sidecar lifecycle via Docker Engine API ──────────────────────

    async def _async_ensure_sidecar(self) -> bool:
        """Pull image if needed, create + start the sidecar container."""
        try:
            self._stage_model()
        except Exception as err:
            _LOGGER.error("Failed to stage model file: %s", err)
            return False

        containers = await self._docker_get("/containers/json?all=1")
        if containers is None:
            return False
        existing = next(
            (
                c
                for c in containers
                if CONTAINER_NAME in [n.lstrip("/") for n in c.get("Names", [])]
            ),
            None,
        )

        if existing:
            state = existing.get("State", "")
            container_id = existing.get("Id", "")
            if state != "running":
                _LOGGER.info("Starting existing sidecar container ...")
                if not await self._docker_post(f"/containers/{container_id}/start"):
                    return False
            return True

        # Create new container; pull image first on 404.
        payload = {
            "Image": INFERENCE_IMAGE,
            "name": CONTAINER_NAME,
            "ExposedPorts": {"19530/tcp": {}},
            "Env": [f"MODEL_PATH=/model/best.onnx", f"PORT={self._inference_port}"],
            "HostConfig": {
                "Binds": [f"{MODEL_DIR}:/model:ro"],
                "PortBindings": {
                    "19530/tcp": [{"HostPort": str(self._inference_port)}]
                },
                "RestartPolicy": {"Name": "always"},
            },
        }
        container_id = await self._docker_create(payload)
        if container_id is None:
            _LOGGER.info("Image %s missing, pulling ...", INFERENCE_IMAGE)
            if not await self._docker_pull(INFERENCE_IMAGE):
                return False
            container_id = await self._docker_create(payload)
            if container_id is None:
                return False

        _LOGGER.info("Starting new sidecar container %s ...", container_id[:12])
        return await self._docker_post(f"/containers/{container_id}/start")

    def _stage_model(self) -> None:
        """Copy best.onnx to /config/bambu_ai_model/ for the sidecar mount."""
        src = Path(self._model_path)
        if not src.exists():
            src = MODEL_SRC
        if not src.exists():
            raise FileNotFoundError(f"Model not found: {src}")
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if not MODEL_DST.exists() or MODEL_DST.stat().st_size != src.stat().st_size:
            shutil.copy2(src, MODEL_DST)
            _LOGGER.info("Model staged at %s", MODEL_DST)

    # ── Minimal Docker Engine API client (Unix socket) ───────────────

    async def _docker_get(self, path: str):
        try:
            import aiohttp

            connector = aiohttp.UnixConnector(path=DOCKER_SOCKET)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    DOCKER_API + f"/v1.41{path}",
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    _LOGGER.error("Docker GET %s → HTTP %s", path, resp.status)
        except Exception as err:
            _LOGGER.error("Docker API error: %s", err)
        return None

    async def _docker_post(self, path: str, payload: dict | None = None) -> bool:
        try:
            import aiohttp

            connector = aiohttp.UnixConnector(path=DOCKER_SOCKET)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    DOCKER_API + f"/v1.41{path}",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status in (200, 201, 204):
                        return True
                    text = await resp.text()
                    _LOGGER.error(
                        "Docker POST %s → HTTP %s: %s", path, resp.status, text[:300]
                    )
        except Exception as err:
            _LOGGER.error("Docker API error: %s", err)
        return False

    async def _docker_create(self, payload: dict) -> str | None:
        """Create container, return id. None on failure (incl. missing image)."""
        try:
            import aiohttp

            connector = aiohttp.UnixConnector(path=DOCKER_SOCKET)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    DOCKER_API + "/v1.41/containers/create?name=" + CONTAINER_NAME,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        return data["Id"]
                    text = await resp.text()
                    _LOGGER.warning("Docker create → HTTP %s: %s", resp.status, text[:300])
        except Exception as err:
            _LOGGER.error("Docker create error: %s", err)
        return None

    async def _docker_pull(self, image: str) -> bool:
        try:
            import aiohttp

            connector = aiohttp.UnixConnector(path=DOCKER_SOCKET)
            async with aiohttp.ClientSession(connector=connector) as session:
                repo, _, tag = image.partition(":")
                params = f"fromImage={repo}&tag={tag or 'latest'}"
                async with session.post(
                    DOCKER_API + f"/v1.41/images/create?{params}",
                    timeout=aiohttp.ClientTimeout(total=600),
                ) as resp:
                    if resp.status == 200:
                        # Consume progress stream
                        await resp.read()
                        _LOGGER.info("Image %s pulled", image)
                        return True
                    text = await resp.text()
                    _LOGGER.error("Docker pull failed: %s", text[:300])
        except Exception as err:
            _LOGGER.error("Docker pull error: %s", err)
        return False
