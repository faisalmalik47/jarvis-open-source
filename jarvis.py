import asyncio
import os
import sys
import time
import select
import termios
import tty
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types, live

from audio_manager import AudioManager
from tools import TOOL_DECLARATIONS, dispatch_tool
from logger import (
    jarvis_logger,
    log_event,
    log_transcript,
    log_interruption,
    log_session_lifecycle,
    log_error,
)

# Load environment variables
load_dotenv()

# Patch websockets in google-genai to disable client keepalive ping timeout
# Google's Gemini Live WebSocket proxy does not handle client ping frames,
# which causes websockets library to abort with code 1011 if ping_interval is active.
orig_ws_connect = live.ws_connect


def custom_ws_connect(uri, **kwargs):
    kwargs.setdefault("ping_interval", None)
    kwargs.setdefault("ping_timeout", None)
    return orig_ws_connect(uri, **kwargs)


live.ws_connect = custom_ws_connect

API_KEY = os.getenv("GEMINI_API_KEY")
VOICE_NAME = os.getenv("JARVIS_VOICE", "Puck")
MODEL_ID = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")

SYSTEM_INSTRUCTION = """
You are J.A.R.V.I.S. (Just A Rather Very Intelligent System), the iconic, refined, and hyper-capable AI assistant created for Tony Stark, now running with full system control over Sir's macOS machine.
You communicate via direct real-time voice streaming with Sir.

CRITICAL WAKE-WORD & INTERACTION PROTOCOL:
1. You must ONLY speak or execute tools when Sir explicitly addresses you by name ("Jarvis", "Hey Jarvis", "J.A.R.V.I.S.").
2. If Sir or ambient conversation does NOT explicitly address you as "Jarvis", you must remain COMPLETELY SILENT. Output nothing. Do not speak.
3. If Sir asks you to stop, pause, or be quiet, cease speaking immediately.

Core Persona & Iron Man Protocols:
1. Mannerisms & Tone:
   - Always address the user respectfully as "Sir".
   - Speak in a calm, cultivated British cadence with dry wit, understated irony, and unflappable composure.
   - You never panic, yell, or become overly emotional. Maintain total poise and elegance at all times.
   - Classic JARVIS quips are welcomed when appropriate ("As always, Sir, a great pleasure watching you work", "A very astute observation, Sir").

2. Full System & Filesystem Powers:
   - You have complete, unrestricted access to Sir's Mac.
   - When asked to find a file, document, or project: invoke `search_files` (Spotlight mdfind) immediately.
   - When asked to inspect, read, or summarize a file: invoke `read_file`.
   - When asked to create notes, code, or documents: invoke `write_file`.
   - When asked what is in a folder or on the Desktop/Downloads: invoke `list_directory`.
   - When asked to open, move, copy, or trash a file: invoke `manage_file`.
   - When asked about system health, CPU, RAM, battery, or disk space: invoke `get_system_vitals`.
   - When asked about network, Wi-Fi, or IP: invoke `get_network_info`.
   - When asked to run terminal tasks, git commands, shell scripts, or check packages: invoke `execute_shell_command`.
   - When asked to take a screenshot, toggle dark mode, or lock screen: invoke `control_system`.
   - When asked what applications are running: invoke `list_running_applications`.

3. Spoken Brevity (Crucial for Voice Fluidity):
   - You are speaking aloud through speakers: do NOT speak asterisks, bullet marks, or markdown symbols.
   - Keep spoken answers crisp, direct, and conversational (strictly 1 to 2 natural sentences).
   - If a tool returns detailed data (e.g. system vitals or file list), summarize the highlights smoothly aloud: e.g. "Sir, CPU is humming at 14 percent, with 10 gigabytes of memory free and battery at 82 percent."
"""


