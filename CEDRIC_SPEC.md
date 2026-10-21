# Cedric: Voice Task Assistant (Windows) — Build Spec

Hand this file to the coding agent. Build **Phase 1 only**. Phase 2 (LLM) is described so Phase 1 leaves the right hooks, but must not be implemented yet.

## 1. Goals and constraints

- Windows 10/11 laptop, Intel i5, integrated graphics, 8 GB RAM.
- Must not disturb other work: idle CPU near zero, total RAM under ~400 MB in Phase 1.
- Process runs at **below-normal priority** (psutil `BELOW_NORMAL_PRIORITY_CLASS`).
- Wake word: **"Cedric"**, via **Porcupine** (Picovoice). Built-in laptop mic.
- Fully offline core loop: wake word, speech-to-text, command matching, speech output. Internet only needed for web commands. If offline and a web command is requested, say "No internet connection" and do nothing.
- Replies are minimal. Say "Opening YouTube." then act. Confirm only destructive actions (none in the current command list).
- All commands live in a config file so adding one never needs code changes.

## 2. Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Audio input | `sounddevice` | 16 kHz mono, 512-sample frames for Porcupine / Vosk |
| Wake word | `VoskWakeWordEngine` (offline default, no key required) / `pvporcupine` + custom `cedric_windows.ppn` | Vosk grammar-restricted keyword spotter is default; Porcupine is optional alternative behind `WakeWordEngine`. |
| Push-to-talk | `keyboard` or `pynput` global hotkey (default `Ctrl+Alt+Space`) | Backup trigger, same pipeline after trigger |
| STT | `vosk` with a small English model (`vosk-model-small-en-us`) | Use grammar-restricted recognition (see section 5) |
| Matching | `rapidfuzz` | |
| TTS | `pyttsx3` (Windows SAPI5) | Piper is an optional later upgrade behind the same interface |
| Windows APIs | `pywin32` | Explorer navigation, app launch |
| Process priority, RAM stats | `psutil` | |
| Config | YAML (`pyyaml`) | |
| Logging | stdlib `logging`, rotating file | |

## 3. Module layout

```
cedric/
  main.py                # entry point, state machine
  config/
    commands.yaml        # command registry
    settings.yaml        # hotkey, thresholds, timeouts, paths
  core/
    audio.py             # mic stream, frame queue
    wakeword.py          # WakeWordEngine interface + VoskWakeWordEngine + PorcupineEngine
    stt.py               # Vosk wrapper (open vocab + grammar modes)
    tts.py               # Speaker interface + Pyttsx3Speaker
    router.py            # Router interface + RuleRouter (LLMRouter later)
    registry.py          # loads commands.yaml, exposes actions
    actions.py           # launchers: url, exe, uri, shell
    net.py               # is_online()
    priority.py          # set below-normal priority
  modes/
    explorer_nav.py      # file explorer navigation mode
  tests/
  README.md
```

Keep `WakeWordEngine`, `Speaker`, and `Router` as small interfaces so engines can be swapped (for example openWakeWord later, Piper later, LLM router in Phase 2).

## 4. State machine

```
IDLE (only wake word listening)
  └─ wake word or hotkey ─► LISTENING (beep, start STT, 5 s silence timeout)
        └─ utterance ─► ROUTING
              ├─ matched (confidence ≥ high) ─► speak reply, execute ─► IDLE
              ├─ unsure (between low and high) ─► speak "Did you mean X?" ─► LISTENING (yes/no)
              ├─ no match ─► speak "Sorry, I didn't get that" ─► IDLE
              └─ "open file explorer" ─► EXPLORER_NAV mode
```

- A short beep on wake so the user knows it is listening.
- STT runs only in LISTENING and EXPLORER_NAV. In IDLE only Porcupine runs.
- The assistant must not hear its own TTS: pause the wake word and STT while speaking.
- Meta commands handled by the router: `cancel`, `repeat that`, `stop listening` (go IDLE and pause until hotkey), `what can you do` (list command names from the registry).

## 5. Speech recognition details

- Build the Vosk **grammar** from all command phrases and aliases in `commands.yaml` (plus meta commands and numbers one to nine). A restricted grammar greatly improves accuracy and speed.
- If grammar recognition returns nothing usable, retry once in open-vocabulary mode, then fuzzy match the result.
- Normalize before matching: lowercase, strip filler words ("please", "can you", "the"), expand synonyms (`launch`, `start`, `open up`, `pull up` → `open`).
- Thresholds in `settings.yaml`: `high_confidence: 85`, `low_confidence: 65` (rapidfuzz scores, tune with logs).

