"""Unit tests for utterance and filesystem name normalization."""

import pytest
from cedric.core.router import normalize_utterance
from cedric.modes.explorer_nav import normalize_fs_name


def test_normalize_utterance_filler_words():
    assert normalize_utterance("please open youtube") == "open youtube"
    assert normalize_utterance("can you open spotify") == "open spotify"
    assert normalize_utterance("could you please open the settings") == "open settings"
    assert normalize_utterance("hey cedric open terminal") == "open terminal"
    assert normalize_utterance("open the chrome for me") == "open chrome"


def test_normalize_utterance_synonyms():
    assert normalize_utterance("launch youtube") == "open youtube"
    assert normalize_utterance("start vs code") == "open vs code"
    assert normalize_utterance("open up github") == "open github"
    assert normalize_utterance("pull up chatgpt") == "open chatgpt"
    assert normalize_utterance("run terminal") == "open terminal"


def test_normalize_utterance_punctuation_and_spaces():
    assert normalize_utterance("   Open,   YouTube!   ") == "open youtube"
    assert normalize_utterance("what's up???") == "what s up"
    assert normalize_utterance("") == ""


def test_normalize_fs_name_extensions_and_delimiters():
    assert normalize_fs_name("Final_Report_v2.pdf") == "final report v2"
    assert normalize_fs_name("thesis-final-draft.docx") == "thesis final draft"
    assert normalize_fs_name("archive.tar.gz") == "archive tar"


def test_normalize_fs_name_camelcase():
    assert normalize_fs_name("MyImportantDocument.txt") == "my important document"
    assert normalize_fs_name("CEDRICProjectFiles") == "cedric project files"
    assert normalize_fs_name("AnnualReport2026.xlsx") == "annual report 2026"