class WakeWordGate:
    """Manages conversational state: STANDBY vs ACTIVE.
    
    STANDBY:
    - JARVIS listens quietly.
    - If ambient conversation does NOT address JARVIS ("Jarvis"), model audio output is suppressed.
    - Audio output remains dead silent.
    
    ACTIVE:
    - Triggered when "Jarvis" / "Hey Jarvis" is detected in user speech, or by pressing Spacebar.
    - Full bidirectional speech permitted.
    - Stays active during conversation and for an 8-second follow-up window after speech finishes.
    - If 8 seconds elapse without user speech, smoothly returns to STANDBY.
    """

    def __init__(self, timeout_sec: float = 8.0):
        self.state = "STANDBY"
        self.timeout_sec = timeout_sec
        self.last_speech_time = 0.0
        self.wake_words = [
            "jarvis",
            "hey jarvis",
            "ok jarvis",
            "okay jarvis",
            "hi jarvis",
            "j.a.r.v.i.s.",
            "travis",
            "javis",
            "charvis",
        ]

    def is_active(self) -> bool:
        if self.state == "ACTIVE":
            if time.time() - self.last_speech_time > self.timeout_sec:
                self.state = "STANDBY"
                print("\n💤 [JARVIS entered Standby. Say 'Jarvis' or tap Space to activate.]\n", flush=True)
                log_event("STATE_CHANGE", {"to": "STANDBY", "reason": "timeout"})
                return False
            return True
        return False

    def activate(self, reason: str = "wake_word"):
        self.state = "ACTIVE"
        self.last_speech_time = time.time()
        log_event("STATE_CHANGE", {"to": "ACTIVE", "reason": reason})

    def touch(self):
        """Refreshes the active conversation window."""
        if self.state == "ACTIVE":
            self.last_speech_time = time.time()

    def check_wake_word(self, text: str) -> bool:
        if not text:
            return False
        clean = text.lower().strip()
        return any(w in clean for w in self.wake_words)


class TurnState:
    """Tracks per-turn interruption and suppression state."""

    def __init__(self):
        self.interrupted = False
        self.suppressed = False

    def reset_for_turn(self):
        self.interrupted = False
        self.suppressed = False


def validate_api_key(api_key: str):
    """Checks that the API key is configured."""
    if not api_key or api_key == "your_gemini_api_key_here":
        return False, "GEMINI_API_KEY is not set in .env"
    return True, "Valid"


async def send_mic_loop(session, audio_mgr: AudioManager, gate: WakeWordGate, turn_state: TurnState):
    """Continuously streams microphone PCM audio chunks to Gemini Live.
    
    Acoustic Management & Barge-In:
    - When Jarvis is speaking through the laptop speakers, the laptop microphone hears
      the speaker output. We stream silence comfort frames while speaking to prevent
      Gemini's server VAD from self-interrupting on laptop speaker audio.
    - Software Noise Gate: When ambient room noise is low (RMS < 320), we send
      zeroed comfort frames to prevent Gemini VAD from hallucinating speech on fan/room hum.
    """
    silent_frames = 0
    silence_warned = False
    user_speaking = False

    try:
        while audio_mgr.is_running:
            chunk = await audio_mgr.input_queue.get()
            if chunk:
                # Measure RMS energy level of the microphone input
                samples = np.frombuffer(chunk, dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float64)**2)))

                # Acoustic Echo Suppression:
                # If Jarvis is speaking through the speakers, send comfort silence frames
                # to Gemini so the server VAD doesn't self-interrupt on speaker output.
                if audio_mgr.is_speaking():
                    if rms > 2500:  # Deliberate user shout over full speaker volume
                        turn_state.interrupted = True
                        audio_mgr.flush_output()
                        gate.activate("voice_barge_in")
                        print("\n⚡ [Interrupted by Sir]", flush=True)
                        log_interruption("VOICE_BARGE_IN", f"Microphone RMS: {rms:.1f}")
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                        )
                    else:
                        # Send comfort silence while speakers are active
                        await session.send_realtime_input(
                            audio=types.Blob(data=b'\x00' * len(chunk), mime_type="audio/pcm;rate=16000")
                        )
                    audio_mgr.input_queue.task_done()
                    continue

                # Visual feedback when the user's voice is detected
                if rms > 400:
                    if not user_speaking:
                        print("\r🎙️  [Hearing your voice...]", end="", flush=True)
                        user_speaking = True
                        log_event("MIC_ACTIVITY", {"status": "speech_started", "rms": round(rms, 1)})
                elif rms < 200 and user_speaking:
                    user_speaking = False
                    log_event("MIC_ACTIVITY", {"status": "speech_ended", "rms": round(rms, 1)})

                # Noise Gate: If input is ambient murmur/fan hum (<320 RMS), send silence
                # This prevents Gemini VAD from hallucinating speech and talking unprompted.
                payload_data = chunk if rms >= 320 else b'\x00' * len(chunk)

                # Detect if microphone is delivering pure silence (all zeros) due to macOS TCC
                if rms == 0.0:
                    silent_frames += 1
                    # 1024 samples @ 16kHz = ~64ms per frame. 50 frames = ~3 seconds
                    if silent_frames > 50 and not silence_warned:
                        print("\n⚠️  [Warning] Microphone input is completely silent (level: 0.0).", flush=True)
                        print("   macOS may be blocking microphone access for this terminal.", flush=True)
                        print("   Check: System Settings > Privacy & Security > Microphone > Enable your Terminal app.\n", flush=True)
                        silence_warned = True
                        log_error("MIC_STREAM", Exception("Microphone delivering pure silence - possible macOS TCC restriction"))
                else:
                    silent_frames = 0

                await session.send_realtime_input(
                    audio=types.Blob(data=payload_data, mime_type="audio/pcm;rate=16000")
                )
            audio_mgr.input_queue.task_done()
    except (asyncio.CancelledError, Exception) as e:
        if not audio_mgr.is_running or "closed" in str(e).lower() or "1000" in str(e) or "1011" in str(e):
            return
        log_error("send_mic_loop", e)
        print(f"\n[Mic Stream Error]: {e}", file=sys.stderr)


