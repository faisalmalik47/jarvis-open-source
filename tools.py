import datetime
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

# Function declarations for Gemini Live API
TOOL_DECLARATIONS = [
    # --- System & Hardware Vitals ---
    {
        "name": "get_system_vitals",
        "description": "Comprehensive Iron Man HUD diagnostics: reports CPU load, RAM usage, disk storage, battery status, and top resource-consuming processes.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_network_info",
        "description": "Checks current Wi-Fi network SSID, local IP address, and internet connectivity status.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "control_system",
        "description": "Executes hardware & OS controls: take a screenshot, toggle Dark Mode, post a notification banner, or lock the screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "One of: 'screenshot', 'toggle_dark_mode', 'notify', 'lock_screen'.",
                },
                "value": {
                    "type": "STRING",
                    "description": "Optional text message for 'notify' action.",
                },
            },
            "required": ["action"],
        },
    },
    # --- Deep Filesystem Access ---
    {
        "name": "search_files",
        "description": "Instant Spotlight search across the Mac using mdfind. Finds files by filename or text content across the entire drive or specific folders.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The search phrase, filename, or keyword to find.",
                },
                "directory": {
                    "type": "STRING",
                    "description": "Optional directory path to restrict search (e.g. '~/Desktop', '~/Documents', '~/Downloads'). Defaults to full Mac.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Reads the contents of any file on the Mac (code, markdown, text, json, configs, scripts).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "The file path to read (e.g. '~/Desktop/notes.txt' or absolute path).",
                },
                "max_lines": {
                    "type": "INTEGER",
                    "description": "Maximum number of lines to return (default 150).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Creates, writes, or appends text to a file on disk anywhere on the Mac.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "The target file path (e.g. '~/Desktop/todo.txt'). Parent folders created automatically.",
                },
                "content": {
                    "type": "STRING",
                    "description": "The text content to write to the file.",
                },
                "mode": {
                    "type": "STRING",
                    "description": "'overwrite' to replace content, or 'append' to add to existing file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "Lists files and folders inside any directory with item sizes and modification dates.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Directory path to list (e.g. '~', '~/Desktop', '~/Downloads'). Default is home directory.",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum number of items to return (default 40).",
                },
            },
        },
    },
    {
        "name": "manage_file",
        "description": "Performs file operations: 'open' in default app, 'reveal' in Finder, 'copy', 'move', or 'trash'.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "One of: 'open', 'reveal', 'copy', 'move', 'trash'.",
                },
                "path": {
                    "type": "STRING",
                    "description": "Target file or folder path.",
                },
                "destination": {
                    "type": "STRING",
                    "description": "Destination path required only for 'copy' or 'move'.",
                },
            },
            "required": ["action", "path"],
        },
    },
    # --- Full Terminal Shell Command Execution ---
    {
        "name": "execute_shell_command",
        "description": "Executes any terminal shell command (zsh/bash) with full user privileges. Use for system automation, Homebrew, Git, Docker, Python scripts, or terminal utilities.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "The exact shell command line to run.",
                },
                "working_directory": {
                    "type": "STRING",
                    "description": "Optional working directory path (defaults to home).",
                },
            },
            "required": ["command"],
        },
    },
    # --- Applications & Window Management ---
    {
        "name": "list_running_applications",
        "description": "Lists all currently active GUI applications running on the Mac.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_application",
        "description": "Opens any Mac application by name (e.g. Safari, Spotify, Slack, Calculator, Notes, Terminal, Chrome, VS Code).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "The name of the macOS application to open.",
                }
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "close_application",
        "description": "Quits or closes an open application on the Mac.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "The name of the application to quit.",
                }
            },
            "required": ["app_name"],
        },
    },
    # --- Hardware & Media Controls ---
    {
        "name": "set_system_volume",
        "description": "Sets the system audio output volume level on the Mac (0 to 100).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "level": {
                    "type": "INTEGER",
                    "description": "Volume percentage between 0 and 100.",
                }
            },
            "required": ["level"],
        },
    },
    {
        "name": "get_system_volume",
        "description": "Gets the current system audio output volume level on the Mac.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "media_control",
        "description": "Controls audio and media playback on macOS (play/pause, next track, previous track).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "One of: play_pause, next, previous.",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_battery_status",
        "description": "Checks the Mac battery percentage, charging status, and remaining time.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_current_time",
        "description": "Gets the current real-world date, time, and day of the week.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "clipboard_action",
        "description": "Reads text from or copies text to the Mac system clipboard.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "'read' to get clipboard contents, or 'copy' to write text to clipboard.",
                },
                "text": {
                    "type": "STRING",
                    "description": "Text to copy (only required if action is 'copy').",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "search_web",
        "description": "Opens the user's default browser and performs a Google search for the query.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The search term or question to look up.",
                }
            },
            "required": ["query"],
        },
    },
]


