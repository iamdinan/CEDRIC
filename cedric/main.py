"""Cedric: Voice Task Assistant (Windows) — Main Application & State Machine.

Handles the complete Phase 1 offline core loop:
- Wake word (Porcupine) + Push-to-talk hotkey (Ctrl+Alt+Space)
- Audio capture with pause during TTS (no self-hearing)
- Beep on wake
- Vosk STT (grammar-restricted with open-vocab fallback)
- RapidFuzz routing & normalization
- Command registry execution (Chrome url reuse, exe discovery, URI, Explorer mode)
- Rotating file logging
- Below-normal process priority
"""

import os
import re
import sys
import time
import random
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from cedric.core.priority import set_below_normal_priority
from cedric.core.net import is_online
from cedric.core.registry import CommandRegistry
from cedric.core.router import RuleRouter, RouterContext, RoutingResult, normalize_utterance
from cedric.core.tts import Pyttsx3Speaker
from cedric.core.audio import AudioStreamManager, play_wake_beep
from cedric.core.wakeword import PorcupineEngine, VoskWakeWordEngine, PushToTalkTrigger
from cedric.core.stt import VoskSTT
from cedric.core.actions import execute_action, resolve_exe_path
from cedric.modes.explorer_nav import ExplorerNavMode


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """Configures plain text rotating file logging and console logging."""
    log_cfg = config.get("logging", {})
    log_file = log_cfg.get("file", "logs/cedric.log")
    max_bytes = log_cfg.get("max_bytes", 5 * 1024 * 1024)
    backup_count = log_cfg.get("backup_count", 5)
    level_name = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = PROJECT_ROOT / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    # Formatter
    fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Rotating File Handler
    file_handler = RotatingFileHandler(str(log_path), maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    root_logger.addHandler(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    return logging.getLogger("cedric.main")


class CedricAssistant:
    """State machine controller for Cedric Voice Task Assistant."""

    # States
    STATE_IDLE = "IDLE"
    STATE_LISTENING = "LISTENING"
    STATE_ROUTING = "ROUTING"
    STATE_AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    STATE_EXPLORER_NAV = "EXPLORER_NAV"

    # Spoken responses when awakened
    WAKE_RESPONSES = ["Yes?", "Listening.", "Go ahead."]

    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else PROJECT_ROOT / "cedric" / "config"
        self.settings_file = self.config_dir / "settings.yaml"
        self.commands_file = self.config_dir / "commands.yaml"
        self.explorer_aliases_file = self.config_dir / "explorer_aliases.yaml"

        self.settings = self._load_settings()
        self.logger = setup_logging(self.settings)

        # Set process priority
        set_below_normal_priority()

        # Initialize core components
        self.registry = CommandRegistry(str(self.commands_file))
        
        # Audio stream manager
        audio_cfg = self.settings.get("audio", {})
        self.audio_manager = AudioStreamManager(
            sample_rate=audio_cfg.get("sample_rate", 16000),
            frame_length=audio_cfg.get("frame_length", 512),
            channels=audio_cfg.get("channels", 1),
        )

        # TTS Speaker with pause/resume hooks to prevent self-hearing
        tts_cfg = self.settings.get("tts", {})
        self.speaker = Pyttsx3Speaker(
            rate=tts_cfg.get("rate", 185),
            volume=tts_cfg.get("volume", 1.0),
            voice_id=tts_cfg.get("voice") or None,
            on_start=self._on_speaker_start,
            on_finish=self._on_speaker_finish,
        )

        # STT Engine
        stt_cfg = self.settings.get("stt", {})
        self.stt = VoskSTT(
            model_path=stt_cfg.get("model_path") or None,
            model_name=stt_cfg.get("model_name", "vosk-model-small-en-us-0.15"),
            sample_rate=audio_cfg.get("sample_rate", 16000),
        )
        self._update_stt_grammar()

        # Router
        thresh_cfg = self.settings.get("thresholds", {})
        self.router = RuleRouter(
            registry=self.registry,
            high_confidence=thresh_cfg.get("high_confidence", 85.0),
            low_confidence=thresh_cfg.get("low_confidence", 65.0),
        )
        self.router_context = RouterContext()

        # Wake word engine
        ww_cfg = self.settings.get("wakeword", {})
        engine_type = ww_cfg.get("engine", "vosk").lower()
        keyword_name = ww_cfg.get("keyword", "Cedric")

        if engine_type == "porcupine":
            kw_path = ww_cfg.get("keyword_path")
            if kw_path and not Path(kw_path).is_absolute():
                kw_path = str(PROJECT_ROOT / kw_path)

            porcupine_engine = PorcupineEngine(
                keyword_path=kw_path,
                access_key=os.environ.get(ww_cfg.get("access_key_env", "PICOVOICE_ACCESS_KEY")),
                sensitivity=ww_cfg.get("sensitivity", 0.65),
            )
            if porcupine_engine.is_available:
                self.wakeword_engine = porcupine_engine
            else:
                self.logger.info("Porcupine unavailable or key missing. Falling back to offline Vosk wake word engine.")
                self.wakeword_engine = VoskWakeWordEngine(
                    model=self.stt.model,
                    keyword=keyword_name,
                    sample_rate=audio_cfg.get("sample_rate", 16000),
                )
        else:
            self.wakeword_engine = VoskWakeWordEngine(
                model=self.stt.model,
                keyword=keyword_name,
                sample_rate=audio_cfg.get("sample_rate", 16000),
            )

        # Push-to-talk trigger
        hotkey_str = self.settings.get("hotkey", "ctrl+alt+space")
        self.ptt_trigger = PushToTalkTrigger(
            hotkey_str=hotkey_str,
            on_trigger=self._on_wake_trigger,
        )

        # Explorer nav mode
        exp_cfg = self.settings.get("explorer", {})
        self.explorer_nav = ExplorerNavMode(
            speaker=self.speaker,
            stt_engine=self.stt,
            start_folder=exp_cfg.get("start_folder", "~"),
            show_hidden=exp_cfg.get("show_hidden", False),
            max_entries=exp_cfg.get("max_entries", 500),
            alias_file=str(self.explorer_aliases_file),
            inactivity_timeout_sec=self.settings.get("timeouts", {}).get("explorer_inactivity_sec", 15.0),
        )

        # State variables
        self.state = self.STATE_IDLE
        self.is_running = False
        self.sleep_paused = False  # Set by "stop listening" meta command
        self._wake_requested = False
        self.pending_confirmation_cmd = None
        self._last_wake_reply = None

        # Verify application paths on startup
        self._verify_and_update_app_paths()

    def _load_settings(self) -> Dict[str, Any]:
        if not self.settings_file.is_file():
            return {}
        with open(self.settings_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _save_settings(self) -> None:
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.settings, f, default_flow_style=False, sort_keys=False)
            self.logger.info(f"Updated settings saved to {self.settings_file}")
        except Exception as e:
            self.logger.error(f"Failed to save settings: {e}")

    def _verify_and_update_app_paths(self) -> None:
        """Section 6: Path discovery for exe apps. Check configured paths, resolve if missing,
        and update settings.yaml.
        """
        paths = self.settings.setdefault("paths", {})
        apps_to_check = {
            "vscode": "code",
            "antigravity": "antigravity",
            "opencode": "opencode",
            "postman": "postman",
            "spotify": "spotify",
            "terminal": "wt.exe",
        }

        updated = False
        for key, target in apps_to_check.items():
            current_path = paths.get(key)
            if not current_path or not os.path.exists(current_path):
                resolved = resolve_exe_path(target, paths)
                if resolved:
                    paths[key] = resolved
                    self.logger.info(f"Resolved path for '{key}': {resolved}")
                    updated = True
                else:
                    self.logger.warning(f"Could not automatically locate path for app '{key}' (target: {target})")

        if updated:
            self._save_settings()

    def _update_stt_grammar(self) -> None:
        """Builds grammar from commands and control words.

        NEW-07 fix: meta-command phrases are added in their raw (un-normalized)
        form so Vosk can hear the actual spoken words (e.g. 'repeat that',
        'stop listening').  Previously they were extended as-is which is correct,
        but we now also include individual words from each phrase so the grammar
        recogniser can hear partial utterances.
        """
        phrases = self.registry.get_all_spoken_phrases()
        for meta_list in RuleRouter.META_COMMANDS.values():
            for phrase in meta_list:
                phrases.append(phrase)
                # Also add individual words from each phrase for partial coverage
                for word in phrase.split():
                    if word not in ("[unk]",):
                        phrases.append(word)
        self.stt.set_grammar(phrases)

    def _on_speaker_start(self) -> None:
        """Prevents self-hearing by pausing audio stream collection."""
        self.audio_manager.pause()

    def _on_speaker_finish(self) -> None:
        """Resumes audio capture after Cedric finishes speaking."""
        self.audio_manager.resume()

    def _on_wake_trigger(self) -> None:
        """Callback for wake word or hotkey trigger."""
        if self.state == self.STATE_IDLE:
            self._wake_requested = True
            self.sleep_paused = False  # Hotkey unpauses sleep mode

    def start(self) -> None:
        """Main run loop for Cedric."""
        self.logger.info("Starting Cedric Voice Task Assistant...")
        
        # Start hotkey listener
        self.ptt_trigger.start()

        # Start microphone stream
        if not self.audio_manager.start():
            self.logger.error("Failed to start audio stream. Running in hotkey-only mode if mic unavailable.")

        # Report engine readiness
        kw_name = self.settings.get("wakeword", {}).get("keyword", "Cedric")
        if self.wakeword_engine.is_available:
            self.logger.info(f"Wake word active. Say '{kw_name}' or press Ctrl+Alt+Space to speak.")
        else:
            self.logger.warning("Wake word engine not active. Using Push-to-Talk (Ctrl+Alt+Space).")

        self.is_running = True
        self.state = self.STATE_IDLE

        try:
            while self.is_running:
                self._run_state_step()
                time.sleep(0.01)
        except KeyboardInterrupt:
            self.logger.info("Cedric terminated by user.")
        finally:
            self.stop()

    def stop(self) -> None:
        self.is_running = False
        self.audio_manager.stop()
        self.ptt_trigger.stop()
        self.wakeword_engine.close()
        self.logger.info("Cedric stopped.")

    def _run_state_step(self) -> None:
        """Executes a single step of the state machine."""
        if self.state == self.STATE_IDLE:
            self._handle_idle_state()

        elif self.state == self.STATE_LISTENING:
            self._handle_listening_state()

        elif self.state == self.STATE_AWAITING_CONFIRMATION:
            self._handle_confirmation_state()

        elif self.state == self.STATE_EXPLORER_NAV:
            self._handle_explorer_nav_state()

    def _handle_idle_state(self) -> None:
        """IDLE: listens only for wake word (Porcupine) or hotkey flag."""
        # Check hotkey trigger
        if self._wake_requested:
            self._wake_requested = False
            self._transition_to_listening()
            return

        # If paused by 'stop listening' command, do not check wake word
        if self.sleep_paused:
            time.sleep(0.05)
            return

        # Process audio frame through Porcupine
        frame = self.audio_manager.get_frame(timeout=0.02)
        if frame and self.wakeword_engine.is_available:
            if self.wakeword_engine.process_frame(frame):
                self._transition_to_listening()

    def _get_wake_reply(self) -> str:
        """Picks a rotating spoken wake acknowledgment, avoiding repeats."""
        candidates = [r for r in self.WAKE_RESPONSES if r != self._last_wake_reply]
        reply = random.choice(candidates) if candidates else random.choice(self.WAKE_RESPONSES)
        self._last_wake_reply = reply
        return reply

    def _transition_to_listening(self) -> None:
        self.logger.info("Transitioning to LISTENING state.")
        self.state = self.STATE_LISTENING
        # Beep synchronously so it finishes before TTS starts (prevents bleed into STT)
        play_wake_beep(1000, 80, async_play=False)
        # Verbally acknowledge — speaker.speak() pauses mic while speaking, then resumes+flushes
        wake_reply = self._get_wake_reply()
        self.speaker.speak(wake_reply)

    def _handle_listening_state(self) -> None:
        """LISTENING: captures speech with 5s silence timeout, then routes utterance."""
        timeouts = self.settings.get("timeouts", {})
        silence_timeout = timeouts.get("silence_timeout_sec", 5.0)

        transcript, is_timeout = self.stt.recognize_stream(
            self.audio_manager,
            silence_timeout_sec=silence_timeout,
        )

        if is_timeout:
            self.logger.info("Listening ended with silence or timeout.")
            # BUG-05 fix: removed misleading "Going back to sleep" — Cedric stays
            # awake (wake-word still active); only "stop listening" triggers sleep.
            self.speaker.speak("Nothing heard.")
            self.state = self.STATE_IDLE
            return

        if not transcript.strip():
            self.state = self.STATE_IDLE
            return

        self._route_utterance(transcript.strip())

    def _route_utterance(self, text: str) -> None:
        """ROUTING: Matches utterance against registry and meta commands."""
        start_time = time.monotonic()
        normalized = normalize_utterance(text)
        result = self.router.route(text, self.router_context)
        routing_time = time.monotonic() - start_time

        # Section 10: Log every utterance
        self.logger.info(
            f"Utterance: raw='{text}', norm='{normalized}', status='{result.status}', "
            f"score={result.confidence:.1f}, match='{result.matched_phrase}', time={routing_time*1000:.1f}ms"
        )

        if result.status == "meta":
            self._handle_meta_action(result.meta_action)

        elif result.status == "matched" and result.command:
            self._execute_command(result.command)

        elif result.status == "clarification" and result.command:
            self.pending_confirmation_cmd = result.command
            self.state = self.STATE_AWAITING_CONFIRMATION
            clarification_text = result.clarification_prompt or f"Did you mean {result.command.name}?"
            # BUG-04 fix: update context so "repeat that" can replay this prompt
            self.router_context.update(reply=clarification_text)
            self.speaker.speak(clarification_text)

        else:
            # Strip any residual Vosk unknown tokens before reading aloud
            # (belt-and-suspenders; stt.py strips them at source now — BUG-01)
            clean_utt = re.sub(r'\[unk\]', '', text, flags=re.IGNORECASE).strip()
            if clean_utt:
                sorry_text = f"Sorry, I didn't get that. I heard: {clean_utt}."
            else:
                sorry_text = "Sorry, I didn't catch that."
            # BUG-04 fix: update context so "repeat that" can replay the sorry message
            self.router_context.update(reply=sorry_text)
            self.speaker.speak(sorry_text)
            self.state = self.STATE_IDLE

    def _handle_meta_action(self, meta_action: Optional[str]) -> None:
        """Handles built-in meta actions."""
        if meta_action == "cancel":
            self.speaker.speak("Cancelled.")
            self.router_context.update(reply="Cancelled.")
            self.pending_confirmation_cmd = None
            self.state = self.STATE_IDLE

        elif meta_action == "repeat_that":
            last_reply = self.router_context.last_reply
            if last_reply:
                self.speaker.speak(last_reply)
            else:
                self.speaker.speak("I haven't said anything yet.")
            self.state = self.STATE_IDLE

        elif meta_action == "stop_listening":
            msg = "Going to sleep. Press Control Alt Space to wake me."
            self.router_context.update(reply=msg)
            self.speaker.speak(msg)
            self.sleep_paused = True
            self.state = self.STATE_IDLE

        elif meta_action == "what_can_you_do":
            names = [cmd.name for cmd in self.registry.all_commands()]
            total = len(names)
            shown = names[:10]
            # BUG-13 fix: grammatically clean "and N more" suffix
            if total > len(shown):
                suffix = f" and {total - len(shown)} more"
            else:
                suffix = ""
            spoken_names = ", ".join(shown) + suffix + "."
            msg = f"I can open {spoken_names}"
            self.router_context.update(reply=msg)
            self.speaker.speak(msg)
            self.state = self.STATE_IDLE

        else:
            self.state = self.STATE_IDLE

    def _execute_command(self, cmd) -> None:
        """Executes a matched command."""
        # BUG-08 fix: guard against a None cmd being passed when pending_confirmation_cmd
        # was cleared mid-clarification-chain before this method is reached.
        if cmd is None:
            self.logger.warning("_execute_command called with None command — ignoring.")
            self.state = self.STATE_IDLE
            return

        self.state = self.STATE_IDLE
        self.pending_confirmation_cmd = None

        # Check internet requirement
        if cmd.needs_internet and not is_online():
            self.logger.warning(f"Command '{cmd.name}' requires internet, but device is offline.")
            no_net_msg = "No internet connection."
            self.router_context.update(reply=no_net_msg)
            self.speaker.speak(no_net_msg)
            return

        # Special mode: File Explorer navigation
        if cmd.id == "file_explorer" or cmd.type == "special":
            self.speaker.speak(cmd.reply)
            self.router_context.update(action=cmd.id, reply=cmd.reply)
            self._enter_explorer_nav_mode()
            return

        # Speak reply before launching action
        reply = cmd.reply or f"Opening {cmd.name}."
        self.speaker.speak(reply)
        self.router_context.update(action=cmd.id, reply=reply)

        # Launch action
        success = execute_action(cmd.to_dict(), self.settings.get("paths", {}))
        if not success:
            fail_msg = f"I couldn't open {cmd.name}."
            self.router_context.update(reply=fail_msg)
            self.speaker.speak(fail_msg)

    def _handle_confirmation_state(self) -> None:
        """AWAITING_CONFIRMATION: User answers yes/no for unsure matches."""
        play_wake_beep(1200, 100)
        transcript, is_timeout = self.stt.recognize_stream(self.audio_manager, silence_timeout_sec=4.0)

        if is_timeout or not transcript:
            cancelled_msg = "Confirmation cancelled."
            self.router_context.update(reply=cancelled_msg)
            self.speaker.speak(cancelled_msg)
            self.pending_confirmation_cmd = None
            self.state = self.STATE_IDLE
            return

        norm = normalize_utterance(transcript)
        self.logger.info(f"Confirmation response: raw='{transcript}', norm='{norm}'")

        if norm in ("yes", "yeah", "yep", "sure", "correct", "do it", "open", "please"):
            cmd = self.pending_confirmation_cmd
            # BUG-08 fix: clear pending before executing so a re-entrant clarification
            # doesn't leave a stale cmd reference.
            self.pending_confirmation_cmd = None
            self._execute_command(cmd)
        elif norm in ("no", "nope", "cancel", "never mind", "wrong"):
            cancelled_msg = "Cancelled."
            self.router_context.update(reply=cancelled_msg)
            self.speaker.speak(cancelled_msg)
            self.pending_confirmation_cmd = None
            self.state = self.STATE_IDLE
        else:
            # BUG-08 fix: explicitly reset state to IDLE before re-routing so a
            # second clarification result doesn't chain back into AWAITING_CONFIRMATION
            # with a cleared pending_confirmation_cmd.
            self.pending_confirmation_cmd = None
            self.state = self.STATE_IDLE
            self._route_utterance(transcript)

    def _enter_explorer_nav_mode(self) -> None:
        """Transitions into File Explorer voice navigation mode."""
        self.state = self.STATE_EXPLORER_NAV
        self.explorer_nav.enter()

    def _handle_explorer_nav_state(self) -> None:
        """EXPLORER_NAV: Handles voice navigation inside File Explorer."""
        # Inactivity check
        inactivity = time.monotonic() - self.explorer_nav.last_interaction_time
        if inactivity > self.explorer_nav.inactivity_timeout_sec:
            self.logger.info("Explorer nav mode timed out due to inactivity.")
            self.speaker.speak("Exiting File Explorer.")
            self.explorer_nav.exit("inactivity")
            self._restore_main_grammar()
            self.state = self.STATE_IDLE
            return

        # Listen for utterance inside Explorer Nav
        transcript, is_timeout = self.stt.recognize_stream(
            self.audio_manager,
            silence_timeout_sec=3.0,
        )

        if is_timeout or not transcript:
            return

        keep_in_mode = self.explorer_nav.handle_utterance(transcript)
        if not keep_in_mode:
            self._restore_main_grammar()
            self.state = self.STATE_IDLE

    def _restore_main_grammar(self) -> None:
        """Restores the main command grammar after exiting Explorer nav mode."""
        self._update_stt_grammar()


def main():
    assistant = CedricAssistant()
    assistant.start()


if __name__ == "__main__":
    main()

