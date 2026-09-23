import datetime
import json
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Base logging directory
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Main rolling log file (10MB per file, keeps up to 5 backups)
DEBUG_LOG_FILE = LOG_DIR / "jarvis_debug.log"
# Structured JSON Lines session log for AI evaluations and telemetry
SESSION_LOG_FILE = LOG_DIR / "jarvis_sessions.jsonl"


def setup_logger():
    """Configures multi-channel logging: detailed debug file + structured session logger."""
    logger = logging.getLogger("JARVIS")
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers if reloaded
    if logger.handlers:
        return logger

    # Rotating File Handler for detailed human-readable logs
    file_handler = RotatingFileHandler(
        DEBUG_LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


jarvis_logger = setup_logger()


def log_event(event_type: str, details: dict):
    """Logs a structured JSON event to jarvis_sessions.jsonl and mirror to debug log."""
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event_type": event_type,
        "details": details,
    }
    
    # 1. Append JSONL
    try:
        with open(SESSION_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        jarvis_logger.error(f"Failed to write to session log: {e}")

    # 2. Write to debug log
    jarvis_logger.debug(f"[EVENT:{event_type}] {json.dumps(details, default=str)}")


def log_tool_execution(tool_name: str, args: dict, result: dict, duration_ms: float = 0.0):
    """Specifically logs tool execution arguments, outputs, execution duration, and errors."""
    event_data = {
        "tool_name": tool_name,
        "args": args,
        "result": result,
        "duration_ms": round(duration_ms, 2),
        "status": "error" if "error" in result else "success",
    }
    log_event("TOOL_EXECUTION", event_data)
    if "error" in result:
        jarvis_logger.warning(f"Tool {tool_name} failed: {result['error']}")
    else:
        jarvis_logger.info(f"Tool {tool_name} succeeded in {duration_ms:.1f}ms")


def log_transcript(speaker: str, text: str):
    """Logs conversation transcript chunks with timestamps."""
    if not text.strip():
        return
    log_event("TRANSCRIPT", {
        "speaker": speaker,
        "text": text.strip()
    })
    jarvis_logger.info(f"Transcript [{speaker}]: {text.strip()}")


def log_interruption(source: str, details: str = ""):
    """Logs user interruptions (barge-in or keypress)."""
    log_event("INTERRUPTION", {
        "source": source,
        "details": details
    })
    jarvis_logger.info(f"Interrupted via {source}: {details}")


def log_session_lifecycle(action: str, metadata: dict = None):
    """Logs connection starts, disconnects, model changes, and auto-reconnects."""
    data = metadata or {}
    data["action"] = action
    log_event("SESSION_LIFECYCLE", data)
    jarvis_logger.info(f"Session lifecycle: {action} - {data}")


def log_error(context: str, exc: Exception):
    """Logs detailed exceptions with stack trace."""
    tb = traceback.format_exc()
    log_event("ERROR", {
        "context": context,
        "error": str(exc),
        "traceback": tb
    })
    jarvis_logger.error(f"Error in {context}: {exc}\n{tb}")
