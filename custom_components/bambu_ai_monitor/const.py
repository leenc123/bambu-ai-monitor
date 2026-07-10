"""Constants for Bambu AI Print Monitor."""

from enum import StrEnum

DOMAIN = "bambu_ai_monitor"

# Configuration keys
CONF_HOST = "host"
CONF_ACCESS_CODE = "access_code"
CONF_SERIAL = "serial"
CONF_PRINTER_MODEL = "printer_model"
CONF_CAMERA_PORT = "camera_port"
CONF_YOLO_MODEL_PATH = "yolo_model_path"
CONF_INFERENCE_HOST = "inference_host"
CONF_INFERENCE_PORT = "inference_port"
CONF_ANALYSIS_INTERVAL = "analysis_interval"
CONF_CONFIDENCE_THRESHOLD = "confidence_threshold"
CONF_AUTO_PAUSE = "auto_pause"
CONF_CONSECUTIVE_DETECTIONS = "consecutive_detections"
CONF_SSH_HOST = "host_ssh_host"
CONF_SSH_USER = "host_ssh_user"
CONF_SSH_PORT = "host_ssh_port"
CONF_SSH_KEY = "host_ssh_key"

# Defaults
DEFAULT_CAMERA_PORT = 6000
DEFAULT_MQTT_PORT = 8883
DEFAULT_ANALYSIS_INTERVAL = 300  # 5 minutes
DEFAULT_CONFIDENCE_THRESHOLD = 0.5  # YOLO detection confidence threshold
DEFAULT_AUTO_PAUSE = True
DEFAULT_CONSECUTIVE_DETECTIONS = 2
# Default ONNX model path: relative to the component directory
DEFAULT_YOLO_MODEL_PATH = "model/best.onnx"
DEFAULT_INFERENCE_HOST = "localhost"
DEFAULT_INFERENCE_PORT = 19530

# YOLO detection classes (single-class: spaghetti only)
YOLO_CLASS_NAMES = ["spaghetti"]

# YOLO → AnomalyType mapping (class name → internal type)
YOLO_ANOMALY_TYPE_MAP = {
    "spaghetti": "spaghetti",
}

# Analysis interval options (seconds)
ANALYSIS_INTERVAL_OPTIONS = {
    30: "30 seconds",
    60: "1 minute",
    300: "5 minutes",
    600: "10 minutes",
    1800: "30 minutes",
}


class PrinterModel(StrEnum):
    """Supported Bambu Lab printer models."""

    X1C = "X1C"
    X1E = "X1E"
    P1P = "P1P"
    P1S = "P1S"
    A1 = "A1"
    A1_MINI = "A1 Mini"


class AnomalyType(StrEnum):
    """Print anomaly types (YOLO-detected classes)."""

    SPAGHETTI = "spaghetti"
    NONE = "none"


ANOMALY_TRANSLATIONS = {
    "spaghetti": "炒面/拉丝",
    "none": "正常",
}

# Printer status mapping
PRINTER_STATUS_MAP = {
    "RUNNING": "running",
    "PAUSE": "paused",
    "FINISH": "finished",
    "IDLE": "idle",
    "PREPARE": "preparing",
    "FAILED": "failed",
}

# Service names
SERVICE_ANALYZE_NOW = "analyze_now"
SERVICE_SET_ANALYSIS_INTERVAL = "set_analysis_interval"

# Entity base naming
MANUFACTURER = "Bambu Lab"
