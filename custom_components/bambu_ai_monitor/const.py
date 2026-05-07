"""Constants for Bambu AI Print Monitor."""

from enum import StrEnum

DOMAIN = "bambu_ai_monitor"

# Configuration keys
CONF_HOST = "host"
CONF_ACCESS_CODE = "access_code"
CONF_SERIAL = "serial"
CONF_PRINTER_MODEL = "printer_model"
CONF_CAMERA_PORT = "camera_port"
CONF_AI_API_KEY = "ai_api_key"
CONF_ANALYSIS_INTERVAL = "analysis_interval"
CONF_CONFIDENCE_THRESHOLD = "confidence_threshold"
CONF_AUTO_PAUSE = "auto_pause"
CONF_ANALYSIS_MODEL = "analysis_model"
CONF_CONSECUTIVE_DETECTIONS = "consecutive_detections"

# Defaults
DEFAULT_CAMERA_PORT = 6000
DEFAULT_MQTT_PORT = 8883
DEFAULT_ANALYSIS_INTERVAL = 300  # 5 minutes
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_AUTO_PAUSE = True
DEFAULT_ANALYSIS_MODEL = "qwen-vl-max-latest"
DEFAULT_CONSECUTIVE_DETECTIONS = 2

# AI provider display name
AI_PROVIDER_NAME = "通义千问"

# Vision-capable AI models
AI_MODELS = {
    "qwen-vl-max-latest": "通义千问 VL Max (推荐)",
    "qwen-vl-plus-latest": "通义千问 VL Plus",
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
    """Print anomaly types."""

    SPAGHETTI = "spaghetti"
    WARPING = "warping"
    LAYER_SHIFT = "layer_shift"
    UNDER_EXTRUSION = "under_extrusion"
    OVER_EXTRUSION = "over_extrusion"
    DETACHMENT = "detachment"
    NONE = "none"
    OTHER = "other"


ANOMALY_TRANSLATIONS = {
    "spaghetti": "炒面/面条状挤出",
    "warping": "翘边",
    "layer_shift": "层偏移",
    "under_extrusion": "欠挤出",
    "over_extrusion": "过挤出",
    "detachment": "脱落/脱离热床",
    "none": "正常",
    "other": "其他异常",
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
