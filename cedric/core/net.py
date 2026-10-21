"""Network connectivity checking with short TTL caching."""

import socket
import time
import logging

logger = logging.getLogger("cedric.net")

_LAST_CHECK_TIME = 0.0
_LAST_CHECK_RESULT = False
_CACHE_TTL = 10.0  # seconds


def is_online(host: str = "1.1.1.1", port: int = 443, timeout: float = 1.0) -> bool:
    """Checks whether the device has internet access via a fast TCP connect.
    
    The result is cached for 10 seconds to avoid repeated network probes.
    """
    global _LAST_CHECK_TIME, _LAST_CHECK_RESULT

    now = time.monotonic()
    if now - _LAST_CHECK_TIME < _CACHE_TTL:
        return _LAST_CHECK_RESULT

    online = False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            online = True
    except (socket.timeout, OSError) as e:
        logger.debug(f"Network probe failed ({host}:{port}): {e}")
        online = False

    _LAST_CHECK_TIME = now
    _LAST_CHECK_RESULT = online
    return online

