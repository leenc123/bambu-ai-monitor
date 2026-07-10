"""Inference server status monitor and auto-installer.

Auto-installs the inference server on the Docker HOST by:
1. Using Docker socket (if mounted) → runs install in host namespace
2. Fallback: writes install script to /config/ for manual one-command execution
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 19530
SCRIPT_DIR = Path(__file__).parent
SERVER_SCRIPT = SCRIPT_DIR / "inference_server" / "server.py"
INSTALL_SCRIPT = SCRIPT_DIR / "inference_server" / "install.py"
DOCKER_SOCKET = "/var/run/docker.sock"


class InferenceServerManager:
    """Check inference server status; auto-install on host via Docker socket."""

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
        self._model_path = model_path or str(
            SCRIPT_DIR / "model" / "best.onnx"
        )
        self._install_script_path = "/config/install_inference_server.sh"

    @property
    def is_running(self) -> bool:
        return self._last_known_running

    @property
    def port(self) -> int:
        return self._inference_port

    @property
    def install_script_path(self) -> str:
        return self._install_script_path

    async def async_check_health(self) -> bool:
        """Check if inference server is reachable via HTTP /health."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._last_known_running = data.get("status") == "ok"
                        return self._last_known_running
        except Exception:
            pass
        self._last_known_running = False
        return False

    async def async_ensure_running(self) -> bool:
        """Check server; if not running, auto-install on host."""
        healthy = await self.async_check_health()
        if healthy:
            _LOGGER.info("Inference server running at %s", self._base_url)
            return True

        # Strategy 1: auto-install via Docker socket (no user action needed)
        if os.path.exists(DOCKER_SOCKET):
            _LOGGER.info("Docker socket found, auto-installing on host...")
            ok = await self._async_install_via_docker()
            if ok:
                for _ in range(30):
                    if await self.async_check_health():
                        _LOGGER.info("Inference server installed and running!")
                        return True
                    await asyncio.sleep(1)
                _LOGGER.warning("Server started but not yet healthy, will retry")
                return False

        # Strategy 2: write install script for manual one-command execution
        await self._async_write_install_script()
        _LOGGER.warning(
            "Inference server not running.\n"
            "Run this ONE command on the host:\n"
            "  bash %s",
            self._install_script_path,
        )
        return False

    async def async_restart(self) -> bool:
        """Restart the server on the host."""
        docker_ok = await self._async_docker_exec(
            "systemctl restart yolo-inference-server 2>/dev/null || "
            f"(pkill -f 'server.py' 2>/dev/null; sleep 1; "
            f"nohup python3 /opt/bambu-ai-inference/server.py "
            f"--port {self._inference_port} "
            f"--model /opt/bambu-ai-inference/best.onnx "
            f"> /var/log/yolo-inference-server.log 2>&1 &)"
        )
        if docker_ok:
            for _ in range(15):
                if await self.async_check_health():
                    return True
                await asyncio.sleep(1)
        return False

    # ── Docker socket auto-install ─────────────────────────────────

    async def _async_install_via_docker(self) -> bool:
        """Auto-install inference server on host via Docker socket.

        Runs a privileged container that mounts the host rootfs and executes
        the install script in the host's namespace (chroot).
        """
        script = self._generate_install_script()
        install_cmd = "/tmp/install.sh"

        # Write install script to /config (visible from host too)
        Path(self._install_script_path).write_text(script)
        Path(self._install_script_path).chmod(0o755)

        # Build the docker run command
        cmd = (
            f"cp {self._install_script_path} {install_cmd} && "
            f"chmod +x {install_cmd} && bash {install_cmd}"
        )
        return await self._async_docker_exec(cmd)

    async def _async_docker_exec(self, command: str) -> bool:
        """Run a command on the host via Docker socket.

        Uses a lightweight Alpine container with:
          --pid=host    → access host process namespace
          -v /:/host    → mount host rootfs
          chroot /host  → execute in host namespace
        """
        try:
            import aiohttp

            # Connect to Docker daemon via Unix socket
            connector = aiohttp.UnixConnector(path=DOCKER_SOCKET)
            async with aiohttp.ClientSession(connector=connector) as session:
                # 1. Create container
                create_payload = {
                    "Image": "alpine:latest",
                    "Cmd": ["sh", "-c", f"chroot /host sh -c '{command}'"],
                    "HostConfig": {
                        "PidMode": "host",
                        "Binds": ["/:/host:rslave"],
                        "NetworkMode": "host",
                        "AutoRemove": True,
                    },
                }
                async with session.post(
                    "http://localhost/v1.41/containers/create",
                    json=create_payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status not in (200, 201):
                        text = await resp.text()
                        _LOGGER.error("Docker create failed: %s", text[:300])
                        return False
                    data = await resp.json()
                    container_id = data["Id"]

                # 2. Start container
                async with session.post(
                    f"http://localhost/v1.41/containers/{container_id}/start",
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status not in (200, 204):
                        text = await resp.text()
                        _LOGGER.error("Docker start failed: %s", text[:300])
                        return False

                # 3. Wait for completion
                async with session.post(
                    f"http://localhost/v1.41/containers/{container_id}/wait",
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        code = result.get("StatusCode", -1)
                        if code == 0:
                            return True
                        _LOGGER.error("Install exited with code %s", code)

                # 4. Get logs on failure
                async with session.get(
                    f"http://localhost/v1.41/containers/{container_id}/logs?stdout=true&stderr=true",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    log_text = await resp.text()
                    _LOGGER.error("Install failed. Logs:\n%s", log_text[:1000])

        except ImportError:
            _LOGGER.error("aiohttp required for Docker auto-install")
        except FileNotFoundError:
            _LOGGER.debug("Docker socket not accessible")
        except Exception as err:
            _LOGGER.error("Docker auto-install error: %s", err)

        return False

    # ── Fallback: write install script ─────────────────────────────

    async def _async_write_install_script(self) -> None:
        """Write self-contained install script to /config/ (shared with host)."""
        script = self._generate_install_script()
        try:
            Path(self._install_script_path).write_text(script)
            Path(self._install_script_path).chmod(0o755)
            _LOGGER.info(
                "Install script written to %s", self._install_script_path
            )
        except Exception as err:
            _LOGGER.error("Failed to write install script: %s", err)

    def _generate_install_script(self) -> str:
        """Generate the install script content (auto-detects host paths)."""
        return f"""#!/bin/bash
# Bambu AI Monitor - Inference Server Installer
# Auto-generated. Run ONCE on the host:
#   bash {self._install_script_path}

set -e

# Auto-detect plugin directory from script's own location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/custom_components/bambu_ai_monitor"
SERVER_SRC="$PLUGIN_DIR/inference_server/server.py"
MODEL_SRC="$PLUGIN_DIR/model/best.onnx"
INSTALL_SRC="$PLUGIN_DIR/inference_server/install.py"

echo "=== Installing inference server dependencies ==="
pip3 install onnxruntime pillow numpy -q

echo "=== Deploying server files ==="
mkdir -p /opt/bambu-ai-inference

if [ -f "$SERVER_SRC" ]; then
  cp "$SERVER_SRC" /opt/bambu-ai-inference/server.py
  echo "server.py copied"
else
  echo "Warning: server.py not found at $SERVER_SRC"
fi

if [ -f "$MODEL_SRC" ]; then
  cp "$MODEL_SRC" /opt/bambu-ai-inference/best.onnx
  echo "best.onnx copied"
else
  echo "Warning: best.onnx not found at $MODEL_SRC"
fi

[ -f "$INSTALL_SRC" ] && cp "$INSTALL_SRC" /opt/bambu-ai-inference/install.py

echo "=== Installing systemd service ==="
PYTHON3=$(command -v python3)
cat > /etc/systemd/system/yolo-inference-server.service << SERVICEEOF
[Unit]
Description=YOLO Inference Server for Bambu AI Monitor
After=network.target

[Service]
Type=simple
ExecStart=$PYTHON3 /opt/bambu-ai-inference/server.py --port {self._inference_port} --model /opt/bambu-ai-inference/best.onnx
WorkingDirectory=/opt/bambu-ai-inference
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/yolo-inference-server.log
StandardError=append:/var/log/yolo-inference-server.log

[Install]
WantedBy=multi-user.target
SERVICEEOF

echo "=== Starting service ==="
systemctl daemon-reload
systemctl enable yolo-inference-server
systemctl restart yolo-inference-server

echo ""
echo "=== Done! ==="
echo "Service: yolo-inference-server"
echo "Status: $(systemctl is-active yolo-inference-server)"
echo "Port: {self._inference_port}"
echo "Logs: journalctl -u yolo-inference-server -f"
"""
