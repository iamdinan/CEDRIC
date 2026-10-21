# Cedric: Voice Task Assistant (Windows)

Cedric is a lightweight, offline-first voice task assistant tailored specifically for Windows 10 and 11. Designed to run quietly in the background at below-normal process priority, Cedric allows hands-free voice control of your desktop, web apps, and file system without disturbing your primary work or draining system resources.

---

## 📖 Project Description

Cedric solves the problem of heavy, cloud-dependent voice assistants by running a **100% local, offline core loop** for wake word detection, speech-to-text, command routing, and speech synthesis. 

### Design Philosophy
- **Resource Conscious:** Idle CPU near 0%, idle RAM <150 MB, and active memory consumption capped under ~400 MB.
- **Below-Normal Priority:** Process runs at Windows `BELOW_NORMAL_PRIORITY_CLASS` via `psutil`, ensuring it never slows down games, compilation, or foreground tasks.
- **Offline Reliability:** Wake word detection, speech recognition, fuzzy matching, and TTS execute locally without requiring internet connectivity. Internet is probed only when a web command is explicitly invoked.
- **Minimal Speech Feedback:** Crisp, concise verbal replies spoken *before* launching applications (e.g., *"Opening YouTube."*).
- **Extensible Configuration:** All voice triggers, target applications, and aliases live in configuration files (`commands.yaml`, `settings.yaml`, `explorer_aliases.yaml`) so new commands can be added without modifying source code.
- **Phase 2 LLM Ready:** Implements unified abstract interfaces (`Router`, `Speaker`, `WakeWordEngine`, `STTEngine`) and structured prompt metadata (`id`, `description`, `parameters`) for seamless future integration with local LLMs (such as Qwen 2.5 or Llama 3.2).

---

## 🌟 Key Features

### 1. Dual Triggering: Wake Word & Push-to-Talk
- **Wake Word ("Cedric"):** 100% offline, local wake word detection powered by Vosk grammar-constrained keyword spotting. Requires zero cloud accounts, zero registration, and zero API keys. (Also supports Picovoice Porcupine if configured).
- **Push-to-Talk Backup (`Ctrl+Alt+Space`):** A global keyboard hotkey allows instant voice input alongside or as a backup to the wake word.
- **Wake Feedback:** Plays an unobtrusive audio beep (`1000 Hz, 150 ms`) signaling that listening is active.

### 2. Fast, Grammar-Constrained Offline STT
- Uses **Vosk** with the lightweight American English model (`vosk-model-small-en-us-0.15`).
- Dynamically generates restricted recognition grammars from registered command names, aliases, and numbers for high accuracy and instant decoding.
- Automatically falls back to open-vocabulary recognition if grammar-constrained recognition returns empty.

### 3. RapidFuzz Command Routing & Normalization
- Normalizes utterances by stripping filler phrases (*"please"*, *"can you"*, *"the"*, *"for me"*), lowercasing, and mapping action synonyms (*"launch"*, *"start"*, *"pull up"* → *"open"*).
- Evaluates utterances against command aliases with sub-millisecond latency:
  - **Score ≥ 85% (High Confidence):** Directly executes the action.
  - **65% ≤ Score < 85% (Unsure):** Prompts for confirmation (*"Did you mean X?"*).
  - **Score < 65% (No Match):** Replies *"Sorry, I didn't get that."*

### 4. Native Windows Launchers & Chrome Tab Reuse
- **Chrome Window Reuse:** Web commands launch in Google Chrome with your default profile, reusing running windows as new tabs via `chrome.exe <url>` instead of opening redundant browser instances.
- **Automated Exe Discovery:** Resolves application paths using an established hierarchy: Configured settings → `shutil.which` → Registry `App Paths` → Start Menu `.lnk` targets → `LOCALAPPDATA`.
- **Existing Window Focusing:** Brings already running application windows to the foreground before attempting to spawn new processes.
- **Windows URI Schemes:** Launches system settings (`ms-settings:`) and media players (`spotify:`).

