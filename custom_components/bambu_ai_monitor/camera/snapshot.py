"""Camera snapshot capture for Bambu Lab printers.

A1 Mini / P1P / P1S use a raw TLS socket on port 6000 (not HTTP).
X1/X1C may also support HTTP on port 6000.
"""

from __future__ import annotations

import asyncio
import io
import logging
import socket
import ssl
import struct

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

    A1 Mini (and P1 series) uses a raw TLS binary protocol on port 6000:
    connect → wrap TLS → send binary auth packet → read 16-byte header →
    read JPEG payload.  This is NOT an HTTP endpoint.

    Falls back to HTTP GET (for printers that support it) if TLS socket fails.

    Args:
        host: Printer IP address
        access_code: LAN access code
        camera_port: Camera port (default 6000)
        timeout: Total timeout in seconds

    Returns:
        JPEG image bytes, resized and compressed, or None on failure
    """
    # Strategy 1: raw TLS socket (A1 Mini / P1 protocol — the standard Bambu way)
    snapshot = await _async_capture_tls_socket(host, access_code, camera_port, timeout)
    if snapshot:
        return _prepare_image(snapshot)

    # Strategy 2: HTTP fallback (some printers/firmware support this)
    snapshot = await _async_capture_http(host, access_code, camera_port, timeout)
    if snapshot:
        return _prepare_image(snapshot)

    return None


async def _async_capture_tls_socket(
    host: str,
    access_code: str,
    port: int,
    timeout: int,
) -> bytes | None:
    """Capture one JPEG frame via raw TLS socket on port 6000.

    Protocol:
      1. TCP connect
      2. TLS handshake (self-signed cert, skip verify)
      3. Send 96-byte binary auth packet:
         - 4 bytes: 0x40 (little-endian)
         - 4 bytes: 0x3000 (little-endian)
         - 4 bytes: 0x00000000
         - 4 bytes: 0x00000000
         - username ('bblp') padded to 32 bytes with nulls
         - access_code padded to 32 bytes with nulls
      4. Read 16-byte header: first 4 bytes = JPEG payload size (LE)
      5. Read payload_size bytes of JPEG data
    """
    loop = asyncio.get_event_loop()

    def _capture() -> bytes | None:
        # Build binary auth packet (96 bytes total)
        username = "bblp"
        auth = bytearray()
        auth += struct.pack("<I", 0x40)
        auth += struct.pack("<I", 0x3000)
        auth += struct.pack("<I", 0)
        auth += struct.pack("<I", 0)
        # username padded to 32 bytes
        auth += username.encode("ascii").ljust(32, b"\x00")
        # access_code padded to 32 bytes
        auth += access_code.encode("ascii").ljust(32, b"\x00")

        # TLS context (skip cert verification for self-signed printer cert)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    tls.settimeout(timeout)

                    # Send auth packet
                    tls.write(auth)

                    # Read 16-byte header
                    header = bytearray()
                    while len(header) < 16:
                        chunk = tls.recv(16 - len(header))
                        if not chunk:
                            _LOGGER.warning(
                                "TLS socket closed before header received"
                            )
                            return None
                        header.extend(chunk)

                    # Payload size is first 4 bytes of header (little-endian)
                    payload_size = int.from_bytes(header[0:4], byteorder="little")
                    if payload_size < 2 or payload_size > 500_000:
                        _LOGGER.warning(
                            "Invalid payload size: %d", payload_size
                        )
                        return None

                    # Read JPEG payload
                    payload = bytearray()
                    while len(payload) < payload_size:
                        chunk = tls.recv(payload_size - len(payload))
                        if not chunk:
                            _LOGGER.warning(
                                "TLS socket closed during payload read"
                            )
                            return None
                        payload.extend(chunk)

                    # Quick JPEG sanity check
                    if (
                        len(payload) < 4
                        or payload[0:2] != b"\xff\xd8"
                        or payload[-2:] != b"\xff\xd9"
                    ):
                        _LOGGER.warning(
                            "Received data doesn't look like JPEG "
                            "(%d bytes, starts with %s)",
                            len(payload),
                            payload[:4].hex(),
                        )
                        return None

                    return bytes(payload)

        except socket.timeout:
            _LOGGER.debug("TLS socket timeout for %s:%s", host, port)
            return None
        except OSError as err:
            _LOGGER.debug("TLS socket error for %s:%s: %s", host, port, err)
            return None
        except Exception as err:
            _LOGGER.debug(
                "TLS socket snapshot failed for %s:%s: %s", host, port, err
            )
            return None

    return await loop.run_in_executor(None, _capture)


async def _async_capture_http(
    host: str,
    access_code: str,
    port: int,
    timeout: int,
) -> bytes | None:
    """Fallback: HTTP GET snapshot (some X1 series support this)."""
    import aiohttp

    url = f"http://{host}:{port}/snapshot.jpg"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                auth=aiohttp.BasicAuth("bblp", access_code),
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status != 200:
                    _LOGGER.debug(
                        "HTTP camera returned %s from %s",
                        response.status,
                        url,
                    )
                    return None

                return await response.read()

    except asyncio.TimeoutError:
        _LOGGER.debug("HTTP camera timeout from %s", url)
        return None
    except Exception as err:
        _LOGGER.debug("HTTP camera error from %s: %s", url, err)
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