# ==============================================================================
# Implementation Functions
# ==============================================================================

def get_system_vitals() -> str:
    """Comprehensive system diagnostics for Iron Man HUD reporting."""
    try:
        # Load average (CPU)
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 8
        cpu_load_pct = min(100, int((load1 / cpu_count) * 100))

        # Memory via sysctl and vm_stat
        sysctl_res = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
        total_ram_gb = int(sysctl_res.stdout.strip()) / (1024**3) if sysctl_res.returncode == 0 else 16.0

        # Storage on /
        df_res = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
        disk_line = df_res.stdout.strip().splitlines()[-1].split() if df_res.returncode == 0 else []
        disk_used, disk_avail, disk_pct = (disk_line[2], disk_line[3], disk_line[4]) if len(disk_line) >= 5 else ("?", "?", "?")

        # Battery
        pm_res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
        batt_lines = pm_res.stdout.strip().splitlines()
        batt_str = batt_lines[1].strip() if len(batt_lines) > 1 else "AC Power"

        # Top 3 processes
        ps_res = subprocess.run(["ps", "-eo", "%cpu,%mem,comm", "-r"], capture_output=True, text=True)
        top_procs = []
        if ps_res.returncode == 0:
            for line in ps_res.stdout.strip().splitlines()[1:4]:
                parts = line.strip().split(None, 2)
                if len(parts) == 3:
                    p_name = os.path.basename(parts[2])
                    top_procs.append(f"{p_name} ({parts[0]}% CPU)")

        procs_str = ", ".join(top_procs) if top_procs else "None"

        return (
            f"Sir, system diagnostics report:\n"
            f"• CPU Load: {cpu_load_pct}% (Averages: {load1:.2f}, {load5:.2f})\n"
            f"• Physical Memory: {total_ram_gb:.1f} GB Total\n"
            f"• Primary Storage: {disk_avail} Available ({disk_pct} used)\n"
            f"• Power & Battery: {batt_str}\n"
            f"• Top Active Processes: {procs_str}"
        )
    except Exception as e:
        return f"Telemetry diagnostic failed: {e}"


def get_network_info() -> str:
    """Checks Wi-Fi SSID, local IP, and connectivity."""
    try:
        # Wi-Fi SSID
        airport_res = subprocess.run(
            ["ipconfig", "getsummary", "en0"],
            capture_output=True,
            text=True,
        )
        ssid = "Connected"
        for line in airport_res.stdout.splitlines():
            if "SSID" in line:
                ssid = line.split(":", 1)[-1].strip()
                break

        # Local IP
        ip_res = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True)
        local_ip = ip_res.stdout.strip() or "Unavailable"

        return f"Network Status: Connected to '{ssid}', Local IP: {local_ip}. Internet connection is active."
    except Exception as e:
        return f"Network query failed: {e}"


def control_system(action: str, value: str = None) -> str:
    """Hardware & system automation."""
    action = action.lower().strip()
    try:
        if action == "screenshot":
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dest = os.path.expanduser(f"~/Desktop/Screenshot_{ts}.png")
            res = subprocess.run(["screencapture", dest], capture_output=True)
            if res.returncode == 0 and os.path.exists(dest):
                return f"Screenshot captured and saved to Desktop: Screenshot_{ts}.png."
            return "Failed to capture screenshot."

        elif action in ["toggle_dark_mode", "dark_mode"]:
            script = 'tell application "System Events" to tell appearance preferences to set dark mode to not dark mode'
            subprocess.run(["osascript", "-e", script], check=True)
            return "Toggled macOS system appearance."

        elif action == "notify":
            msg = value or "Protocol complete, Sir."
            script = f'display notification "{msg}" with title "J.A.R.V.I.S." sound name "Glass"'
            subprocess.run(["osascript", "-e", script], check=True)
            return f"Notification banner posted: {msg}"

        elif action in ["lock", "lock_screen"]:
            subprocess.run(["pmset", "displaysleepnow"])
            return "Display locked, Sir."

        return f"Unknown system control action: {action}"
    except Exception as e:
        return f"System control error: {e}"


