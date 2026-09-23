import asyncio
import os
import sys
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types, live

from audio_manager import AudioManager
from tools import TOOL_DECLARATIONS, dispatch_tool

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


def validate_api_key(api_key: str):
    """Checks that the API key is configured."""
    if not api_key or api_key == "your_gemini_api_key_here":
        return False, "GEMINI_API_KEY is not set in .env"
    return True, "Valid"


async def send_mic_loop(session, audio_mgr: AudioManager):
    """Continuously streams microphone PCM audio chunks to Gemini Live.
    
    Acoustic Management & Barge-In:
    - When Jarvis is speaking, we watch for user barge-in. If the user speaks
      firmly (RMS > 900), we immediately cut off Jarvis's speech and stream the user's voice.
    - Software Noise Gate: When ambient room noise is low (RMS < 300), we send
      zeroed comfort frames to prevent Gemini VAD from hallucinating speech on fan/room hum.
    """
    silent_frames = 0
    silence_warned = False
    user_speaking = False
    consecutive_loud_interrupt_frames = 0

    try:
        while audio_mgr.is_running:
            chunk = await audio_mgr.input_queue.get()
            if chunk:
                # Measure RMS energy level of the microphone input
                samples = np.frombuffer(chunk, dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float64)**2)))

                # Voice Barge-In: If Jarvis is speaking, detect if user is interrupting
                if audio_mgr.is_speaking():
                    if rms > 900:  # User speaking over laptop speakers
                        consecutive_loud_interrupt_frames += 1
                        if consecutive_loud_interrupt_frames >= 2:
                            # Instant Voice Interruption!
                            audio_mgr.flush_output()
                            consecutive_loud_interrupt_frames = 0
                            print("\n⚡ [Interrupted by Sir]", flush=True)
                            await session.send_realtime_input(
                                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                            )
                    else:
                        consecutive_loud_interrupt_frames = 0
                    
                    audio_mgr.input_queue.task_done()
                    continue

                consecutive_loud_interrupt_frames = 0

                # Visual feedback when the user's voice is detected
                if rms > 350:
                    if not user_speaking:
                        print("\r🎙️  [Hearing your voice...]", end="", flush=True)
                        user_speaking = True
                elif rms < 180 and user_speaking:
                    user_speaking = False

                # Noise Gate: If input is ambient murmur/fan hum (<250 RMS), send silence
                # This prevents Gemini VAD from hallucinating speech and talking unprompted.
                payload_data = chunk if rms >= 250 else b'\x00' * len(chunk)

                # Detect if microphone is delivering pure silence (all zeros) due to macOS TCC
                if rms == 0.0:
                    silent_frames += 1
                    # 1024 samples @ 16kHz = ~64ms per frame. 50 frames = ~3 seconds
                    if silent_frames > 50 and not silence_warned:
                        print("\n⚠️  [Warning] Microphone input is completely silent (level: 0.0).", flush=True)
                        print("   macOS may be blocking microphone access for this terminal.", flush=True)
                        print("   Check: System Settings > Privacy & Security > Microphone > Enable your Terminal app.\n", flush=True)
                        silence_warned = True
                else:
                    silent_frames = 0

                await session.send_realtime_input(
                    audio=types.Blob(data=payload_data, mime_type="audio/pcm;rate=16000")
                )
            audio_mgr.input_queue.task_done()
    except (asyncio.CancelledError, Exception) as e:
        if not audio_mgr.is_running or "closed" in str(e).lower() or "1000" in str(e) or "1011" in str(e):
            return
        print(f"\n[Mic Stream Error]: {e}", file=sys.stderr)


async def receive_gemini_loop(session, audio_mgr: AudioManager):
    """Continuously receives streaming audio chunks and tool calls from Gemini Live across all turns."""
    speaking = False
    try:
        while audio_mgr.is_running:
            async for response in session.receive():
                if not audio_mgr.is_running:
                    break

                # Check for server content (audio + text + interruptions)
                server_content = response.server_content
                if server_content is not None:
                    # Handle Barge-In: User spoke while Jarvis was speaking
                    if getattr(server_content, "interrupted", False):
                        audio_mgr.flush_output()
                        speaking = False
                        print("\n⚡ [Interrupted]", flush=True)

                    # Process returned model output parts
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn is not None:
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

                    if getattr(server_content, "turn_complete", False):
                        if speaking:
                            print("✓\n🟢 JARVIS is listening...\n", flush=True)
                            speaking = False

                # Check for GoAway signal (session duration limit reached by Google)
                if response.go_away is not None:
                    print("\n⚡ [J.A.R.V.I.S. Protocol: Session duration reached. Auto-refreshing connection...]", flush=True)
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
        print(f"\n[Receive Loop Error]: {e}", file=sys.stderr)


