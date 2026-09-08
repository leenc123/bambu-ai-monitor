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
    remaining_time_min: int = 0  # mc_remaining_time unit is MINUTES
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


def parse_printer_status(
    payload: dict,
    previous: PrinterStatus | None = None,
) -> PrinterStatus:
    """Parse MQTT payload into PrinterStatus.

    Bambu printers push INCREMENTAL updates — each MQTT message may
    contain only a subset of fields (e.g. only ``layer_num``, or only
    ``mc_remaining_time``, or a bare heartbeat ``{"print": {"command":
    "push_status"}}`` with no data at all).

    To avoid wiping out values like print_progress or temperatures on
    partial updates, ``previous`` is used as the baseline: only fields
    that are actually present in this payload are updated, everything
    else keeps its previous value.
    """
    if previous is None:
        status = PrinterStatus()
    else:
        # Shallow-copy so we never mutate the caller's object
        status = PrinterStatus(
            stage=previous.stage,
            gcode_state=previous.gcode_state,
            print_progress=previous.print_progress,
            remaining_time_min=previous.remaining_time_min,
            bed_temperature=previous.bed_temperature,
            bed_target_temperature=previous.bed_target_temperature,
            nozzle_temperature=previous.nozzle_temperature,
            nozzle_target_temperature=previous.nozzle_target_temperature,
            fan_speed=previous.fan_speed,
            fan_gear=previous.fan_gear,
            heatbreak_fan_speed=previous.heatbreak_fan_speed,
            cooling_fan_speed=previous.cooling_fan_speed,
            layer_num=previous.layer_num,
            total_layer_count=previous.total_layer_count,
            print_weight=previous.print_weight,
            print_length=previous.print_length,
            mc_print_sub_stage=previous.mc_print_sub_stage,
            mc_percent=previous.mc_percent,
            online=previous.online,
        )

    print_data = payload.get("print", {})
    if not print_data:
        return status

    # Only update fields that are actually present in this message.
    # Partial/heartbeat messages must not reset values to defaults.
    if "gcode_state" in print_data:
        status.gcode_state = str(print_data.get("gcode_state", "IDLE"))
        status.stage = status.gcode_state
    if "mc_percent" in print_data:
        status.mc_percent = int(print_data.get("mc_percent", 0))
        status.print_progress = float(status.mc_percent)
    if "mc_remaining_time" in print_data:
        # Unit is MINUTES per Bambu MQTT protocol (see pybambu get_end_time)
        status.remaining_time_min = int(print_data.get("mc_remaining_time", 0))
    if "mc_print_sub_stage" in print_data:
        status.mc_print_sub_stage = int(print_data.get("mc_print_sub_stage", 0))

    if "bed_temper" in print_data:
        bed_temp = print_data.get("bed_temper", 0)
        status.bed_temperature = float(bed_temp) if bed_temp else 0.0
    if "bed_target_temper" in print_data:
        bed_target = print_data.get("bed_target_temper", 0)
        status.bed_target_temperature = float(bed_target) if bed_target else 0.0

    if "nozzle_temper" in print_data:
        nozzle_temp = print_data.get("nozzle_temper", 0)
        status.nozzle_temperature = float(nozzle_temp) if nozzle_temp else 0.0
    if "nozzle_target_temper" in print_data:
        nozzle_target = print_data.get("nozzle_target_temper", 0)
        status.nozzle_target_temperature = float(nozzle_target) if nozzle_target else 0.0

    if "layer_num" in print_data:
        status.layer_num = int(print_data.get("layer_num", 0))
    if "total_layer_num" in print_data:
        status.total_layer_count = int(print_data.get("total_layer_num", 0))

    if "gcode_file_prepare" in print_data:
        weight = print_data.get("gcode_file_prepare", {}).get("weight", 0) or 0
        status.print_weight = float(weight)

    if "fan" in print_data:
        fan_info = print_data.get("fan", {})
        if isinstance(fan_info, dict):
            if "fan_speed" in fan_info:
                status.fan_speed = int(fan_info.get("fan_speed", 0))
        elif isinstance(fan_info, (int, float)):
            status.fan_speed = int(fan_info)

    return status
