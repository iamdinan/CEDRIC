"""Text-To-Speech (TTS) interface and Windows SAPI5 pyttsx3 implementation."""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional, Callable

logger = logging.getLogger("cedric.tts")


class Speaker(ABC):
    """Abstract interface for speech synthesis engines."""

    @abstractmethod
    def speak(self, text: str) -> None:
        """Speaks the provided text synchronously or blocking until audio completes."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stops ongoing speech if any."""
        pass


class Pyttsx3Speaker(Speaker):
    """pyttsx3 (Windows SAPI5) speech engine implementation."""

    def __init__(
        self,
        rate: int = 185,
        volume: float = 1.0,
        voice_id: Optional[str] = None,
        on_start: Optional[Callable[[], None]] = None,
        on_finish: Optional[Callable[[], None]] = None,
    ):
        self.rate = rate
        self.volume = volume
        self.voice_id = voice_id
        self.on_start = on_start
        self.on_finish = on_finish
        self._lock = threading.Lock()
        self._engine = None
        self._init_engine()

    def _init_engine(self) -> None:
        try:
            import pyttsx3
            # Initialize SAPI5 engine
            self._engine = pyttsx3.init("sapi5")
            self._engine.setProperty("rate", self.rate)
            self._engine.setProperty("volume", self.volume)
            if self.voice_id:
                self._engine.setProperty("voice", self.voice_id)
            logger.info("Initialized pyttsx3 SAPI5 speaker.")
        except Exception as e:
            logger.error(f"Failed to initialize pyttsx3: {e}", exc_info=True)
            self._engine = None

    def speak(self, text: str) -> None:
        if not text:
            return

        with self._lock:
            if self.on_start:
                try:
                    self.on_start()
                except Exception as e:
                    logger.debug(f"Error in on_start callback: {e}")

            logger.info(f"Speaking: '{text}'")
            try:
                if self._engine is None:
                    self._init_engine()

                if self._engine:
                    self._engine.say(text)
                    self._engine.runAndWait()
                else:
                    print(f"[Cedric Speech]: {text}")
            except Exception as e:
                logger.error(f"Error during TTS speak: {e}", exc_info=True)
                # Re-initialize engine if crashed
                self._engine = None
            finally:
                if self.on_finish:
                    try:
                        self.on_finish()
                    except Exception as e:
                        logger.debug(f"Error in on_finish callback: {e}")

    def stop(self) -> None:
        with self._lock:
            if self._engine:
                try:
                    self._engine.stop()
                except Exception as e:
                    logger.debug(f"Error stopping TTS: {e}")

