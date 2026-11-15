"""File Explorer voice navigation mode (modes/explorer_nav.py).

Features:
- Dynamic grammar updates on folder changes (up to 500 entries)
- Name normalization (split camelCase, strip extensions, replace punctuation)
- Shell.Application COM window sync with explorer.exe fallback
- Ambiguity resolution (numbered options up to 5)
- History stack (go back, go up)
- Folder reading (first 10, show more)
- Aliases support (explorer_aliases.yaml)
- 15s inactivity timeout
"""

import os
import re
import yaml
import time
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from rapidfuzz import fuzz, process

logger = logging.getLogger("cedric.modes.explorer")

try:
    import pythoncom
    import win32com.client
    HAS_COM = True
except ImportError:
    HAS_COM = False


def normalize_fs_name(name: str) -> str:
    """Normalizes file/folder names for speech matching:
    1. Strip extension
    2. Split camelCase (e.g. MyThesis -> My Thesis)
    3. Separate letters and numbers (e.g. Report2026 -> Report 2026)
    4. Replace '_', '-', '.' with spaces
    5. Lowercase and collapse whitespace
    """
    if not name:
        return ""

    base_name = os.path.splitext(name)[0]
    # Split camelCase
    s1 = re.sub(r"([a-z])([A-Z])", r"\1 \2", base_name)
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s1)
    # Split letters and digits (leave single letter prefixes like v2 intact)
    s3 = re.sub(r"([a-zA-Z]{2,})([0-9])", r"\1 \2", s2)
    s4 = re.sub(r"([0-9])([a-zA-Z]{2,})", r"\1 \2", s3)
    # Replace separators with space
    s5 = re.sub(r"[_\-\.]", " ", s4)
    # Remove any non-alphanumeric except space
    s6 = re.sub(r"[^\w\s]", " ", s5)
    # Lowercase & collapse spaces
    return re.sub(r"\s+", " ", s6).strip().lower()


