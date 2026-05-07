"""MQTT command payloads for Bambu Lab printer control."""

from __future__ import annotations

import json


class BambuCommands:
    """Static methods for building MQTT command payloads."""

    @staticmethod
    def build_pause_command() -> str:
        """Build MQTT payload to pause the current print."""
        return json.dumps({
            "print": {
                "command": "pause",
                "param": "",
                "sequence_id": "0",
            }
        })

    @staticmethod
    def build_resume_command() -> str:
        """Build MQTT payload to resume a paused print."""
        return json.dumps({
            "print": {
                "command": "resume",
                "param": "",
                "sequence_id": "0",
            }
        })

    @staticmethod
    def build_stop_command() -> str:
        """Build MQTT payload to stop the current print."""
        return json.dumps({
            "print": {
                "command": "stop",
                "param": "",
                "sequence_id": "0",
            }
        })