def search_files(query: str, directory: str = None) -> str:
    """Instant Spotlight search using mdfind."""
    try:
        cmd = ["mdfind"]
        if directory:
            clean_dir = os.path.expanduser(directory)
            if os.path.exists(clean_dir):
                cmd.extend(["-onlyin", clean_dir])
        cmd.extend(["-name", query])

        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]

        if not lines:
            # Fallback to broader content query
            fallback = subprocess.run(["mdfind", query], capture_output=True, text=True, timeout=8)
            lines = [l.strip() for l in fallback.stdout.strip().splitlines() if l.strip()]

        if not lines:
            return f"No files matching '{query}' found on your Mac, Sir."

        total = len(lines)
        preview = lines[:8]
        formatted = "\n".join(f"  • {p}" for p in preview)
        extra = f"\n  ...and {total - 8} more files." if total > 8 else ""
        return f"Found {total} files matching '{query}':\n{formatted}{extra}"
    except Exception as e:
        return f"File search failed: {e}"


def read_file(path: str, max_lines: int = 150) -> str:
    """Reads file text safely."""
    try:
        full_path = Path(os.path.expanduser(path)).resolve()
        if not full_path.exists():
            return f"File not found at '{path}', Sir."
        if not full_path.is_file():
            return f"Path '{path}' is a directory, not a readable file."

        # File size guard (max 100KB for real-time speech)
        size_bytes = full_path.stat().st_size
        if size_bytes > 200_000:
            return f"File is too large ({size_bytes // 1024} KB). Please specify targeted lines."

        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(max_lines)]

        content = "".join(lines).strip()
        return f"Contents of {full_path.name}:\n{content[:2500]}"
    except Exception as e:
        return f"Failed to read file: {e}"


def write_file(path: str, content: str, mode: str = "overwrite") -> str:
    """Creates, writes, or appends text to a file anywhere on disk."""
    try:
        full_path = Path(os.path.expanduser(path)).resolve()
        full_path.parent.mkdir(parents=True, exist_ok=True)

        write_mode = "a" if mode.lower() == "append" else "w"
        with open(full_path, write_mode, encoding="utf-8") as f:
            f.write(content)

        action_str = "appended to" if write_mode == "a" else "written to"
        return f"Successfully {action_str} {full_path.name} at {full_path}."
    except Exception as e:
        return f"Failed to write file: {e}"


def list_directory(path: str = "~", limit: int = 40) -> str:
    """Lists files and folders inside any directory."""
    try:
        target = Path(os.path.expanduser(path or "~")).resolve()
        if not target.exists():
            return f"Directory does not exist: {path}"
        if not target.is_dir():
            return f"Path is not a directory: {path}"

        items = list(target.iterdir())
        items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))

        formatted = []
        for item in items[:limit]:
            prefix = "📁" if item.is_dir() else "📄"
            if item.is_file():
                sz = item.stat().st_size
                sz_str = f"{sz // 1024}KB" if sz >= 1024 else f"{sz}B"
                formatted.append(f"{prefix} {item.name} ({sz_str})")
            else:
                formatted.append(f"{prefix} {item.name}/")

        total = len(items)
        extra = f"\n...and {total - limit} more items." if total > limit else ""
        return f"Directory listing for {target} ({total} total):\n" + "\n".join(formatted) + extra
    except Exception as e:
        return f"Failed to list directory: {e}"


def manage_file(action: str, path: str, destination: str = None) -> str:
    """File actions: open, reveal, copy, move, trash."""
    action = action.lower().strip()
    try:
        src = Path(os.path.expanduser(path)).resolve()
        if not src.exists():
            return f"Target not found: {path}"

        if action == "open":
            subprocess.run(["open", str(src)], check=True)
            return f"Opened {src.name} in its default application, Sir."
        elif action == "reveal":
            subprocess.run(["open", "-R", str(src)], check=True)
            return f"Revealed {src.name} in Finder."
        elif action == "trash":
            script = f'tell application "Finder" to delete POSIX file "{str(src)}"'
            subprocess.run(["osascript", "-e", script], check=True)
            return f"Moved {src.name} to the macOS Trash."
        elif action in ["copy", "move"]:
            if not destination:
                return "Destination path required for copy/move."
            dst = Path(os.path.expanduser(destination)).resolve()
            if action == "copy":
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                return f"Copied {src.name} to {dst}."
            else:
                shutil.move(src, dst)
                return f"Moved {src.name} to {dst}."
        return f"Unknown file action: {action}"
    except Exception as e:
        return f"File management failed: {e}"


