"""Process priority management for Cedric."""

import os
import logging
import psutil

logger = logging.getLogger("cedric.priority")


def set_below_normal_priority() -> bool:
    """Sets the current process priority to BELOW_NORMAL_PRIORITY_CLASS on Windows."""
    try:
        p = psutil.Process(os.getpid())
        if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            logger.info("Process priority set to BELOW_NORMAL_PRIORITY_CLASS.")
            return True
        else:
            logger.warning("BELOW_NORMAL_PRIORITY_CLASS not available on this platform.")
            return False
    except Exception as e:
        logger.error(f"Failed to set process priority: {e}", exc_info=True)
        return False

