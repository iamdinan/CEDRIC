"""Unit tests for File Explorer voice navigation matching and ambiguity resolution."""

import os
from unittest.mock import MagicMock
import pytest
from cedric.modes.explorer_nav import ExplorerNavMode, normalize_fs_name


class DummySpeaker:
    def __init__(self):
        self.spoken = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def stop(self) -> None:
        pass


class DummySTT:
    def __init__(self):
        self.grammar = None

    def set_grammar(self, phrases):
        self.grammar = phrases


@pytest.fixture
def explorer_nav(tmp_path):
    speaker = DummySpeaker()
    stt = DummySTT()
    nav = ExplorerNavMode(
        speaker=speaker,
        stt_engine=stt,
        start_folder=str(tmp_path),
        inactivity_timeout_sec=15.0,
    )
    return nav, speaker, tmp_path


def test_explorer_nav_matching(explorer_nav):
    nav, speaker, tmp_path = explorer_nav
    (tmp_path / "Final_Report_v2.pdf").write_text("sample")
    (tmp_path / "Budget2026.xlsx").write_text("sample")
    (tmp_path / "Notes.txt").write_text("sample")

    nav.enter()
    assert len(nav.current_entries) == 3

    # Match exact normalized
    matches = nav._find_matching_entries("final report")
    assert len(matches) >= 1
    assert matches[0][0]["name"] == "Final_Report_v2.pdf"

    matches_budget = nav._find_matching_entries("budget 2026")
    assert len(matches_budget) >= 1
    assert matches_budget[0][0]["name"] == "Budget2026.xlsx"


def test_explorer_ambiguity(explorer_nav):
    nav, speaker, tmp_path = explorer_nav
    (tmp_path / "Report_Draft_A.pdf").write_text("sample")
    (tmp_path / "Report_Draft_B.pdf").write_text("sample")
    (tmp_path / "Report_Draft_C.pdf").write_text("sample")

    nav.enter()
    speaker.spoken.clear()

    # Query 'report draft' matches all three closely
    nav.handle_utterance("report draft")
    assert len(nav.ambiguous_options) == 3
    assert len(speaker.spoken) > 0
    assert "Three matches" in speaker.spoken[-1]

    # Select 'two'
    nav.handle_utterance("two")
    assert len(nav.ambiguous_options) == 0


def test_explorer_history_stack(explorer_nav):
    nav, speaker, tmp_path = explorer_nav
    sub1 = tmp_path / "FolderA"
    sub1.mkdir()
    sub2 = sub1 / "FolderB"
    sub2.mkdir()

    nav.enter()
    nav.handle_utterance("FolderA")
    assert nav.current_path == str(sub1)

    nav.handle_utterance("FolderB")
    assert nav.current_path == str(sub2)

    # Go back
    nav.handle_utterance("go back")
    assert nav.current_path == str(sub1)

    # Go up
    nav.handle_utterance("go up")
    assert nav.current_path == str(tmp_path)

