"""MQTT command payloads for Bambu Lab printer control."""

from __future__ import annotations

import json


class BambuCommands:
    """Static methods for building MQTT command payloads."""

    @staticmethod
    def build_get_version_command() -> str:
        """Build MQTT payload to request printer version info."""
        return json.dumps({
            "info": {
                "sequence_id": "0",
                "command": "get_version",
            }
        })

    @staticmethod
    def build_push_all_command() -> str:
        """Build MQTT payload to start pushing status data.

        Without this command, the printer will NOT send any status
        updates after MQTT connection.  Must be published once on
        the request topic after subscribing.
        """
        return json.dumps({
            "pushing": {
                "sequence_id": "0",
                "command": "pushall",
            }
        })

    @staticmethod
    def build_start_push_command(sequence_id: str = "0") -> str:
        """Build MQTT payload to resume/start pushing data.

        Used for watchdog recovery and push retry after initial connect.
        Unlike pushall (which is a one-shot full dump), 'start' tells
        the printer to begin/resume publishing incremental updates.

        Args:
            sequence_id: Increment this on retries to avoid the printer's
                         MQTT broker deduplicating identical commands.
        """
        return json.dumps({
            "pushing": {
                "sequence_id": sequence_id,
                "command": "start",
            }
        })

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