### 5. File Explorer Voice Navigation Mode
Triggered by saying *"open file explorer"*:
- **Dynamic Vocabulary:** Scans the active directory and rebuilds the Vosk grammar on the fly (up to 500 entries) with background threading.
- **Filesystem Normalization:** Cleans filenames for natural speech by splitting camelCase (`MyReport` → *"my report"*), separating digits (`Document2026` → *"document 2026"*), stripping extensions, and replacing separators.
- **Window Synchronization:** Navigates the active Windows File Explorer window via the `Shell.Application` COM interface (`pywin32`), with automatic fallback to `explorer.exe`.
- **Ambiguity Resolution:** When multiple files or directories score closely, Cedric reads numbered options (*"Three matches. One, draft A. Two, draft B..."*) and responds to *"one"*, *"two"*, or *"none"*.
- **History & Jumps:** Supports *"go back"*, *"go up"*, *"go to desktop/downloads/c drive"*, *"read this folder"*, and *"show more"*.
- **Inactivity Timeout:** Automatically exits the mode after 15 seconds of silence.

### 6. Acoustic Isolation (No Self-Hearing)
- Automatically pauses the microphone capture stream while Cedric speaks via Windows SAPI5 (`pyttsx3`) and drains lingering buffer frames before resuming.

---

## 🏛️ State Machine Flow

```
                      +-----------------------------+
                      |            IDLE             |
                      | (Listening for Wake Word or |
                      |    Push-to-Talk Hotkey)     |
                      +--------------+--------------+
                                     |
                          Wake Word or Hotkey
                                     v
                      +-----------------------------+
                      |          LISTENING          |
                      |  (Beep, 16kHz STT Capture,  |
                      |     5s silence timeout)     |
                      +--------------+--------------+
                                     |
                                 Utterance
                                     v
                      +-----------------------------+
                      |           ROUTING           |
                      | (Rapidfuzz Match & Scoring) |
                      +--------------+--------------+
                                     |
         +---------------------------+---------------------------+
         | (Score >= 85%)            | (65% <= Score < 85%)      | (Score < 65%)
         v                           v                           v
+------------------+       +-------------------+       +--------------------+
| EXECUTE ACTION   |       |   CONFIRMATION    |       |   NO MATCH REPLY   |
| Speak reply &    |       | "Did you mean X?" |       | "Sorry, I didn't   |
| launch target    |       |   (Wait Yes/No)   |       |     get that"      |
+--------+---------+       +---------+---------+       +---------+----------+
         |                           |                           |
         |                           v                           |
         |                +--------------------+                 |
         |                | Yes -> Execute     |                 |
         |                | No  -> Cancel      |                 |
         |                +----------+---------+                 |
         |                           |                           |
         +---------------------------+---------------------------+
                                     |
                                     v
                                   IDLE
                                     |
                          "open file explorer"
                                     v
                      +-----------------------------+
                      |     EXPLORER_NAV MODE       |
                      | (Dynamic vocabulary, COM    |
                      | window sync, ambiguity,     |
                      | back/up, 15s inactivity)    |
                      +-----------------------------+
```

---

## 📁 Project Structure

```
CEDRIC/
├── run.py                               # Top-level application entry point
├── requirements.txt                     # Python package dependencies
├── README.md                            # Project documentation
├── CEDRIC_SPEC.md                       # Phase 1 specification
├── cedric/
│   ├── main.py                          # State machine and orchestrator
│   ├── config/
│   │   ├── commands.yaml                # 15 Phase 1 commands + Phase 2 LLM prompt hooks
│   │   ├── settings.yaml                # Hotkeys, thresholds, timeouts, discovered paths
│   │   └── explorer_aliases.yaml        # Explorer shortcuts & custom spoken aliases
│   ├── core/
│   │   ├── actions.py                   # Launchers (Chrome tab reuse, exe, URI, window focus)
│   │   ├── audio.py                     # sounddevice 16 kHz stream, queue, wake beep
│   │   ├── net.py                       # Fast TCP connectivity check (10s cached)
│   │   ├── priority.py                  # Process priority management (below-normal)
│   │   ├── registry.py                  # Command registry loader and phrase builder
│   │   ├── router.py                    # RapidFuzz fuzzy matcher & text normalizer
│   │   ├── stt.py                       # Vosk STT (grammar-restricted + open-vocab fallback)
│   │   ├── tts.py                       # pyttsx3 Windows SAPI5 speaker
│   │   └── wakeword.py                  # VoskWakeWordEngine + PorcupineEngine + PushToTalkTrigger
│   └── modes/
│       └── explorer_nav.py              # File Explorer voice navigation mode
├── models/
│   └── vosk-model-small-en-us-0.15/     # Local Vosk offline speech model
├── scripts/
│   └── setup_autostart.py               # Silent background Windows logon installer
└── tests/
    ├── test_wakeword.py                 # Unit tests for Vosk wake word & keyword matching
    ├── test_normalization.py            # Unit tests for text & filename cleaning
    ├── test_matching.py                 # Unit tests for router matching & thresholds
    ├── test_registry.py                 # Unit tests for commands.yaml schema
    ├── test_explorer.py                 # Unit tests for Explorer mode & ambiguity
    └── replay_tool.py                   # Replay tool for batch text and WAV testing
```

