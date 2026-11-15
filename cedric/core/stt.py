"""Speech-to-Text (STT) interface and Vosk implementation with grammar and open-vocabulary modes."""

import os
import re
import json
import time
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Dict, Any

logger = logging.getLogger("cedric.stt")

# BUG-01 fix: strip [unk] tokens that Vosk emits for unrecognised words before
# the result reaches any routing or matching logic.
_UNK_PATTERN = re.compile(r"\[unk\]", re.IGNORECASE)


def _strip_unk(text: str) -> str:
    """Removes Vosk '[unk]' tokens and collapses leftover whitespace."""
    return re.sub(r"\s+", " ", _UNK_PATTERN.sub("", text)).strip()


class STTEngine(ABC):
    """Abstract interface for speech recognition engines."""

    @abstractmethod
    def set_grammar(self, phrases: List[str]) -> None:
        """Sets or restricts recognition grammar to the specified phrases."""
        pass

    @abstractmethod
    def recognize_stream(
        self,
        audio_stream_manager,
        silence_timeout_sec: float = 5.0,
    ) -> Tuple[str, bool]:
        """Recognizes speech from audio stream until utterance completes or timeout occurs.
        Returns: (transcript, is_timeout)
        """
        pass


class VoskSTT(STTEngine):
    """Vosk speech recognition engine supporting both grammar-constrained and open-vocabulary modes."""

    def __init__(self, model_path: Optional[str] = None, model_name: str = "vosk-model-small-en-us-0.15", sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.model_path = model_path
        self.model_name = model_name
        self.model = None
        self._grammar_json: Optional[str] = None
        self._init_model()

    def _init_model(self) -> None:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1) # Suppress noisy Vosk C++ logs

        # Priority 1: explicitly passed model_path
        if self.model_path and os.path.isdir(self.model_path):
            logger.info(f"Loading Vosk model from directory: {self.model_path}")
            self.model = Model(self.model_path)
            return

        # Priority 2: local models/ directory inside CEDRIC
        local_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models", self.model_name)
        if os.path.isdir(local_dir):
            logger.info(f"Loading Vosk model from local models folder: {local_dir}")
            self.model = Model(local_dir)
            return

        # Priority 3: standard ~/.cache/vosk or download by model_name
        logger.info(f"Loading Vosk model '{self.model_name}' via vosk.Model...")
        try:
            self.model = Model(model_name=self.model_name)
            logger.info("Vosk model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load Vosk model: {e}", exc_info=True)
            self.model = None

    def build_grammar(self, phrases: List[str]) -> str:
        """Constructs a Vosk grammar JSON string from phrases.
        Vosk expects a JSON list of words/phrases plus '[unk]' for unknown tokens.
        """
        unique_tokens = set()
        for p in phrases:
            cleaned = p.strip().lower()
            if cleaned:
                unique_tokens.add(cleaned)
                for w in cleaned.split():
                    unique_tokens.add(w)

        # Always include numbers and control words
        extra_tokens = [
            "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "zero",
            "yes", "no", "cancel", "stop", "exit", "done", "back", "up", "more", "help",
            "open", "launch", "start", "go", "to", "read", "show", "this", "folder", "files",
            "[unk]"
        ]
        unique_tokens.update(extra_tokens)
        
        grammar_list = sorted(list(unique_tokens))
        return json.dumps(grammar_list)

    def set_grammar(self, phrases: List[str]) -> None:
        """Configures the active grammar for recognition."""
        if not phrases:
            self._grammar_json = None
            return
        self._grammar_json = self.build_grammar(phrases)
        logger.debug(f"Grammar set with {len(phrases)} base phrases.")

    def _create_recognizer(self, use_grammar: bool = True):
        from vosk import KaldiRecognizer
        if self.model is None:
            return None

        if use_grammar and self._grammar_json:
            return KaldiRecognizer(self.model, self.sample_rate, self._grammar_json)
        else:
            return KaldiRecognizer(self.model, self.sample_rate)

    def recognize_stream(
        self,
        audio_stream_manager,
        silence_timeout_sec: float = 5.0,
    ) -> Tuple[str, bool]:
        """Listens from the audio stream. Uses grammar recognition first;
        if empty, retries with open-vocabulary recognizer as required by Section 5.
        """
        if self.model is None:
            logger.error("Vosk model is not initialized.")
            return "", True

        rec = self._create_recognizer(use_grammar=True)
        if rec is None:
            return "", True

        start_time = time.monotonic()
        last_speech_time = None
        has_started_speaking = False
        captured_frames = []

        while True:
            now = time.monotonic()

            # Timeout check before speech begins
            if not has_started_speaking and (now - start_time > silence_timeout_sec):
                logger.info("Speech recognition timed out (initial silence).")
                return "", True

            # Timeout check after speech has paused (utterance end detection)
            if has_started_speaking and last_speech_time and (now - last_speech_time > 1.2):
                logger.debug("Speech pause detected, finalizing utterance.")
                break

            # Absolute max safety timeout: 15 seconds
            if now - start_time > 15.0:
                break

            frame = audio_stream_manager.get_frame(timeout=0.05)
            if not frame:
                continue

            captured_frames.append(frame)

            if rec.AcceptWaveform(frame):
                res = json.loads(rec.Result())
                raw_text = res.get("text", "").strip()
                # BUG-01: strip [unk] tokens before returning
                text = _strip_unk(raw_text)
                if raw_text:
                    logger.info(f"Grammar STT result (finalized): '{raw_text}' -> cleaned: '{text}'")
                if text:
                    return text, False
            else:
                partial = json.loads(rec.PartialResult())
                partial_text = partial.get("partial", "").strip()
                if partial_text:
                    if not has_started_speaking:
                        has_started_speaking = True
                        logger.debug(f"Speech detected: '{partial_text}'")
                    last_speech_time = now

        # Get final result from grammar recognizer
        final_res = json.loads(rec.FinalResult())
        raw_text = final_res.get("text", "").strip()
        # BUG-01: strip [unk] tokens before returning
        text = _strip_unk(raw_text)
        if raw_text:
            logger.info(f"Grammar STT final result: '{raw_text}' -> cleaned: '{text}'")
        if text:
            return text, False

        # Section 5 fallback: "If grammar recognition returns nothing usable,
        # retry once in open-vocabulary mode, then fuzzy match the result."
        if captured_frames:
            logger.info("Grammar recognition returned empty. Retrying with open-vocabulary recognizer...")
            open_rec = self._create_recognizer(use_grammar=False)
            if open_rec:
                for f in captured_frames:
                    if open_rec.AcceptWaveform(f):
                        pass
                open_res = json.loads(open_rec.FinalResult())
                open_text = _strip_unk(open_res.get("text", "").strip())
                if open_text:
                    logger.info(f"Open-vocabulary STT result: '{open_text}'")
                    return open_text, False

        return "", False

