# Cedric: Voice Task Assistant (Windows)

> **Cedric is a lightweight, fully offline Windows voice assistant for hands-free desktop control, app launching, web shortcuts, and file navigation.**

Designed to run quietly in the background at below-normal priority (`BELOW_NORMAL_PRIORITY_CLASS`), Cedric operates with near-zero idle CPU and <150 MB RAM without draining system resources or disturbing foreground tasks.

---

## 🌟 Key Features

- **100% Offline & Private:** Wake word detection, speech recognition (Vosk), command routing, and speech synthesis (SAPI5) execute entirely on your machine.
- **Dual Triggering:** 
  - **Wake Word:** Say *"Cedric"* for hands-free activation (powered by bundled offline Vosk model; Picovoice Porcupine also supported).
  - **Push-to-Talk Hotkey:** Press <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>Space</kbd> anytime.
- **Natural Voice Feedback:**
  - Verbally acknowledges wake-up with rotating replies (*"Yes?"*, *"Listening."*, *"Go ahead."*).
  - Announces tasks out loud before execution (*"Opening GitHub."*).
  - Tells you what was heard on unrecognized speech (*"Sorry, I didn't get that. I heard: ..."*).
  - Acknowledges silence timeouts (*"Nothing heard. Going back to sleep."*).
- **Smart App & Web Launching:** Reuses existing Chrome windows as new tabs via `chrome.exe <url>` instead of spawning duplicate browser windows.
- **Voice File Explorer Navigation:** Hands-free directory jumping, folder traversal, file launching, and ambiguity resolution.
- **Acoustic Isolation:** Automatically pauses microphone capture while Cedric speaks to prevent self-hearing.

---

## 🚀 Quick Start

### 1. Requirements
- Windows 10 or 11 (64-bit)
- Python 3.11+
- Working microphone

### 2. Setup
```powershell
# Navigate to the project root
cd C:\Users\DELL\Desktop\Dinan\Projects\CEDRIC

# Activate existing virtual environment (or run 'python -m venv .venv')
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```
*(The Vosk small English speech model is already pre-bundled in `models/vosk-model-small-en-us-0.15/`—no extra model downloads needed).*

### 3. Run
```powershell
.\.venv\Scripts\python run.py
```

---

## 🎙️ Interaction & Usage

```
User:   "Cedric"
Cedric: [Beep] "Listening."
User:   "Open GitHub"
Cedric: "Opening GitHub." (Opens github.com in Chrome)

User:   "Cedric"
Cedric: "Go ahead."
User:   "Open dog"
Cedric: "Sorry, I didn't get that. I heard: open dog."
```

### Supported Commands

| Category | Spoken Phrases | Action | Internet Required |
|---|---|---|:---:|
| **Web Apps** | *"open youtube"* | Opens YouTube in Chrome | Yes |
| | *"open github"* | Opens GitHub in Chrome | Yes |
| | *"open gmail"* / *"mail"* | Opens Gmail in Chrome | Yes |
| | *"open whatsapp"* | Opens WhatsApp Web in Chrome | Yes |
| | *"open chatgpt"* / *"gemini"* / *"claude"* | Opens respective AI chat in Chrome | Yes |
| **Desktop Apps** | *"open vs code"* / *"code editor"* | Launches / focuses Visual Studio Code | No |
| | *"open terminal"* / *"command line"* | Launches Windows Terminal (`wt.exe`) | No |
| | *"open spotify"* | Launches / focuses Spotify | No |
| | *"open postman"* / *"opencode"* / *"antigravity"* | Launches / focuses desktop application | No |
| | *"open settings"* | Opens Windows Settings (`ms-settings:`) | No |
| **System** | *"open file explorer"* / *"files"* | Enters Voice File Explorer Mode | No |
| **Meta** | *"what can you do"* / *"help"* | Summarizes available commands | No |
| | *"repeat that"* | Repeats last spoken message | No |
| | *"cancel"* / *"never mind"* | Cancels current listening/prompt | No |
| | *"stop listening"* | Pauses Cedric until hotkey is pressed | No |

---

## 📂 File Explorer Voice Navigation Mode

Triggered by saying *"open file explorer"*:

| Spoken Phrase | Action |
|---|---|
| *"<folder name>"* or *"open <folder>"* | Navigates into that subfolder |
| *"<file name>"* or *"open <file>"* | Opens file with default Windows app |
| *"go back"* / *"go up"* | Navigates backward in history or to parent folder |
| *"go to desktop"* / *"downloads"* / *"documents"* / *"c drive"* | Quick jump to common system directories |
| *"read this folder"* / *"show more"* | Reads current directory contents in batches of 10 |
| *"one"*, *"two"*, *"three"*, or *"none"* | Selects between ambiguous matching files |
| *"exit"* / *"done"* / *"close explorer"* | Exits navigation mode and returns to IDLE |

---

## ⚙️ Configuration & Customization

All voice commands, aliases, paths, and thresholds live in YAML configuration files inside `cedric/config/`:

- **[`commands.yaml`](file:///c:/Users/DELL/Desktop/Dinan/Projects/CEDRIC/cedric/config/commands.yaml):** Define triggers, targets (URL, exe, URI), and spoken confirmation replies.
- **[`settings.yaml`](file:///c:/Users/DELL/Desktop/Dinan/Projects/CEDRIC/cedric/config/settings.yaml):** Customize hotkeys, confidence thresholds (`high: 85`, `low: 65`), timeouts, and application executable paths.
- **[`explorer_aliases.yaml`](file:///c:/Users/DELL/Desktop/Dinan/Projects/CEDRIC/cedric/config/explorer_aliases.yaml):** Custom folder shortcuts for File Explorer navigation.

---

## 🧪 Testing & Diagnostics

### Run Unit Tests
```powershell
.\.venv\Scripts\pytest -v
```
*(Tests cover wake word detection, text normalization, RapidFuzz scoring thresholds, command registry schema, and File Explorer navigation).*

### Diagnostics & Replay Tool
- **Logs:** Real-time and historical logs with utterance timestamps, confidence scores, and latencies are written to `logs/cedric.log`.
- **Text & Audio Replay:** Test router matches without speaking:
  ```powershell
  .\.venv\Scripts\python tests/replay_tool.py --text "open github"
  ```

---

## 🔄 Windows Auto-Start (Optional)

Install Cedric to run silently in the background on Windows startup (no console window):

```powershell
# Install auto-start:
.\.venv\Scripts\python scripts/setup_autostart.py --install

# Remove auto-start:
.\.venv\Scripts\python scripts/setup_autostart.py --uninstall
```
