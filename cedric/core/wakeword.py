"""Wake word detection interface, Porcupine implementation, and push-to-talk trigger."""

import os
import struct
import json
import logging
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Optional, Callable, List, Any

logger = logging.getLogger("cedric.wakeword")


class WakeWordEngine(ABC):
    """Abstract interface for wake word detection."""

    @abstractmethod
    def process_frame(self, pcm_bytes: bytes) -> bool:
        """Processes a frame of 16-bit 16kHz mono audio. Returns True if wake word detected."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Cleans up engine resources."""
        pass


class PorcupineEngine(WakeWordEngine):
    """Wake word detection using Picovoice Porcupine."""

    def __init__(
        self,
        keyword_path: Optional[str] = None,
        access_key: Optional[str] = None,
        sensitivity: float = 0.65,
    ):
        self.keyword_path = keyword_path
        self.access_key = access_key or os.environ.get("PICOVOICE_ACCESS_KEY")
        self.sensitivity = max(0.0, min(1.0, sensitivity))
        self._porcupine = None
        self._frame_length = 512
        self._init_engine()

    def _init_engine(self) -> None:
        if not self.access_key:
            logger.warning("PICOVOICE_ACCESS_KEY not found in environment or config.")
            return

        try:
            import pvporcupine

            if self.keyword_path and os.path.isfile(self.keyword_path):
                logger.info(f"Loading custom Porcupine keyword file: {self.keyword_path}")
                self._porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keyword_paths=[self.keyword_path],
                    sensitivities=[self.sensitivity],
                )
            else:
                logger.info(f"Custom keyword file not found at '{self.keyword_path}'. Using default keyword 'porcupine' for testing.")
                # Fallback to built-in keyword if custom .ppn file not yet generated in Picovoice console
                self._porcupine = pvporcupine.create(
                    access_key=self.access_key,
                    keywords=["porcupine"],
                    sensitivities=[self.sensitivity],
                )
            self._frame_length = self._porcupine.frame_length
            logger.info("Porcupine wake word engine initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Porcupine wake word engine: {e}")
            self._porcupine = None

    @property
    def is_available(self) -> bool:
        return self._porcupine is not None

    def process_frame(self, pcm_bytes: bytes) -> bool:
        if self._porcupine is None or not pcm_bytes:
            return False

        try:
            # Porcupine expects a sequence of int16 values of length self._frame_length
            num_samples = len(pcm_bytes) // 2
            if num_samples != self._frame_length:
                return False

            pcm_unpacked = struct.unpack(f"{num_samples}h", pcm_bytes)
            keyword_index = self._porcupine.process(pcm_unpacked)
            if keyword_index >= 0:
                logger.info(f"Wake word detected! (keyword_index={keyword_index})")
                return True
        except Exception as e:
            logger.debug(f"Porcupine process_frame error: {e}")
        return False

    def close(self) -> None:
        if self._porcupine:
            try:
                self._porcupine.delete()
            except Exception as e:
                logger.debug(f"Error closing Porcupine: {e}")
            self._porcupine = None


class VoskWakeWordEngine(WakeWordEngine):
    """Wake word detection using offline Vosk speech recognition with constrained grammar."""

    def __init__(
        self,
        model: Optional[Any] = None,
        model_path: Optional[str] = None,
        model_name: str = "vosk-model-small-en-us-0.15",
        sample_rate: int = 16000,
        keyword: str = "cedric",
    ):
        self.sample_rate = sample_rate
        self.keyword = keyword.strip().lower()
        self._model = model
        self._model_path = model_path
        self._model_name = model_name
        self._recognizer = None
        self._init_engine()

    def _init_engine(self) -> None:
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)

            if self._model is None:
                if self._model_path and os.path.isdir(self._model_path):
                    self._model = Model(self._model_path)
                else:
                    base_dir = Path(__file__).resolve().parent.parent.parent
                    local_dir = base_dir / "models" / self._model_name
                    if local_dir.is_dir():
                        self._model = Model(str(local_dir))
                    else:
                        self._model = Model(model_name=self._model_name)

            # Build grammar: keyword, common variants, and unknown token
            grammar_tokens = {self.keyword, "[unk]", "hey"}
            if self.keyword == "cedric":
                grammar_tokens.add("cedrick")

            grammar_json = json.dumps(sorted(list(grammar_tokens)))
            self._recognizer = KaldiRecognizer(self._model, self.sample_rate, grammar_json)
            logger.info(f"Vosk wake word engine initialized (keyword: '{self.keyword}').")
        except Exception as e:
            logger.error(f"Failed to initialize Vosk wake word engine: {e}", exc_info=True)
            self._recognizer = None

    @property
    def is_available(self) -> bool:
        return self._recognizer is not None

    def process_frame(self, pcm_bytes: bytes) -> bool:
        if self._recognizer is None or not pcm_bytes:
            return False

        try:
            if self._recognizer.AcceptWaveform(pcm_bytes):
                res = json.loads(self._recognizer.Result())
                text = res.get("text", "").lower()
                if self._matches(text):
                    logger.info(f"Wake word detected (AcceptWaveform): '{text}'")
                    self._recognizer.Reset()
                    return True
            else:
                res = json.loads(self._recognizer.PartialResult())
                partial = (res.get("partial") or res.get("text") or "").lower()
                if self._matches(partial):
                    logger.info(f"Wake word detected (PartialResult): '{partial}'")
                    self._recognizer.Reset()
                    return True
        except Exception as e:
            logger.debug(f"Vosk wake word process_frame error: {e}")
        return False

    def _matches(self, text: str) -> bool:
        if not text:
            return False
        words = text.split()
        if self.keyword in words:
            return True
        if self.keyword == "cedric" and "cedrick" in words:
            return True
        return False

    def close(self) -> None:
        self._recognizer = None
        self._model = None


class PushToTalkTrigger:
    """Global hotkey listener for backup push-to-talk trigger (e.g. Ctrl+Alt+Space)."""

    def __init__(self, hotkey_str: str = "<ctrl>+<alt>+<space>", on_trigger: Optional[Callable[[], None]] = None):
        self.hotkey_str = hotkey_str
        self.on_trigger = on_trigger
        self._listener = None
        self._is_running = False

    def start(self) -> bool:
        if self._is_running:
            return True

        try:
            from pynput import keyboard

            # Normalize hotkey format e.g. ctrl+alt+space -> <ctrl>+<alt>+<space>
            keys = [k.strip() for k in self.hotkey_str.lower().split("+")]
            formatted_keys = []
            for k in keys:
                if k in ("ctrl", "alt", "shift", "space", "cmd", "win"):
                    formatted_keys.append(f"<{k}>")
                else:
                    formatted_keys.append(k)
            parsed_hotkey = "+".join(formatted_keys)

            def _handle_hotkey():
                logger.info(f"Push-to-talk hotkey '{self.hotkey_str}' triggered.")
                if self.on_trigger:
                    self.on_trigger()

            self._listener = keyboard.GlobalHotKeys({parsed_hotkey: _handle_hotkey})
            self._listener.start()
            self._is_running = True
            logger.info(f"Push-to-talk hotkey listener active on {self.hotkey_str}")
            return True
        except Exception as e:
            logger.error(f"Failed to start push-to-talk listener: {e}", exc_info=True)
            return False

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception as e:
                logger.debug(f"Error stopping hotkey listener: {e}")
            self._listener = None
        self._is_running = False