class ExplorerNavMode:
    """State machine controller for File Explorer voice navigation."""

    # Words that — when spoken alone or as the whole utterance — always exit Explorer Nav.
    # BUG-06 fix: keeping "cedric"/"hey cedric" as exit triggers is fragile because
    # Vosk may include the wake-word in the STT grammar as a folder token.  We now
    # use a dedicated set and check both exact match AND single-word containment so
    # partial captures like "cedric done" still trigger exit.
    EXIT_PHRASES = {
        "exit", "done", "stop", "close", "cancel", "quit",
        "exit explorer", "close explorer", "never mind", "nevermind",
        "cedric", "hey cedric",
    }
    # Single keywords that trigger exit when found anywhere in the utterance
    EXIT_KEYWORDS = {"exit", "done", "quit", "cedric"}

    CONTROL_WORDS = [
        "go back", "go up", "read this folder", "show more",
        "exit", "done", "one", "two", "three", "four", "five", "none",
        "c drive", "d drive", "downloads", "documents", "desktop", "pictures"
    ]

    KNOWN_FOLDERS = {
        "c drive": "C:\\",
        "d drive": "D:\\",
        "downloads": "~/Downloads",
        "documents": "~/Documents",
        "desktop": "~/Desktop",
        "pictures": "~/Pictures",
        "music": "~/Music",
        "videos": "~/Videos",
    }

    NUMBER_MAP = {
        "one": 0, "1": 0,
        "two": 1, "2": 1,
        "three": 2, "3": 2,
        "four": 3, "4": 3,
        "five": 4, "5": 4,
    }

    def __init__(
        self,
        speaker,
        stt_engine,
        start_folder: str = "~",
        show_hidden: bool = False,
        max_entries: int = 500,
        alias_file: Optional[str] = None,
        inactivity_timeout_sec: float = 15.0,
    ):
        self.speaker = speaker
        self.stt_engine = stt_engine
        self.start_folder = os.path.expanduser(start_folder)
        self.show_hidden = show_hidden
        self.max_entries = max_entries
        self.alias_file = alias_file
        self.inactivity_timeout_sec = inactivity_timeout_sec

        self.current_path = os.path.abspath(self.start_folder)
        self.history: List[str] = []
        self.aliases: Dict[str, str] = {}
        self.current_entries: List[Dict[str, Any]] = []
        self.ambiguous_options: List[Dict[str, Any]] = []
        self.read_index: int = 0
        self.is_active = False
        self.last_interaction_time = time.monotonic()
        self.com_active = False

        self._load_aliases()

    def _load_aliases(self) -> None:
        if self.alias_file and os.path.isfile(self.alias_file):
            try:
                with open(self.alias_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    self.aliases = {k.lower().strip(): os.path.expanduser(v) for k, v in data.items()}
                logger.info(f"Loaded {len(self.aliases)} explorer aliases from {self.alias_file}")
            except Exception as e:
                logger.error(f"Failed to load explorer aliases: {e}")

    def sync_explorer_window(self, folder_path: str) -> None:
        """Navigates an existing Explorer window to folder_path via COM,
        or launches a new Explorer window as fallback.
        """
        abs_path = os.path.abspath(folder_path)
        if HAS_COM:
            try:
                pythoncom.CoInitialize()
                shell = win32com.client.Dispatch("Shell.Application")
                windows = shell.Windows()
                found = False

                for w in windows:
                    try:
                        full_name = getattr(w, "FullName", "").lower()
                        if "explorer.exe" in full_name:
                            w.Navigate2(abs_path)
                            found = True
                            self.com_active = True
                            logger.info(f"Synchronized existing Explorer window to: {abs_path} via COM")
                            break
                    except Exception:
                        pass

                if not found:
                    logger.info(f"No existing Explorer window found. Launching new window: {abs_path}")
                    subprocess.Popen(["explorer.exe", abs_path])
                    self.com_active = True
                return
            except Exception as e:
                logger.warning(f"COM Explorer navigation failed: {e}. Falling back to explorer.exe.")

        # Fallback
        self.com_active = False
        logger.info(f"Navigating Explorer via process fallback: {abs_path}")
        subprocess.Popen(["explorer.exe", abs_path])

    def refresh_directory_contents(self) -> None:
        """Reads current_path, filters entries, normalizes names, and updates STT grammar."""
        self.current_entries.clear()
        self.read_index = 0

        if not os.path.isdir(self.current_path):
            return

        try:
            with os.scandir(self.current_path) as it:
                raw_entries = []
                for entry in it:
                    if not self.show_hidden and entry.name.startswith("."):
                        continue
                    raw_entries.append(entry)

            # Cap entries
            is_capped = len(raw_entries) > self.max_entries
            selected_entries = raw_entries[:self.max_entries]

            phrases_for_grammar = set(self.CONTROL_WORDS)

            for entry in selected_entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False

                norm_name = normalize_fs_name(entry.name)
                entry_info = {
                    "name": entry.name,
                    "path": entry.path,
                    "is_dir": is_dir,
                    "normalized": norm_name,
                }
                self.current_entries.append(entry_info)

                if norm_name:
                    phrases_for_grammar.add(norm_name)
                    # Also include "open <name>" and "go to <name>"
                    phrases_for_grammar.add(f"open {norm_name}")
                    phrases_for_grammar.add(f"go to {norm_name}")

            # Include aliases for grammar
            for a in self.aliases.keys():
                phrases_for_grammar.add(a)

            # Dynamic grammar update
            if not is_capped and self.stt_engine:
                self.stt_engine.set_grammar(list(phrases_for_grammar))
                logger.info(f"Explorer dynamic grammar updated with {len(phrases_for_grammar)} phrases.")
            else:
                logger.info(f"Directory has {len(raw_entries)} entries (> {self.max_entries}). Using open vocabulary.")
                if self.stt_engine:
                    self.stt_engine.set_grammar([])  # Open vocabulary

        except PermissionError:
            self.speaker.speak("I can't open that.")
            logger.warning(f"Permission denied accessing directory: {self.current_path}")
        except Exception as e:
            logger.error(f"Error scanning directory {self.current_path}: {e}", exc_info=True)

    def enter(self) -> None:
        """Enters Explorer Navigation mode."""
        self.is_active = True
        self.history.clear()
        self.ambiguous_options.clear()
        self.last_interaction_time = time.monotonic()
        logger.info(f"Entered Explorer Nav mode at: {self.current_path}")
        self.sync_explorer_window(self.current_path)
        self.refresh_directory_contents()
        self.speaker.speak(f"File Explorer ready in {os.path.basename(self.current_path) or 'root'}.")

    def exit(self, reason: str = "done") -> None:
        """Exits Explorer Navigation mode.

        NEW-01/06 fix: only speak the exit confirmation when the user explicitly
        asked to exit ('user requested').  Caller-driven exits (e.g. inactivity
        timeout) already speak their own message before calling this method, so
        speaking 'Done.' here as well causes a double-TTS.
        """
        self.is_active = False
        self.ambiguous_options.clear()
        logger.info(f"Exiting Explorer Nav mode (reason: {reason})")
        if reason == "user requested":
            self.speaker.speak("Done.")

    def handle_utterance(self, raw_text: str) -> bool:
        """Processes a voice command inside Explorer Nav mode.
        Returns True to stay in mode, False to exit mode.
        """
        self.last_interaction_time = time.monotonic()
        text = raw_text.lower().strip()
        logger.info(f"Explorer Nav handling voice utterance: '{text}'")

        # 1. Exit / Done commands
        # BUG-06 fix: check both exact phrase match and single-keyword containment
        # so "cedric", "hey cedric", partial matches etc. all reliably exit.
        words_in_text = set(text.split())
        if text in self.EXIT_PHRASES or bool(words_in_text & self.EXIT_KEYWORDS):
            self.exit("user requested")
            return False

        # 2. Ambiguity resolution (user selecting option 1 to 5)
        if self.ambiguous_options:
            if text in ("none", "neither", "cancel"):
                self.ambiguous_options.clear()
                self.speaker.speak("Cancelled.")
                return True

            for word, idx in self.NUMBER_MAP.items():
                if word in text.split():
                    if idx < len(self.ambiguous_options):
                        chosen = self.ambiguous_options[idx]
                        self.ambiguous_options.clear()
                        self._activate_entry(chosen)
                        return True

            # If not a number, clear ambiguous options and treat as a new query
            self.ambiguous_options.clear()

        # 3. History: "go back"
        if text in ("go back", "back"):
            if self.history:
                prev_path = self.history.pop()
                self._navigate_to(prev_path, add_to_history=False)
            else:
                self.speaker.speak("No previous folder.")
            return True

        # 4. History: "go up"
        if text in ("go up", "up", "parent", "parent folder"):
            parent = os.path.dirname(self.current_path)
            if parent and parent != self.current_path and os.path.isdir(parent):
                self._navigate_to(parent)
            else:
                self.speaker.speak("Already at top level.")
            return True

        # 5. Jump to known folder: "go to <folder>" or "<folder>"
        clean_text = re.sub(r"^(go to|open)\s+", "", text).strip()
        for k, v in self.KNOWN_FOLDERS.items():
            if clean_text == k or text == f"go to {k}" or text == f"open {k}":
                dest = os.path.expanduser(v)
                if os.path.isdir(dest):
                    self._navigate_to(dest)
                    return True

        # 6. Check custom aliases (e.g. explorer_aliases.yaml)
        for alias_phrase, target_path in self.aliases.items():
            if alias_phrase in clean_text or clean_text in alias_phrase:
                if os.path.exists(target_path):
                    if os.path.isdir(target_path):
                        self._navigate_to(target_path)
                    else:
                        self._open_file(target_path)
                    return True

        # 7. Reading folder contents
        if "read this folder" in text or "read folder" in text:
            self.read_index = 0
            self._read_next_entries()
            return True

        if "show more" in text or "read more" in text or "next" in text:
            self._read_next_entries()
            return True

        # 8. Match file or folder inside current directory
        # Strip leading "open" or "go to"
        target_query = clean_text

        # Rapidfuzz search against current entries
        matches = self._find_matching_entries(target_query)
        if not matches:
            self.speaker.speak("No match found.")
            return True

        # If exactly 1 match
        top_entry, top_score = matches[0]
        if len(matches) == 1:
            self._activate_entry(top_entry)
            return True

        # If top match is clearly ahead of second match
        second_score = matches[1][1]
        if (top_score - second_score >= 15) and top_score >= 80:
            self._activate_entry(top_entry)
            return True

        # Ambiguity: multiple close matches
        ambiguous = [m[0] for m in matches[:5]]
        self.ambiguous_options = ambiguous
        num_str = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}.get(len(ambiguous), str(len(ambiguous)))
        
        words = ["One", "Two", "Three", "Four", "Five"]
        spoken_list = []
        for i, item in enumerate(ambiguous):
            clean_item_name = normalize_fs_name(item["name"])
            spoken_list.append(f"{words[i]}, {clean_item_name}")

        prompt = f"{num_str} matches. " + ". ".join(spoken_list) + "."
        self.speaker.speak(prompt)
        return True

    def _find_matching_entries(self, query: str) -> List[Tuple[Dict[str, Any], float]]:
        """Finds matching files or folders scoring above 65 with RapidFuzz."""
        norm_query = normalize_fs_name(query)
        if not norm_query:
            return []

        results = []
        for entry in self.current_entries:
            score = fuzz.WRatio(norm_query, entry["normalized"])
            if score >= 65:
                results.append((entry, score))

        # Sort descending by score
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _activate_entry(self, entry: Dict[str, Any]) -> None:
        """Opens folder or file based on entry type."""
        path = entry["path"]
        if entry["is_dir"]:
            self._navigate_to(path)
        else:
            self._open_file(path)

    def _navigate_to(self, new_path: str, add_to_history: bool = True) -> None:
        """Navigates to a new folder, records history, and refreshes directory listing."""
        abs_path = os.path.abspath(new_path)
        if not os.path.isdir(abs_path):
            self.speaker.speak("I can't open that.")
            return

        if add_to_history and self.current_path != abs_path:
            self.history.append(self.current_path)

        self.current_path = abs_path
        self.sync_explorer_window(self.current_path)
        self.refresh_directory_contents()
        folder_name = os.path.basename(self.current_path) or self.current_path
        self.speaker.speak(f"Opened {folder_name}.")

    def _open_file(self, file_path: str) -> None:
        """Opens a file with its default Windows application."""
        if not os.path.isfile(file_path):
            self.speaker.speak("I couldn't find that file.")
            return

        try:
            file_name = os.path.basename(file_path)
            norm_name = normalize_fs_name(file_name)
            self.speaker.speak(f"Opening {norm_name}.")
            os.startfile(file_path)
        except Exception as e:
            logger.error(f"Failed to open file {file_path}: {e}")
            self.speaker.speak("I can't open that.")

    def _read_next_entries(self) -> None:
        """Reads up to 10 entries from the current directory."""
        if not self.current_entries:
            self.speaker.speak("Folder is empty.")
            return

        chunk = self.current_entries[self.read_index : self.read_index + 10]
        if not chunk:
            self.speaker.speak("No more entries.")
            return

        names = [normalize_fs_name(e["name"]) for e in chunk]
        read_text = ", ".join(names) + "."
        self.read_index += len(chunk)
        self.speaker.speak(read_text)
