"""Command registry loader and manager."""

import os
import yaml
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger("cedric.registry")


class CommandEntry:
    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", self.id)
        self.description: str = data.get("description", "")
        self.parameters: Dict[str, Any] = data.get("parameters", {})
        self.aliases: List[str] = [a.lower().strip() for a in data.get("aliases", [])]
        self.type: str = data.get("type", "exe")
        self.target: str = data.get("target", "")
        self.browser: Optional[str] = data.get("browser")
        self.fallback_exe: Optional[str] = data.get("fallback_exe")
        self.needs_internet: bool = data.get("needs_internet", False)
        self.reply: str = data.get("reply", f"Opening {self.name}.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "aliases": self.aliases,
            "type": self.type,
            "target": self.target,
            "browser": self.browser,
            "fallback_exe": self.fallback_exe,
            "needs_internet": self.needs_internet,
            "reply": self.reply,
        }


class CommandRegistry:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.commands: Dict[str, CommandEntry] = {}
        self.load()

    def load(self) -> None:
        """Loads or reloads commands from the YAML file."""
        if not os.path.isfile(self.config_path):
            raise FileNotFoundError(f"Command registry file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw_entries = yaml.safe_load(f) or []

        self.commands.clear()
        for entry in raw_entries:
            cmd = CommandEntry(entry)
            if cmd.id:
                self.commands[cmd.id] = cmd

        logger.info(f"Loaded {len(self.commands)} commands from {self.config_path}")

    def get(self, cmd_id: str) -> Optional[CommandEntry]:
        return self.commands.get(cmd_id)

    def all_commands(self) -> List[CommandEntry]:
        return list(self.commands.values())

    def get_all_spoken_phrases(self) -> List[str]:
        """Returns all command names and aliases for building STT grammar and matching."""
        phrases = set()
        for cmd in self.commands.values():
            phrases.add(cmd.name.lower())
            for alias in cmd.aliases:
                phrases.add(alias.lower())
        return sorted(list(phrases))