---

## 🚀 Setup & Installation Instructions

### Step 1: Prerequisites
- **Operating System:** Windows 10 or Windows 11 (64-bit)
- **Python:** Python 3.11 or higher
- **Audio Device:** Built-in laptop microphone or USB microphone

### Step 2: Environment Setup
A virtual environment has been created in `.venv`. To activate or recreate it:

```powershell
# Navigate to project directory
cd C:\Users\DELL\Desktop\Dinan\Projects\CEDRIC

# Create virtual environment (if not already present)
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
.\.venv\Scripts\pip install -r requirements.txt
```

### Step 3: Offline Vosk Speech Model
The lightweight English model (`vosk-model-small-en-us-0.15`) is bundled directly in:
`models/vosk-model-small-en-us-0.15/`
and mirrored in `~/.cache/vosk/`. Vosk loads this model automatically—**no additional downloads are needed**.

### Step 4: Wake Word Engine Configuration (100% Offline by Default)
Cedric listens for the wake word **"Cedric"** hands-free:
- **Default Engine (`vosk`):** Uses the local bundled Vosk model with grammar-constrained keyword detection. **Requires zero setup, zero accounts, and 0 external API keys.**
- **Push-to-Talk Trigger:** You can also press <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Space</kbd> at any time to instantly trigger voice input.
- **Picovoice Porcupine (Optional Alternative):** If you already have a Picovoice Porcupine key and `.ppn` model, set `engine: porcupine` in `cedric/config/settings.yaml` and set `PICOVOICE_ACCESS_KEY` in your environment. If Porcupine is unconfigured or unavailable, Cedric seamlessly falls back to the offline Vosk wake word engine.

---

## 🎮 Usage Guide

### Starting Cedric
To run Cedric in the foreground:
```powershell
.\.venv\Scripts\python run.py
```

### Triggering Voice Input
1. **By Wake Word:** Say *"Cedric"*. Cedric will emit a wake beep and verbally acknowledge with a rotating reply (*"Yes?"*, *"Listening."*, or *"Go ahead."*).
2. **By Hotkey:** Press `Ctrl+Alt+Space` to trigger voice input immediately with verbal acknowledgment.
3. **Speak your request clearly:** (e.g., *"open github"*, *"open terminal"*). Cedric speaks out loud the action he is taking (*"Opening GitHub."*) before launching it. If he doesn't understand, he explicitly informs you what he heard (*"Sorry, I didn't get that. I heard '...'."*).

### Supported Commands

| # | Spoken Phrases | Action | Type | Internet |
|---|---|---|---|---|
| 1 | *"open youtube"*, *"youtube"* | Opens YouTube in Chrome (new tab) | URL | Yes |
| 2 | *"open file explorer"*, *"explorer"*, *"files"* | Enters File Explorer Navigation Mode | Special | No |
| 3 | *"open visual studio code"*, *"vs code"*, *"code editor"* | Launches or focuses VS Code | Exe | No |
| 4 | *"open github"*, *"github"* | Opens GitHub in Chrome | URL | Yes |
| 5 | *"open gmail"*, *"mail"*, *"email"* | Opens Gmail in Chrome | URL | Yes |
| 6 | *"open whatsapp"* | Opens WhatsApp Web in Chrome | URL | Yes |
| 7 | *"open claude"* | Opens Claude AI in Chrome | URL | Yes |
| 8 | *"open gemini"* | Opens Google Gemini in Chrome | URL | Yes |
| 9 | *"open chatgpt"*, *"chat gpt"* | Opens ChatGPT in Chrome | URL | Yes |
| 10 | *"open settings"*, *"windows settings"* | Opens Windows Settings | URI | No |
| 11 | *"open terminal"*, *"command line"*, *"new terminal"* | Launches Windows Terminal (`wt.exe`) | Exe | No |
| 12 | *"open antigravity"* | Launches or focuses Antigravity | Exe | No |
| 13 | *"open opencode"* | Launches or focuses OpenCode desktop | Exe | No |
| 14 | *"open postman"* | Launches or focuses Postman | Exe | No |
| 15 | *"open spotify"* | Launches or focuses Spotify | URI / Exe | No |

