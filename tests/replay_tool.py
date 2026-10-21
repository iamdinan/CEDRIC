"""Replay tool for testing Cedric's STT and command router.
Can feed recorded WAV audio files or text lines through the router.

Usage:
    python tests/replay_tool.py --text "open youtube"
    python tests/replay_tool.py --text-file queries.txt
    python tests/replay_tool.py --wav sample.wav
"""

import sys
import time
import wave
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cedric.core.registry import CommandRegistry
from cedric.core.router import RuleRouter, RouterContext, normalize_utterance
from cedric.core.stt import VoskSTT


def replay_text_line(router: RuleRouter, line: str) -> None:
    text = line.strip()
    if not text or text.startswith("#"):
        return

    start = time.perf_counter()
    result = router.route(text)
    duration_ms = (time.perf_counter() - start) * 1000

    print(f"\n--- Utterance: '{text}' ---")
    print(f"  Normalized:  '{normalize_utterance(text)}'")
    print(f"  Status:      {result.status}")
    print(f"  Confidence:  {result.confidence:.1f}%")
    if result.command:
        print(f"  Command ID:  {result.command.id} ({result.command.name})")
        print(f"  Action Type: {result.command.type} -> {result.command.target}")
        print(f"  Reply:       '{result.command.reply}'")
    elif result.meta_action:
        print(f"  Meta Action: {result.meta_action}")
    elif result.clarification_prompt:
        print(f"  Prompt:      '{result.clarification_prompt}'")
    print(f"  Latency:     {duration_ms:.2f} ms")


def replay_wav_file(wav_path: str, router: RuleRouter) -> None:
    print(f"Replaying audio file: {wav_path}")
    if not Path(wav_path).is_file():
        print(f"Error: WAV file not found: {wav_path}")
        return

    stt = VoskSTT()
    from vosk import KaldiRecognizer
    if stt.model is None:
        print("Error: Vosk model not loaded.")
        return

    wf = wave.open(wav_path, "rb")
    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
        print("Warning: Audio file must be WAV format mono PCM 16000Hz 16-bit.")

    rec = KaldiRecognizer(stt.model, wf.getframerate())
    transcript = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            pass

    import json
    res = json.loads(rec.FinalResult())
    transcript = res.get("text", "")
    print(f"STT Transcript: '{transcript}'")
    if transcript:
        replay_text_line(router, transcript)
    else:
        print("No speech detected in audio file.")


def main():
    parser = argparse.ArgumentParser(description="Cedric Router & STT Replay Tool")
    parser.add_argument("--text", type=str, help="Single utterance text to test")
    parser.add_argument("--text-file", type=str, help="File containing utterances (one per line)")
    parser.add_argument("--wav", type=str, help="WAV audio file to process through STT and Router")

    args = parser.parse_args()

    commands_file = PROJECT_ROOT / "cedric" / "config" / "commands.yaml"
    registry = CommandRegistry(str(commands_file))
    router = RuleRouter(registry)

    if args.text:
        replay_text_line(router, args.text)

    elif args.text_file:
        file_path = Path(args.text_file)
        if not file_path.is_file():
            print(f"Error: File not found: {file_path}")
            return
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                replay_text_line(router, line)

    elif args.wav:
        replay_wav_file(args.wav, router)

    else:
        # Default sample suite
        sample_queries = [
            "open youtube",
            "can you launch visual studio code",
            "please open spotify",
            "start opencode",
            "open the terminal",
            "open windows settings",
            "launch antigravity",
            "open postman",
            "open whatsapp",
            "open file explorer",
            "what can you do",
            "repeat that",
            "cancel",
            "fly to saturn",
        ]
        print("Running default sample test utterances through RuleRouter:")
        for q in sample_queries:
            replay_text_line(router, q)


if __name__ == "__main__":
    main()

