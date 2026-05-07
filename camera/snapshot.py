"""Camera snapshot capture for Bambu Lab printers."""

from __future__ import annotations

import asyncio
import logging
import io

import aiohttp
from PIL import Image

_LOGGER = logging.getLogger(__name__)

DEFAULT_CAMERA_PORT = 6000
MAX_IMAGE_SIZE = 1024  # Maximum dimension in pixels
JPEG_QUALITY = 80


async def async_capture_snapshot(
    host: str,
    access_code: str,
    camera_port: int = DEFAULT_CAMERA_PORT,
    timeout: int = 10,
) -> bytes | None:
    """Capture a snapshot from the Bambu printer camera.

    Args:
        host: Printer IP address
        access_code: LAN access code (used as HTTP auth password)
        camera_port: Camera port (default 6000)
        timeout: Request timeout in seconds

    Returns:
        JPEG image bytes, resized and compressed, or None on failure
    """
    url = f"http://{host}:{camera_port}/snapshot.jpg"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                auth=aiohttp.BasicAuth("bblp", access_code),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status != 200:
                    _LOGGER.warning(
                        "Camera returned status %s from %s", response.status, url
                    )
                    return None

                image_bytes = await response.read()

        # Resize and compress
        return _prepare_image(image_bytes)

    except asyncio.TimeoutError:
        _LOGGER.warning("Camera snapshot timeout from %s", url)
        return None
    except aiohttp.ClientError as err:
        _LOGGER.warning("Camera connection error: %s", err)
        return None
    except Exception as err:
        _LOGGER.error("Unexpected error capturing snapshot: %s", err)
        return None


def _prepare_image(image_bytes: bytes) -> bytes:
    """Resize and compress image for API submission."""
    try:
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")

        # Resize if larger than MAX_IMAGE_SIZE
        width, height = image.size
        if max(width, height) > MAX_IMAGE_SIZE:
            ratio = MAX_IMAGE_SIZE / max(width, height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            image = image.resize((new_width, new_height), Image.LANCZOS)

        # Compress to JPEG
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return output.getvalue()

    except Exception as err:
        _LOGGER.error("Failed to prepare image: %s", err)
        return image_bytes  # Return original if processing fails
