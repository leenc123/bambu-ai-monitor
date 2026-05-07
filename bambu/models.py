"""Data models for Bambu Lab printer status."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PrintStage(StrEnum):
    """Print stage codes from MQTT payload."""
    IDLE = "IDLE"
    PREPARE = "PREPARE"
    RUNNING = "RUNNING"
    PAUSE = "PAUSE"
    FINISH = "FINISH"
    FAILED = "FAILED"


@dataclass
class PrinterInfo:
    """Basic printer information."""
    serial: str
    model: str
    software_version: str = ""
    ip_address: str = ""


@dataclass
class PrinterStatus:
    """Current printer status parsed from MQTT payload."""
    stage: str = PrintStage.IDLE
    gcode_state: str = "IDLE"  # IDLE, PREPARE, RUNNING, PAUSE
    print_progress: float = 0.0
    remaining_time_sec: int = 0
    bed_temperature: float = 0.0
    bed_target_temperature: float = 0.0
    nozzle_temperature: float = 0.0
    nozzle_target_temperature: float = 0.0
    fan_speed: int = 0
    fan_gear: int = 0
    heatbreak_fan_speed: int = 0
    cooling_fan_speed: int = 0
    layer_num: int = 0
    total_layer_count: int = 0
    print_weight: float = 0.0
    print_length: int = 0
    mc_print_sub_stage: int = 0
    mc_percent: int = 0
    online: bool = False


@dataclass
class AIAnalysisResult:
    """Result from AI vision analysis."""
    anomaly_detected: bool
    anomaly_type: str | None = None
    confidence: float = 0.0
    description: str = ""
    raw_response: str = ""
    analysis_time: datetime | None = None

    @classmethod
    def from_api_response(cls, raw: str) -> AIAnalysisResult:
        """Parse AI analysis result from AI response string."""
        import json
        import re

        try:
            # Extract JSON from markdown code blocks (```json ... ```) or
            # find the first { ... } block in the response
            json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if not json_match:
                json_match = re.search(r"(\{.*\})", raw, re.DOTALL)

            json_str = json_match.group(1) if json_match else raw
            data = json.loads(json_str)

            return cls(
                anomaly_detected=data.get("anomaly_detected", False),
                anomaly_type=data.get("anomaly_type"),
                confidence=data.get("confidence", 0.0),
                description=data.get("description", ""),
                raw_response=raw,
                analysis_time=datetime.now(),
            )
        except (json.JSONDecodeError, KeyError, re.error) as err:
            return cls(
                anomaly_detected=False,
                anomaly_type="other",
                confidence=0.0,
                description=f"Failed to parse AI response: {err}",
                raw_response=raw,
                analysis_time=datetime.now(),
            )


def parse_printer_status(payload: dict) -> PrinterStatus:
    """Parse MQTT payload into PrinterStatus."""
    status = PrinterStatus()

    print_data = payload.get("print", {})
    if not print_data:
        return status

    status.gcode_state = print_data.get("gcode_state", "IDLE")
    status.stage = print_data.get("gcode_state", PrintStage.IDLE)
    status.print_progress = float(print_data.get("mc_percent", 0))
    status.remaining_time_sec = int(print_data.get("mc_remaining_time", 0))

    bed_temp = print_data.get("bed_temper", 0)
    status.bed_temperature = float(bed_temp) if bed_temp else 0.0
    bed_target = print_data.get("bed_target_temper", 0)
    status.bed_target_temperature = float(bed_target) if bed_target else 0.0

    nozzle_temp = print_data.get("nozzle_temper", 0)
    status.nozzle_temperature = float(nozzle_temp) if nozzle_temp else 0.0
    nozzle_target = print_data.get("nozzle_target_temper", 0)
    status.nozzle_target_temperature = float(nozzle_target) if nozzle_target else 0.0

    status.layer_num = int(print_data.get("layer_num", 0))
    status.total_layer_count = int(print_data.get("total_layer_num", 0))
    status.print_weight = float(print_data.get("gcode_file_prepare", {}).get("weight", 0) or 0)

    fan_info = print_data.get("fan", {})
    if isinstance(fan_info, dict):
        status.fan_speed = int(fan_info.get("fan_speed", 0))
    elif isinstance(fan_info, (int, float)):
        status.fan_speed = int(fan_info)

    return status
