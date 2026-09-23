# 🤖 J.A.R.V.I.S. (Just A Rather Very Intelligent System)

A full-duplex, sub-second real-time streaming voice AI assistant designed natively for macOS, modeled after Tony Stark's **J.A.R.V.I.S.** in *Iron Man*. Powered by **Gemini 3.1 Flash Live** over bidirectional WebSockets with full system and filesystem access.

---

## ⚡ Key Highlights

* **Direct Audio-to-Audio Streaming**: Direct raw PCM 16kHz microphone capture streamed to Gemini Live WebSockets with 24kHz speaker playback (~500ms voice turnaround).
* **Acoustic Echo Suppression**: Automatically mutes microphone transmission while JARVIS is speaking through the Mac's speakers, eliminating feedback loops so you hear every word clearly.
* **MCU Iron Man Persona**: Styled with Paul Bettany's refined British cadence, deadpan wit, unyielding composure, and addressing you exclusively as *"Sir"*.
* **Auto-Rotating Session Management**: Seamlessly handles Google's 15-minute `GoAway` duration limits with 1-second auto-reconnects for continuous uptime.

---

## 🧰 Native macOS Capabilities (19 Tools)

### 📂 Filesystem Superpowers
* `search_files`: Instant Spotlight search (`mdfind`) across your entire SSD (<50ms).
* `read_file`: Reads source code, documents, text files, configs, and scripts.
* `write_file`: Writes, creates, or appends notes, code, and documents anywhere on disk.
* `list_directory`: Browses any folder with file sizes, counts, and modification dates.
* `manage_file`: Opens files in default apps, reveals in Finder, copies, moves, or moves to macOS Trash.

### ⚡ System HUD & Diagnostics
* `get_system_vitals`: Live CPU load %, RAM usage, disk storage (`df -h`), battery state, and top resource-heavy processes.
* `get_network_info`: Current Wi-Fi SSID, local IP address, and connectivity status.
* `control_system`: Takes screenshots to Desktop, toggles Dark Mode, posts native macOS notification banners with chime, and locks the screen.
* `list_running_applications`: Lists all active GUI apps and windows via `lsappinfo`.

### 💻 Shell & Automation
* `execute_shell_command`: Runs arbitrary zsh/bash commands, Homebrew packages, Git repos, Docker containers, or Python scripts.

### 🔊 Hardware & Audio Control
* `open_application` / `close_application` (Safari, Spotify, Slack, Terminal, Chrome, etc.)
* `set_system_volume` / `get_system_volume`
* `media_control` (Play, pause, skip, previous)
* `get_battery_status` / `get_current_time`
* `clipboard_action` (Read / copy clipboard)
* `search_web` (Instant browser queries)

---

## 🚀 Quick Start

### 1. Requirements
* macOS (Apple Silicon or Intel)
* Python 3.11+
* PortAudio: `brew install portaudio`

### 2. Configuration
Get a free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey).

### 3. Run
```bash
./run.sh
```
*(On first launch, it will prompt for your API key and auto-save it to `.env`)*.

---

## 🎙️ Example Voice Commands

* *"Jarvis, run a system diagnostic and tell me what's using my memory."*
* *"Jarvis, find all files related to todo on my Mac."*
* *"Jarvis, what's on my Desktop right now?"*
* *"Jarvis, play Chammak Challo on YouTube Music."*
* *"Jarvis, take a screenshot and toggle Dark Mode."*
* *"Jarvis, execute a shell command to show my uptime."*

---

## 📊 Comprehensive Logging & Telemetry

JARVIS automatically maintains detailed logs in the `logs/` directory for ongoing evaluation, debugging, and continuous improvement:

* **Human-Readable Rolling Log (`logs/jarvis_debug.log`)**:
  - Detailed millisecond-resolution logs of session lifecycle, microphone energy/noise gating, tool execution durations, transcript text, interruptions, and complete exception stack traces.
  - Automatically rolls over at 10MB (keeps 5 rotating backups).
* **Machine-Readable Session Log (`logs/jarvis_sessions.jsonl`)**:
  - Structured JSON Lines telemetry for analyzing conversation history, tool calls, argument payloads, latency metrics, and error rates.

