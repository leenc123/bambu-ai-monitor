#!/bin/bash
""" Install and start YOLO inference server on the host machine.

Run this on the HOST (Orange Pi), NOT inside the HA container.

Usage:  python3 inference_server/install.py
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Install YOLO inference server")
    parser.add_argument("--port", type=int, default=19530,
                        help="Server port (default: 19530)")
    parser.add_argument("--model", default="",
                        help="Path to best.onnx (default: auto-detect)")
    parser.add_argument("--service", action="store_true",
                        help="Install as systemd service (auto-start on boot)")
    args = parser.parse_args()

    print("=" * 50)
    print("YOLO Inference Server Installer")
    print("=" * 50)

    # 1. Find the project directory
    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent  # custom_components/bambu_ai_monitor
    model_default = project_dir / "model" / "best.onnx"

    model_path = args.model or str(model_default)
    if not Path(model_path).exists():
        print(f"WARNING: Model not found at: {model_path}")
        print("Make sure to export best.onnx first:")
        print("  python test/export_onnx.py --output custom_components/bambu_ai_monitor/model/best.onnx")
        if not args.model:
            print("Or provide the path manually: --model /path/to/best.onnx")
    else:
        print(f"Model: {model_path}")

    # 2. Install dependencies
    print("\nInstalling dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "onnxruntime", "pillow", "numpy"],
        check=True,
    )
    print("Dependencies installed.")

    server_script = script_dir / "server.py"

    if args.service:
        # Install as systemd service
        service_name = "yolo-inference-server"
        service_content = f"""[Unit]
Description=YOLO Inference Server for Bambu AI Monitor
After=network.target

[Service]
Type=simple
User={os.environ.get('USER', 'root')}
ExecStart={sys.executable} {server_script} --port {args.port} --model {model_path}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
        service_path = Path(f"/etc/systemd/system/{service_name}.service")
        print(f"\nInstalling systemd service: {service_path}")
        subprocess.run(["sudo", "tee", str(service_path)], input=service_content, text=True, check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", service_name], check=True)
        subprocess.run(["sudo", "systemctl", "start", service_name], check=True)
        print(f"Service '{service_name}' started and enabled on boot.")
    else:
        # Manual start
        print("\n" + "=" * 50)
        print("Install complete! Start the server manually:")
        print(f"  nohup {sys.executable} {server_script} --port {args.port} --model {model_path} &")
        print("\nOr install as a service for auto-start:")
        print(f"  {sys.executable} {script_dir}/install.py --service")
        print("=" * 50)


if __name__ == "__main__":
    main()
