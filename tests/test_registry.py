"""Unit tests for commands registry loading and validation."""

import os
from pathlib import Path
import pytest
from cedric.core.registry import CommandRegistry

COMMANDS_FILE = Path(__file__).resolve().parent.parent / "cedric" / "config" / "commands.yaml"


def test_registry_loading():
    registry = CommandRegistry(str(COMMANDS_FILE))
    commands = registry.all_commands()
    assert len(commands) == 15, f"Expected 15 commands, got {len(commands)}"


def test_registry_expected_command_ids():
    registry = CommandRegistry(str(COMMANDS_FILE))
    expected_ids = {
        "youtube", "file_explorer", "vscode", "github", "mail",
        "whatsapp", "claude", "gemini", "chatgpt", "settings",
        "terminal", "antigravity", "opencode", "postman", "spotify"
    }
    actual_ids = {cmd.id for cmd in registry.all_commands()}
    assert actual_ids == expected_ids


def test_registry_command_attributes():
    registry = CommandRegistry(str(COMMANDS_FILE))
    yt = registry.get("youtube")
    assert yt is not None
    assert yt.type == "url"
    assert yt.needs_internet is True
    assert yt.browser == "chrome"
    assert "https://www.youtube.com" in yt.target
    assert isinstance(yt.description, str)
    assert isinstance(yt.parameters, dict)

    explorer = registry.get("file_explorer")
    assert explorer is not None
    assert explorer.type == "special"
    assert explorer.needs_internet is False

    settings = registry.get("settings")
    assert settings is not None
    assert settings.type == "uri"
    assert settings.target == "ms-settings:"


def test_registry_spoken_phrases():
    registry = CommandRegistry(str(COMMANDS_FILE))
    phrases = registry.get_all_spoken_phrases()
    assert "youtube" in phrases
    assert "visual studio code" in phrases
    assert "file explorer" in phrases
    assert "whatsapp" in phrases

