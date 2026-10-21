"""Unit tests for RuleRouter matching, confidence thresholds, and meta commands."""

from pathlib import Path
import pytest
from cedric.core.registry import CommandRegistry
from cedric.core.router import RuleRouter, RouterContext

COMMANDS_FILE = Path(__file__).resolve().parent.parent / "cedric" / "config" / "commands.yaml"


@pytest.fixture
def router():
    registry = CommandRegistry(str(COMMANDS_FILE))
    return RuleRouter(registry, high_confidence=85.0, low_confidence=65.0)


def test_high_confidence_matches(router):
    cases = [
        ("open youtube", "youtube"),
        ("launch visual studio code", "vscode"),
        ("open github", "github"),
        ("please start spotify", "spotify"),
        ("open a new terminal", "terminal"),
        ("start opencode", "opencode"),
        ("can you open antigravity", "antigravity"),
        ("open postman", "postman"),
        ("pull up claude", "claude"),
        ("open gemini", "gemini"),
        ("open windows settings", "settings"),
        ("open file explorer", "file_explorer"),
    ]
    for text, expected_id in cases:
        res = router.route(text)
        assert res.status == "matched", f"Failed for '{text}': got {res.status} with score {res.confidence}"
        assert res.command.id == expected_id, f"Expected {expected_id}, got {res.command.id} for '{text}'"
        assert res.confidence >= 85.0


def test_meta_commands(router):
    meta_cases = [
        ("cancel", "cancel"),
        ("never mind", "cancel"),
        ("repeat that", "repeat_that"),
        ("say that again", "repeat_that"),
        ("stop listening", "stop_listening"),
        ("what can you do", "what_can_you_do"),
        ("help", "what_can_you_do"),
    ]
    for text, expected_meta in meta_cases:
        res = router.route(text)
        assert res.status == "meta", f"Expected meta for '{text}', got {res.status}"
        assert res.meta_action == expected_meta


def test_no_match(router):
    res = router.route("fly me to the moon and bake a potato")
    assert res.status == "no_match"
    assert res.confidence < 65.0

    # Ensure open-prefixed unknown phrases do not falsely match file explorer
    for bogus in ("open did up", "open dog", "open car", "open water"):
        res = router.route(bogus)
        assert res.command is None or res.command.id != "file_explorer"
        assert res.confidence < 85.0


def test_router_context():
    context = RouterContext()
    context.update(action="youtube", utterance="open youtube", reply="Opening YouTube.")
    assert context.last_action == "youtube"
    assert context.last_utterance == "open youtube"
    assert context.last_reply == "Opening YouTube."