async def run_session():
    valid, reason = validate_api_key(API_KEY)
    if not valid:
        print(f"\n❌ Pre-flight Check Failed:\n   {reason}\n", file=sys.stderr)
        return False

    audio_mgr = AudioManager()

    # Configure the Gemini Live Session with zero thinking delay for instant speech
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
            )
        ),
        thinking_config=types.ThinkingConfig(thinking_budget=0, include_thoughts=False),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=SYSTEM_INSTRUCTION)]
        ),
        tools=[{"function_declarations": TOOL_DECLARATIONS}],
    )

    client = genai.Client(api_key=API_KEY)

    try:
        async with client.aio.live.connect(model=MODEL_ID, config=config) as session:
            loop = asyncio.get_running_loop()
            audio_mgr.start(loop)
            print("🟢 J.A.R.V.I.S. is online. All protocols fully operational.")
            print("   🎙️  Wake word: Start your request with 'Jarvis' (e.g. 'Jarvis, check my system')")
            print("   ⚡ Interruption: Speak loudly to interrupt, or press [Enter] in the terminal anytime.\n")

            # Initial spoken greeting to announce arrival aloud
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part.from_text(text="[SYSTEM PROTOCOL: Assistant initialized. Welcome Sir in one brief, elegant J.A.R.V.I.S. sentence, confirming all systems are online.]")])],
                turn_complete=True
            )

            async def keyboard_interrupt_loop():
                """Allows Sir to press Enter at any moment in the terminal to immediately cut off speech."""
                loop = asyncio.get_running_loop()
                while audio_mgr.is_running:
                    try:
                        line = await loop.run_in_executor(None, sys.stdin.readline)
                        if not line and not audio_mgr.is_running:
                            break
                        if audio_mgr.is_speaking():
                            audio_mgr.flush_output()
                            print("\n⚡ [Interrupted by Keypress] Speech halted.", flush=True)
                    except Exception:
                        break

            playback_task = asyncio.create_task(audio_mgr.play_audio_loop())
            mic_task = asyncio.create_task(send_mic_loop(session, audio_mgr))
            recv_task = asyncio.create_task(receive_gemini_loop(session, audio_mgr))
            key_task = asyncio.create_task(keyboard_interrupt_loop())

            await asyncio.gather(mic_task, recv_task, playback_task, key_task)

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n\nShutting down JARVIS...")
        return False
    except Exception as e:
        err_str = str(e)
        if "goaway" in err_str.lower() or "session duration" in err_str.lower() or "1008" in err_str:
            print(f"\n⚡ [J.A.R.V.I.S. Protocol: Session duration reached. Auto-refreshing...]", flush=True)
            return True
        if "403" in err_str or "forbidden" in err_str.lower() or "not allowed by policy" in err_str.lower():
            print(f"\n❌ [Authentication Error]: HTTP 403 Forbidden from Google.", file=sys.stderr)
            print("   Your GEMINI_API_KEY was rejected by Google policy.", file=sys.stderr)
            print("   Please get a valid key at: https://aistudio.google.com/apikey", file=sys.stderr)
            return False
        print(f"\n[Session Error]: {e}", file=sys.stderr)
        return True
    finally:
        audio_mgr.stop()

    return False


async def main():
    print("=" * 64)
    print("🤖 J.A.R.V.I.S. (Just A Rather Very Intelligent System)")
    print(f"📡 Core: Gemini 3.1 Flash Live | Mark VII Neural Engine")
    print(f"🎙️  Voice: {VOICE_NAME} | Full macOS System & Filesystem Access")
    print("=" * 64)
    print("Connecting to live audio stream... Press Ctrl+C to exit.\n")

    while True:
        should_reconnect = await run_session()
        if not should_reconnect:
            break
        print("\n⚡ Reconnecting J.A.R.V.I.S. in 1 second...")
        await asyncio.sleep(1)

    print("Offline. Goodbye, Sir.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOffline. Goodbye, Sir.")
