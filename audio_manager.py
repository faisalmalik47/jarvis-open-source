import asyncio
import sys
import time
import pyaudio

INPUT_SAMPLE_RATE = 16000
INPUT_CHUNK_SIZE = 1024

OUTPUT_SAMPLE_RATE = 24000
OUTPUT_CHUNK_SIZE = 1024


class AudioManager:
    """Manages low-latency audio capture and playback with instant interruption handling."""

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.input_queue = asyncio.Queue()
        self.output_queue = asyncio.Queue()
        self._loop = None
        self.is_running = False
        self.is_playing = False
        self.last_playback_time = 0.0

    def start(self, loop: asyncio.AbstractEventLoop):
        """Start microphone input and speaker output streams."""
        self._loop = loop
        self.is_running = True

        def input_callback(in_data, frame_count, time_info, status):
            if self.is_running and in_data:
                self._loop.call_soon_threadsafe(self.input_queue.put_nowait, in_data)
            return (None, pyaudio.paContinue)

        # 16kHz Mono 16-bit for Gemini Input
        self.input_stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=INPUT_SAMPLE_RATE,
            input=True,
            frames_per_buffer=INPUT_CHUNK_SIZE,
            stream_callback=input_callback,
        )
        self.input_stream.start_stream()

        # 24kHz Mono 16-bit for Gemini Output
        self.output_stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=OUTPUT_SAMPLE_RATE,
            output=True,
            frames_per_buffer=OUTPUT_CHUNK_SIZE,
        )
        self.output_stream.start_stream()

    async def play_audio_loop(self):
        """Asynchronously plays audio bytes queued from Gemini's live stream."""
        loop = asyncio.get_running_loop()
        while self.is_running:
            try:
                data = await self.output_queue.get()
                if not data or not self.output_stream:
                    continue
                self.is_playing = True
                try:
                    await loop.run_in_executor(None, self.output_stream.write, data)
                    self.last_playback_time = time.time()
                finally:
                    if self.output_queue.empty():
                        self.is_playing = False
            except asyncio.CancelledError:
                self.is_playing = False
                break
            except Exception as e:
                self.is_playing = False
                print(f"[Audio Error] Playback: {e}", file=sys.stderr)

    def is_speaking(self) -> bool:
        """Returns True if Jarvis is currently playing audio or reverberating in the room."""
        if not self.output_queue.empty():
            return True
        if self.is_playing:
            return True
        # Allow 200ms for acoustic room echo from laptop speakers to dissipate
        if (time.time() - self.last_playback_time) < 0.20:
            return True
        return False

    def queue_output(self, data: bytes):
        """Enqueue downstream audio chunk from Gemini."""
        if self.is_running:
            self.output_queue.put_nowait(data)

    def flush_output(self):
        """Immediately clear playback queue on user interruption (barge-in)."""
        self.is_playing = False
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except Exception:
                break

    def stop(self):
        """Gracefully release audio streams and hardware resources."""
        self.is_running = False
        self.flush_output()
        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except Exception:
                pass
        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception:
                pass
        if self.pa:
            self.pa.terminate()
