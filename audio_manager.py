import asyncio
import collections
import sys
import threading
import time
import pyaudio

INPUT_SAMPLE_RATE = 16000
INPUT_CHUNK_SIZE = 1024

OUTPUT_SAMPLE_RATE = 24000
OUTPUT_CHUNK_SIZE = 1024


class AudioManager:
    """Manages low-latency audio capture and playback with non-blocking callback architecture.
    
    Uses PortAudio streaming callbacks for both microphone capture and speaker output.
    This completely avoids blocking thread executor calls, prevents PortAudio stream
    crashes ([Errno -9988] Stream closed), and allows true 0ms hardware playback flushing.
    """

    def __init__(self):
        self.pa = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.input_queue = asyncio.Queue()
        self._output_buffer = collections.deque()
        self._buffer_lock = threading.Lock()
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

        def output_callback(in_data, frame_count, time_info, status):
            bytes_needed = frame_count * 2  # 16-bit mono = 2 bytes per sample
            data = bytearray()
            with self._buffer_lock:
                while len(data) < bytes_needed and self._output_buffer:
                    chunk = self._output_buffer.popleft()
                    data.extend(chunk)

                if len(data) > bytes_needed:
                    remainder = bytes(data[bytes_needed:])
                    self._output_buffer.appendleft(remainder)
                    data = data[:bytes_needed]

            if len(data) < bytes_needed:
                data.extend(b"\x00" * (bytes_needed - len(data)))
                self.is_playing = False
            else:
                self.is_playing = True
                self.last_playback_time = time.time()

            return (bytes(data), pyaudio.paContinue)

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

        # 24kHz Mono 16-bit for Gemini Output with hardware callback
        self.output_stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=OUTPUT_SAMPLE_RATE,
            output=True,
            frames_per_buffer=OUTPUT_CHUNK_SIZE,
            stream_callback=output_callback,
        )
        self.output_stream.start_stream()

    async def play_audio_loop(self):
        """Asynchronously maintains playback coroutine lifecycle."""
        try:
            while self.is_running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def is_speaking(self) -> bool:
        """Returns True if Jarvis is currently playing audio or reverberating in the room."""
        with self._buffer_lock:
            if len(self._output_buffer) > 0:
                return True
        if self.is_playing:
            return True
        # Allow 200ms for acoustic room echo from laptop speakers to dissipate
        if (time.time() - self.last_playback_time) < 0.20:
            return True
        return False

    def queue_output(self, data: bytes):
        """Enqueue downstream audio chunk from Gemini into playback buffer."""
        if self.is_running and data:
            with self._buffer_lock:
                self._output_buffer.append(data)
            self.is_playing = True
            self.last_playback_time = time.time()

    def flush_output(self):
        """Instantly purge all buffered playback audio in 0ms without closing PortAudio stream."""
        with self._buffer_lock:
            self._output_buffer.clear()
        self.is_playing = False

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