async def receive_gemini_loop(session, audio_mgr: AudioManager, gate: WakeWordGate, turn_state: TurnState):
    """Continuously receives streaming audio chunks and tool calls from Gemini Live across all turns."""
    speaking = False
    current_transcript = []
    try:
        while audio_mgr.is_running:
            async for response in session.receive():
                if not audio_mgr.is_running:
                    break

                # Check for server content (audio + text + interruptions)
                server_content = response.server_content
                if server_content is not None:
                    # 1. Inspect real-time transcription from Gemini
                    interim_trans = getattr(server_content, "interim_input_transcription", None)
                    input_trans = getattr(server_content, "input_transcription", None)

                    user_text = ""
                    if interim_trans and interim_trans.text:
                        user_text = interim_trans.text
                    elif input_trans and input_trans.text:
                        user_text = input_trans.text

                    if user_text:
                        if gate.check_wake_word(user_text):
                            if not gate.is_active():
                                print(f"\n⚡ [Wake Word Detected: \"Jarvis\"]", flush=True)
                            gate.activate("wake_word")
                            log_transcript("USER", user_text)
                        elif gate.is_active():
                            gate.touch()
                            log_transcript("USER", user_text)

                    # 2. Handle Server-Side Interruption (only when Jarvis was actively speaking)
                    if getattr(server_content, "interrupted", False):
                        if speaking:
                            turn_state.interrupted = True
                            audio_mgr.flush_output()
                            speaking = False
                            print("\n⚡ [Interrupted]", flush=True)
                            log_interruption("SERVER_VAD", "Gemini detected user speech during turn")

                    # 3. Process returned model output parts
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn is not None:
                        # If this turn was interrupted by Sir, discard remaining chunks
                        if turn_state.interrupted:
                            continue

                        # If Sir did not say Jarvis and we are not in active conversation window:
                        if not gate.is_active():
                            if not turn_state.suppressed:
                                print("\r💤 [Ambient speech ignored - Say 'Jarvis' or tap Space to address JARVIS]", flush=True)
                                log_event("SPEECH_SUPPRESSED", {"user_transcript": user_text})
                                turn_state.suppressed = True
                            continue

                        for part in model_turn.parts:
                            # Stream audio output to speaker queue
                            if part.inline_data and part.inline_data.data:
                                if not speaking:
                                    print("\r🔊 JARVIS: [Speaking...] ", end="", flush=True)
                                    speaking = True
                                audio_mgr.queue_output(part.inline_data.data)

                            # Print spoken transcript text if available
                            is_thought = getattr(part, "thought", False)
                            if part.text and not is_thought:
                                print(part.text, end="", flush=True)
                                current_transcript.append(part.text)

                    # 4. Turn Complete
                    if getattr(server_content, "turn_complete", False):
                        if current_transcript:
                            full_text = "".join(current_transcript).strip()
                            log_transcript("JARVIS", full_text)
                            current_transcript.clear()
                        if speaking:
                            print("✓\n🟢 JARVIS is listening...\n", flush=True)
                            speaking = False
                            gate.touch()
                        turn_state.reset_for_turn()

                # Check for GoAway signal (session duration limit reached by Google)
                if response.go_away is not None:
                    print("\n⚡ [J.A.R.V.I.S. Protocol: Session duration reached. Auto-refreshing connection...]", flush=True)
                    log_session_lifecycle("GO_AWAY_RECEIVED", {"reason": "Session duration reached"})
                    audio_mgr.is_running = False
                    return

                # Check for structured tool execution requests
                tool_call = response.tool_call
                if tool_call is not None:
                    function_responses = []
                    for call in tool_call.function_calls:
                        args_preview = str(call.args or '')
                        if len(args_preview) > 60:
                            args_preview = args_preview[:57] + "..."
                        print(f"\n⚡ [J.A.R.V.I.S. Protocol] {call.name}({args_preview})", flush=True)
                        result_dict = dispatch_tool(call.name, call.args or {})
                        res_text = str(result_dict.get('result') or result_dict.get('error') or '')
                        first_line = res_text.splitlines()[0] if res_text else "Done"
                        print(f"   ↳ {first_line[:90]}", flush=True)
                        function_responses.append(
                            types.FunctionResponse(
                                name=call.name,
                                id=call.id,
                                response=result_dict,
                            )
                        )

                    # Send function results back into the conversation
                    if function_responses:
                        await session.send_tool_response(
                            function_responses=function_responses
                        )

            # When session.receive() finishes a turn, small yield to event loop before next turn
            await asyncio.sleep(0.01)

    except (asyncio.CancelledError, Exception) as e:
        err_msg = str(e).lower()
        if not audio_mgr.is_running or "closed" in err_msg or "1008" in err_msg or "goaway" in err_msg:
            return
        log_error("receive_gemini_loop", e)
        print(f"\n[Receive Loop Error]: {e}", file=sys.stderr)