#### Built-In Meta Commands
- *"what can you do"* / *"help"* : Speaks a summary of supported commands.
- *"repeat that"* : Repeats the last spoken response.
- *"cancel"* / *"never mind"* : Cancels active listening or pending confirmation.
- *"stop listening"* : Enters sleep mode until awakened by `Ctrl+Alt+Space`.

---

## 📂 File Explorer Voice Navigation Guide

Entering the mode via *"open file explorer"* initializes navigation at your home folder (or configured start path).

| What to Say | Effect |
|---|---|
| Folder name, or *"open <folder>"* / *"go to <folder>"* | Enters that folder |
| File name, or *"open <file>"* | Opens the file in its default application |
| *"go back"* | Navigates to the previous folder in your session history |
| *"go up"* | Moves up to the parent directory |
| *"go to desktop"* / *"downloads"* / *"documents"* / *"c drive"* | Jumps directly to standard user folders |
| *"read this folder"* | Speaks the names of the first 10 items |
| *"show more"* | Speaks the next 10 items |
| *"one"*, *"two"*, *"three"*, or *"none"* | Resolves ambiguous matches when prompted |
| *"exit"* / *"done"* / *"close"* | Exits Explorer mode and returns to IDLE |

---

## 🧪 Testing & Verification

### Running the Pytest Suite
Cedric includes comprehensive unit tests covering normalization, fuzzy matching, command registry schema, and Explorer ambiguity resolution.

```powershell
.\.venv\Scripts\pytest tests -v
```
*(All 16 unit tests execute and pass in ~1 second).*

### Replay & Router Evaluation Tool
Test utterances, fuzzy scores, and latency without speaking:

```powershell
# Run the built-in sample query suite:
.\.venv\Scripts\python tests/replay_tool.py

# Test a custom spoken phrase:
.\.venv\Scripts\python tests/replay_tool.py --text "can you please open spotify"

# Replay a recorded 16 kHz WAV audio file:
.\.venv\Scripts\python tests/replay_tool.py --wav sample.wav
```

---

## ⚙️ Windows Auto-Start Configuration

To have Cedric automatically run silently in the background whenever you log into Windows (using `pythonw.exe` without an open terminal window):

```powershell
# Install Cedric to Windows Startup:
.\.venv\Scripts\python scripts/setup_autostart.py --install

# Uninstall Cedric from Windows Startup:
.\.venv\Scripts\python scripts/setup_autostart.py --uninstall
```

---

## 🔍 Discovered Application Targets on This Machine

Application executables have been discovered and saved into `cedric/config/settings.yaml`:

- **Google Chrome:** `C:\Program Files\Google\Chrome\Application\chrome.exe`
- **Visual Studio Code:** `C:\Users\DELL\AppData\Local\Programs\Microsoft VS Code\Code.exe`
- **Antigravity:** `C:\Users\DELL\AppData\Local\Programs\antigravity\Antigravity.exe`
- **OpenCode Desktop:** `C:\Users\DELL\AppData\Local\Programs\@opencode-aidesktop\OpenCode.exe`
- **Postman:** `C:\Users\DELL\AppData\Local\Postman\Postman.exe`
- **Spotify:** `C:\Users\DELL\AppData\Roaming\Spotify\Spotify.exe` (and `spotify:` URI)
- **Windows Terminal:** `wt.exe` (via WindowsApps)

---

## 📝 Logging & Diagnostics

Cedric writes structured, plain-text logs to `logs/cedric.log` using a rotating file handler (5 MB max, 5 backups). Every utterance records:
- Raw transcribed text
- Normalized text
- Match status and confidence score
- Executed action
- Routing and execution latency in milliseconds

---

## 🧪 Testing

Run the full automated test suite:
```powershell
.\.venv\Scripts\pytest -v
```

Unit tests cover:
- **Wake Word (`test_wakeword.py`):** Vosk wake word engine initialization, keyword spotter, and silent frame handling
- **Text Normalization (`test_normalization.py`):** Spoken text cleaning, synonym expansion, and filename normalization
- **Router Matching (`test_matching.py`):** RapidFuzz scoring, confidence thresholds, and confirmation logic
- **Registry (`test_registry.py`):** YAML schema integrity and action validation
- **Explorer Navigation (`test_explorer.py`):** Dynamic vocabulary, path resolution, and ambiguity handling