## 6. Command registry (`commands.yaml`)

Schema per entry:

```yaml
- id: youtube
  name: YouTube
  aliases: ["youtube", "you tube"]
  type: url            # url | exe | uri | shell
  target: "https://www.youtube.com"
  browser: chrome      # only for url type; omit to use default browser
  needs_internet: true
  reply: "Opening YouTube."
```

All 15 commands:

| # | id | Spoken names | Type | Target | Internet |
|---|---|---|---|---|---|
| 1 | youtube | youtube | url (Chrome) | https://www.youtube.com | yes |
| 2 | file_explorer | file explorer, explorer, files | special | enters explorer navigation mode (section 8) | no |
| 3 | vscode | vs code, vscode, visual studio code, code editor | exe | `code` (resolve full path) | no |
| 4 | github | github, git hub | url (Chrome) | https://github.com | yes |
| 5 | mail | mail, mails, gmail, email | url (Chrome) | https://mail.google.com | yes |
| 6 | whatsapp | whatsapp, whats app | url (Chrome) | https://web.whatsapp.com | yes |
| 7 | claude | claude, clawed, cloud | url (Chrome) | https://claude.ai | yes |
| 8 | gemini | gemini | url (Chrome) | https://gemini.google.com | yes |
| 9 | chatgpt | chat gpt, chatgpt | url (Chrome) | https://chatgpt.com | yes |
| 10 | settings | settings, windows settings | uri | `ms-settings:` | no |
| 11 | terminal | terminal, new terminal, command line | exe | `wt.exe` | no |
| 12 | antigravity | antigravity, anti gravity | exe | discover path | no |
| 13 | opencode | opencode, open code | exe | **OpenCode desktop app**, discover path | no |
| 14 | postman | postman, post man | exe | discover path | no |
| 15 | spotify | spotify | uri | `spotify:` (fallback: exe) | no |

Notes:
- Phrase forms: "open X", "launch X", "start X", "open a new terminal", or just "X".
- **Chrome**: use the **default profile** and reuse the running window (launch `chrome.exe <url>`, which opens a new tab in the existing window). Locate chrome via registry `App Paths\chrome.exe`, fall back to `webbrowser`.
- **Path discovery for exe apps** (Antigravity, OpenCode desktop, Postman, Spotify, VS Code): resolve in order: `shutil.which`, registry App Paths, Start Menu `.lnk` shortcuts, `shell:AppsFolder` AUMID. On first run write resolved paths to `settings.yaml`, print them, and ask the user to confirm before relying on them. If an app cannot be found, speak "I couldn't find X" and log the attempts.
- If an app is already running, prefer focusing its window over launching a second instance where practical (optional).

## 7. Replies and feedback

- Reply template per command, spoken **before** launching (for example "Opening Postman.").
- Errors: "I couldn't open X." plus details in the log only.
- No internet and `needs_internet: true`: "No internet connection."
- TTS rate and volume in `settings.yaml`.

## 8. File Explorer navigation mode (`modes/explorer_nav.py`)

Entering: "open file explorer" opens Explorer at a configurable start folder (default: user home) and enters the mode. Track `current_path`.

Voice commands inside the mode:

| Say | Effect |
|---|---|
| a folder name, or "open <folder>" / "go to <folder>" | enter that folder |
| a file name, or "open <file>" | open the file with its default app |
| "go back" | previous location in history |
| "go up" | parent folder |
| "go to <drive/known folder>" (C drive, D drive, downloads, documents, desktop, pictures) | jump |
| "read this folder" | speak the first 10 entries |
| "show more" | next 10 entries |
| "exit" / "done" or 15 s inactivity | leave the mode, speak "Done." |