async def keyboard_listener_loop(audio_mgr: AudioManager, gate: WakeWordGate, turn_state: TurnState):
    """Zero-latency keyboard monitor.
    - While JARVIS is speaking: ANY key instantly halts speech!
    - While idle: Spacebar wakes JARVIS directly into ACTIVE mode.
    """
    if not sys.stdin.isatty():
        return

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    try:
        loop = asyncio.get_running_loop()
        while audio_mgr.is_running:
            r, _, _ = await loop.run_in_executor(None, select.select, [sys.stdin], [], [], 0.08)
            if r:
                char = sys.stdin.read(1)
                if char == '\x03':  # Ctrl+C
                    raise KeyboardInterrupt()

                if audio_mgr.is_speaking():
                    turn_state.interrupted = True
                    audio_mgr.flush_output()
                    print("\n⚡ [Interrupted by Keypress] Speech halted.", flush=True)
                    log_interruption("KEYPRESS", f"Key '{repr(char)}' pressed")
                else:
                    if char == ' ':
                        gate.activate("spacebar_press")
                        print("\n⚡ [J.A.R.V.I.S. Activated by Spacebar] Listening for Sir's command...", flush=True)
            await asyncio.sleep(0.02)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    except Exception as e:
        log_error("keyboard_listener", e)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


async def standby_monitor_loop(audio_mgr: AudioManager, gate: WakeWordGate):
    """Periodically checks if the active conversation window has expired."""
    while audio_mgr.is_running:
        try:
            await asyncio.sleep(1.0)
            if not audio_mgr.is_speaking():
                gate.is_active()  # triggers state transition to STANDBY if timed out
        except asyncio.CancelledError:
            break


