"""Unit tests for VoskWakeWordEngine and keyword detection."""

import pytest
from cedric.core.wakeword import VoskWakeWordEngine


def test_vosk_wakeword_init():
    engine = VoskWakeWordEngine(keyword="cedric")
    assert engine.is_available is True
    engine.close()


def test_vosk_keyword_matching():
    engine = VoskWakeWordEngine(keyword="cedric")
    assert engine._matches("cedric") is True
    assert engine._matches("hey cedric") is True
    assert engine._matches("cedrick") is True
    assert engine._matches("hello world") is False
    assert engine._matches("") is False
    assert engine._matches("computer") is False
    engine.close()


def test_vosk_process_silent_frame():
    engine = VoskWakeWordEngine(keyword="cedric")
    silent_frame = b"\x00" * 1024  # 512 samples of 16-bit PCM
    result = engine.process_frame(silent_frame)
    assert result is False
    engine.close()
