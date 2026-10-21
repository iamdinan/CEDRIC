"""Audio stream management, microphone capture, and feedback beeps."""

import time
import queue
import logging
import threading
from typing import Optional, Callable

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

logger = logging.getLogger("cedric.audio")


def _beep_worker(frequency: int, duration_ms: int) -> None:
    if HAS_WINSOUND:
        try:
            winsound.Beep(frequency, duration_ms)
            return
        except Exception as e:
            logger.debug(f"winsound.Beep failed: {e}")
    print("\a", end="", flush=True)


def play_wake_beep(frequency: int = 1000, duration_ms: int = 80, async_play: bool = True) -> None:
    """Plays a short wake beep to signal that Cedric is listening."""
    if async_play:
        threading.Thread(target=_beep_worker, args=(frequency, duration_ms), daemon=True).start()
    else:
        _beep_worker(frequency, duration_ms)


class AudioStreamManager:
    """Manages sounddevice microphone input stream and frame queue."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_length: int = 512,
        channels: int = 1,
        max_queue_size: int = 100,
    ):
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.channels = channels
        self.frame_queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_size)
        self.is_paused = False
        self.is_running = False
        self._stream: Optional[sd.RawInputStream] = None
        self._lock = threading.Lock()

    def _audio_callback(self, indata, frames, time_info, status):
        """sounddevice raw input stream callback."""
        if status:
            logger.debug(f"Audio stream status: {status}")

        if self.is_paused or not self.is_running:
            return

        try:
            # indata is a buffer/bytes of int16 PCM
            self.frame_queue.put_nowait(bytes(indata))
        except queue.Full:
            # Drop older frames if full to avoid latency buildup
            try:
                self.frame_queue.get_nowait()
                self.frame_queue.put_nowait(bytes(indata))
            except Exception:
                pass

    def start(self) -> bool:
        """Starts the audio capture stream."""
        with self._lock:
            if self.is_running:
                return True

            if not HAS_SOUNDDEVICE:
                logger.error("sounddevice is not installed or available.")
                return False

            try:
                # Clear queue
                while not self.frame_queue.empty():
                    self.frame_queue.get_nowait()

                self._stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.frame_length,
                    dtype="int16",
                    channels=self.channels,
                    callback=self._audio_callback,
                )
                self._stream.start()
                self.is_running = True
                self.is_paused = False
                logger.info(f"Audio stream started: {self.sample_rate}Hz, frame={self.frame_length}, mono.")
                return True
            except Exception as e:
                logger.error(f"Failed to start audio stream: {e}", exc_info=True)
                self.is_running = False
                self._stream = None
                return False

    def stop(self) -> None:
        """Stops the audio capture stream."""
        with self._lock:
            self.is_running = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    logger.debug(f"Error closing audio stream: {e}")
                self._stream = None
            logger.info("Audio stream stopped.")

    def pause(self) -> None:
        """Pauses frame collection (used while Cedric speaks to avoid self-hearing)."""
        self.is_paused = True
        # Drain existing frames in queue
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

    def resume(self) -> None:
        """Resumes frame collection."""
        self.flush()
        self.is_paused = False

    def flush(self) -> None:
        """Drains any buffered frames in the queue."""
        while not self.frame_queue.empty():
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                break

    def get_frame(self, timeout: float = 0.1) -> Optional[bytes]:
        """Gets the next PCM audio frame from the queue."""
        try:
            return self.frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