def execute_shell_command(command: str, working_directory: str = None) -> str:
    """Executes arbitrary shell commands in zsh."""
    try:
        cwd = os.path.expanduser(working_directory) if working_directory else os.path.expanduser("~")
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            executable="/bin/zsh",
            timeout=30,
        )
        output = (res.stdout.strip() + "\n" + res.stderr.strip()).strip()
        if not output:
            output = f"Command executed successfully with exit code {res.returncode}."
        return output[:3000]
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        return f"Execution error: {e}"


def list_running_applications() -> str:
    """Lists visible active GUI applications on macOS."""
    try:
        res = subprocess.run(["lsappinfo", "visibleProcessList"], capture_output=True, text=True)
        if res.returncode == 0:
            names = re.findall(r'"([^"]+)"', res.stdout)
            clean_names = [n.replace("_", " ") for n in names if n]
            return f"Active applications ({len(clean_names)}): " + ", ".join(clean_names)
        return "Could not retrieve running applications."
    except Exception as e:
        return f"Failed to query running applications: {e}"


def open_application(app_name: str) -> str:
    res = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
    if res.returncode == 0:
        return f"Successfully opened {app_name}."
    else:
        return f"Could not find or open application '{app_name}'. Error: {res.stderr.strip()}"


def close_application(app_name: str) -> str:
    script = f'tell application "{app_name}" to quit'
    res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if res.returncode == 0:
        return f"Closed {app_name}."
    return f"Failed to close {app_name}."


def set_system_volume(level: int) -> str:
    level = max(0, min(100, int(level)))
    subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
    return f"System volume set to {level}%."


def get_system_volume() -> str:
    res = subprocess.run(
        ["osascript", "-e", "output volume of (get volume settings)"],
        capture_output=True,
        text=True,
    )
    vol = res.stdout.strip()
    return f"Current system volume is {vol}%."


def media_control(action: str) -> str:
    action = action.lower().strip()
    if action in ["play_pause", "pause", "play"]:
        subprocess.run(["osascript", "-e", 'tell application "Music" to playpause'], capture_output=True)
        return "Toggled media playback."
    elif action == "next":
        subprocess.run(["osascript", "-e", 'tell application "Music" to next track'], capture_output=True)
        return "Skipped to next track."
    elif action == "previous":
        subprocess.run(["osascript", "-e", 'tell application "Music" to previous track'], capture_output=True)
        return "Returned to previous track."
    return f"Unknown media action: {action}"


def get_battery_status() -> str:
    res = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
    lines = res.stdout.strip().split("\n")
    if len(lines) > 1:
        return f"Mac Battery: {lines[1].strip()}"
    return res.stdout.strip() or "Battery information unavailable."


def get_current_time() -> str:
    now = datetime.datetime.now()
    return now.strftime("Current time is %I:%M %p on %A, %B %d, %Y.")


def clipboard_action(action: str, text: str = "") -> str:
    if action == "read":
        res = subprocess.run(["pbpaste"], capture_output=True, text=True)
        clip = res.stdout.strip()
        if not clip:
            return "The clipboard is currently empty."
        return f"Clipboard content: {clip[:500]}"
    elif action == "copy":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"))
        return "Text copied to Mac clipboard."
    return "Invalid clipboard action."


def search_web(query: str) -> str:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    subprocess.run(["open", url])
    return f"Opened web search for: {query}"


# Tool Dispatch Table
TOOL_MAP = {
    # System Diagnostics & Controls
    "get_system_vitals": get_system_vitals,
    "get_network_info": get_network_info,
    "control_system": control_system,
    # Filesystem Superpowers
    "search_files": search_files,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "manage_file": manage_file,
    # Shell Execution
    "execute_shell_command": execute_shell_command,
    # Applications
    "list_running_applications": list_running_applications,
    "open_application": open_application,
    "close_application": close_application,
    # Hardware & Audio
    "set_system_volume": set_system_volume,
    "get_system_volume": get_system_volume,
    "media_control": media_control,
    "get_battery_status": get_battery_status,
    "get_current_time": get_current_time,
    "clipboard_action": clipboard_action,
    "search_web": search_web,
}


def dispatch_tool(name: str, args: dict) -> dict:
    """Executes the requested tool and returns a clean dictionary response with detailed telemetry."""
    import time
    from logger import log_tool_execution, jarvis_logger

    func = TOOL_MAP.get(name)
    if not func:
        res = {"error": f"Unknown tool: {name}"}
        log_tool_execution(name, args, res, 0.0)
        return res

    start_time = time.perf_counter()
    try:
        result = func(**args)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        res = {"result": result}
        log_tool_execution(name, args, res, duration_ms)
        return res
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        res = {"error": str(e)}
        log_tool_execution(name, args, res, duration_ms)
        return res