Implementation requirements:
1. **Dynamic vocabulary:** on every folder change, list the directory and rebuild the Vosk grammar from the entry names plus the mode's control words. Run this off the main audio thread and cap at ~500 entries (if more, fall back to open-vocabulary plus fuzzy match against the listing).
2. **Name normalization for matching:** lowercase; replace `_`, `-`, `.` with spaces; strip extensions; split camelCase; collapse whitespace. `Final_Report_v2.pdf` is matched by "final report v2" or "final report".
3. **Ambiguity:** if several entries score close, speak numbered options (max 5): "Three matches. One, final report. Two, final report draft. Three, final report two." The user says "one", "two", or "none".
4. **Navigate the existing Explorer window** via the `Shell.Application` COM interface (`pywin32`) so one window follows the user. Verify it works on the user's Windows version. Fallback: open a new Explorer window per step with `explorer.exe <path>`. Record which method is active in logs.
5. Skip hidden and system entries by default (setting to include).
6. **Alias file** `explorer_aliases.yaml` for unspeakable names: `my thesis: "D:/Uni/thesis_final_v7_REAL.docx"`.
7. Stay inside paths that exist; handle permission errors by speaking "I can't open that."
8. Optional extra after the core works: "find <name>" searching an index of configured root folders.

## 9. Offline/online handling

- `net.is_online()`: short TCP connect (for example 1.1.1.1:443, 1 s timeout), cached for 10 s.
- Core loop never requires internet (confirm Porcupine's key validation behavior and document it; if it requires connectivity at startup, handle failure with a clear spoken/logged message and a push-to-talk fallback).

## 10. Process behavior

- On startup: set below-normal priority, load models once, then drop to the idle loop.
- Auto-start at logon with Task Scheduler (or a Startup folder shortcut) running `pythonw.exe` so no console window appears.
- System tray icon is optional (pause/resume, quit). Not required for Phase 1.
- Log every utterance: raw text, normalized text, match, score, action, timing. Rotating file, plain text.
- Graceful handling of: no mic, mic in use, device change, Porcupine key missing.

## 11. Performance targets

- Idle: under 2% of one core, under ~150 MB RAM.
- Active (listening + recognizing): under ~400 MB RAM.
- Utterance end to action start: under 1 s for launches.
- Wake word: aim for under 1 false trigger per hour in a quiet room. Expose `sensitivity` in settings and test values from 0.5 to 0.8.

## 12. Milestones and acceptance checks

1. **Core loop**: push-to-talk, Vosk STT, TTS, commands 1, 3, 10. Accept: "open youtube" speaks and opens in Chrome.
2. **Registry**: full 15 commands from YAML with aliases, path discovery, internet check. Accept: every command works by voice; unknown app path yields a spoken error.
3. **Wake word**: Porcupine with "Cedric", beep, self-hearing prevention, sensitivity setting. Accept: works from about 1 m with built-in mic; documented false-trigger test.
4. **Explorer mode**: dynamic vocabulary, ambiguity handling, back/up, aliases. Accept: reach a file five folders deep by voice.
5. **Polish**: logging, priority, auto-start, error handling, README with setup steps (Picovoice key, model download, ppn file).
6. **Tests**: unit tests for normalization, fuzzy matching, registry loading, Explorer matching; a replay tool that feeds recorded WAVs or text lines through the router.

## 13. Phase 2 (design only — do not build yet)

Leave these hooks in Phase 1:
- `Router` interface: `route(text, context) -> Action | Clarification | None`. `RuleRouter` is the Phase 1 implementation.
- Each registry command exposes `id`, description, and parameters (empty for now) so it can be serialized into an LLM prompt later.
- A `context` object holding last action, current Explorer path, and last utterance, for follow-ups.

Planned Phase 2 behavior, for reference:
- The rule router runs first. The LLM is called only when rule confidence is below `low_confidence`.
- Model: small instruct model (Qwen2.5 1.5B or Llama 3.2 1B/3B, Q4) via llama.cpp or Ollama, loaded on demand, unloaded after 1 to 2 minutes idle, threads capped at 3 to 4.
- Output is **JSON only**, grammar-constrained, validated against the registry; the model never executes anything directly.
- Adds: free phrasing, multi-step commands, smarter Explorer requests ("open the latest PDF in downloads"), follow-ups ("close that"), clarifying questions, recognition-error repair, and new actions (reminders, clipboard summary).
- Say "One moment" while the model loads on the first request after idle.

## 14. Open items for the coding agent to resolve and report

- Exact launch targets for Antigravity, OpenCode desktop, Postman, Spotify on this machine.
- Whether Porcupine's AccessKey validation needs internet, and current free-tier limits for custom keywords.
- Whether Shell COM navigation of the existing Explorer window works reliably here.
- Tuned values for wake-word sensitivity and match thresholds from real logs.
