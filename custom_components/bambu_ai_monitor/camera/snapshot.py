"""Camera snapshot capture for Bambu Lab printers."""

from __future__ import annotations

import asyncio
import logging
import io

import aiohttp
from PIL import Image, ImageFilter

_LOGGER = logging.getLogger(__name__)

DEFAULT_CAMERA_PORT = 6000
MAX_IMAGE_SIZE = 1024  # Maximum dimension in pixels
JPEG_QUALITY = 80
BLUR_THRESHOLD = 100  # Laplacian variance threshold; below this = blurry


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


def check_image_quality(image_bytes: bytes, threshold: int = BLUR_THRESHOLD) -> tuple[bool, float]:
    """Check image sharpness using Laplacian variance.

    Uses PIL's built-in edge detection filter to approximate the Laplacian
    response, then computes pixel variance. Low variance = blurry image.

    Args:
        image_bytes: JPEG image bytes
        threshold: Minimum acceptable Laplacian variance (default 100)

    Returns:
        Tuple of (is_acceptable, laplacian_variance)
    """
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("L")

        # Apply edge detection (approximates Laplacian gradient magnitude)
        edges = image.filter(ImageFilter.FIND_EDGES)

        # Compute pixel variance as sharpness metric
        pixels = list(edges.getdata())
        n = len(pixels)
        if n == 0:
            return False, 0.0

        mean = sum(pixels) / n
        variance = sum((p - mean) ** 2 for p in pixels) / n

        is_acceptable = variance >= threshold
        _LOGGER.debug(
            "Image quality: variance=%.1f, threshold=%d, acceptable=%s",
            variance,
            threshold,
            is_acceptable,
        )
        return is_acceptable, variance

    except Exception as err:
        _LOGGER.warning("Failed to check image quality: %s", err)
        return True, 0.0  # Pass through on error, don't block analysis