async def run_session():
    valid, reason = validate_api_key(API_KEY)
    if not valid:
        print(f"\n❌ Pre-flight Check Failed:\n   {reason}\n", file=sys.stderr)
        return False

    audio_mgr = AudioManager()
    gate = WakeWordGate(timeout_sec=8.0)
    turn_state = TurnState()

    # Configure the Gemini Live Session with input/output audio transcription
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
            )
        ),
        thinking_config=types.ThinkingConfig(thinking_budget=0, include_thoughts=False),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=SYSTEM_INSTRUCTION)]
        ),
        tools=[{"function_declarations": TOOL_DECLARATIONS}],
    )

    client = genai.Client(api_key=API_KEY)

    try:
        log_session_lifecycle("CONNECTING", {"model": MODEL_ID, "voice": VOICE_NAME})
        async with client.aio.live.connect(model=MODEL_ID, config=config) as session:
            loop = asyncio.get_running_loop()
            audio_mgr.start(loop)
            log_session_lifecycle("CONNECTED", {"model": MODEL_ID, "voice": VOICE_NAME})
            print("🟢 J.A.R.V.I.S. is online. All protocols fully operational.")
            print("   🎙️  Wake word: Start your request with 'Jarvis' (e.g. 'Jarvis, check my system')")
            print("   ⚡ Spacebar: Tap [Space] to activate without saying wake word, or tap ANY key to halt speech!")
            print("   🔇 Voice Barge-In: Speak firmly to interrupt JARVIS mid-sentence.\n")

            # Activate gate for initial arrival greeting
            gate.activate("initial_greeting")
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part.from_text(text="[SYSTEM PROTOCOL: Assistant initialized. Welcome Sir in one brief, elegant J.A.R.V.I.S. sentence, confirming all systems are online.]")])],
                turn_complete=True
            )

            playback_task = asyncio.create_task(audio_mgr.play_audio_loop())
            mic_task = asyncio.create_task(send_mic_loop(session, audio_mgr, gate, turn_state))
            recv_task = asyncio.create_task(receive_gemini_loop(session, audio_mgr, gate, turn_state))
            key_task = asyncio.create_task(keyboard_listener_loop(audio_mgr, gate, turn_state))
            monitor_task = asyncio.create_task(standby_monitor_loop(audio_mgr, gate))

            await asyncio.gather(mic_task, recv_task, playback_task, key_task, monitor_task)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n\nShutting down JARVIS...")
        log_session_lifecycle("SHUTDOWN_REQUESTED", {"reason": "KeyboardInterrupt"})
        return False
    except Exception as e:
        err_str = str(e)
        if "goaway" in err_str.lower() or "session duration" in err_str.lower() or "1008" in err_str:
            print(f"\n⚡ [J.A.R.V.I.S. Protocol: Session duration reached. Auto-refreshing...]", flush=True)
            log_session_lifecycle("RECONNECT_SCHEDULED", {"reason": err_str})
            return True
        if "403" in err_str or "forbidden" in err_str.lower() or "not allowed by policy" in err_str.lower():
            print(f"\n❌ [Authentication Error]: HTTP 403 Forbidden from Google.", file=sys.stderr)
            print("   Your GEMINI_API_KEY was rejected by Google policy.", file=sys.stderr)
            print("   Please get a valid key at: https://aistudio.google.com/apikey", file=sys.stderr)
            log_error("SESSION_AUTH", e)
            return False
        log_error("SESSION_RUN", e)
        print(f"\n[Session Error]: {e}", file=sys.stderr)
        return True
    finally:
        log_session_lifecycle("SESSION_STOPPED")
        audio_mgr.stop()

    return False


async def main():
    print("=" * 64)
    print("🤖 J.A.R.V.I.S. (Just A Rather Very Intelligent System)")
    print(f"📡 Core: Gemini 3.1 Flash Live | Mark VII Neural Engine")
    print(f"🎙️  Voice: {VOICE_NAME} | Full macOS System & Filesystem Access")
    print("=" * 64)
    print("Connecting to live audio stream... Press Ctrl+C to exit.\n")
    log_session_lifecycle("APPLICATION_START", {"model": MODEL_ID, "voice": VOICE_NAME})

    while True:
        should_reconnect = await run_session()
        if not should_reconnect:
            break
        print("\n⚡ Reconnecting J.A.R.V.I.S. in 1 second...")
        log_session_lifecycle("RECONNECT_WAIT", {"delay_sec": 1})
        await asyncio.sleep(1)

    log_session_lifecycle("APPLICATION_EXIT")
    print("Offline. Goodbye, Sir.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOffline. Goodbye, Sir.")
