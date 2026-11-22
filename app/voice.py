"""Voice: speech-to-text with a local Whisper model, and native mic recording.

Transcription runs on your computer with faster-whisper (model "base.en",
about 140 MB, downloaded once into data/models/whisper). Your voice never
leaves your machine; only the resulting text goes to Claude as a normal
chat message.

Two ways audio arrives:
  * In a browser, the page records with the microphone and uploads the clip.
  * In the desktop app, the page asks Python to record (Recorder below),
    because the desktop window can't give web pages microphone access.
"""

import io
import os
import threading
from pathlib import Path

import numpy as np

MODEL_NAME = os.environ.get("AIOS_WHISPER_MODEL", "base.en")
MODEL_DIR = Path(os.environ.get("AIOS_MODEL_DIR", Path(__file__).resolve().parent.parent / "data" / "models")) / "whisper"
SAMPLE_RATE = 16000
MAX_SECONDS = 120

_model = None
_model_lock = threading.Lock()


def _load():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", download_root=str(MODEL_DIR))
    return _model


def ready() -> bool:
    return _model is not None


def warm_up() -> None:
    threading.Thread(target=lambda: _safe_load(), daemon=True).start()


def _safe_load():
    try:
        _load()
    except Exception:
        pass


def decode(data: bytes) -> np.ndarray:
    """Any audio file (webm/ogg from browsers, wav, m4a...) -> 16 kHz mono float32."""
    import av
    out = []
    with av.open(io.BytesIO(data), mode="r") as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for f in resampler.resample(frame):
                out.append(f.to_ndarray().flatten())
        for f in resampler.resample(None):  # flush
            out.append(f.to_ndarray().flatten())
    if not out:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(out).astype(np.float32) / 32768.0


def transcribe(audio) -> str:
    """`audio` is a float32 numpy array at 16 kHz, or raw bytes of an audio file (webm, wav, mp4...)."""
    model = _load()
    if isinstance(audio, (bytes, bytearray)):
        if len(audio) < 100:
            return ""
        source = decode(bytes(audio))
    else:
        source = np.asarray(audio, dtype=np.float32).flatten()
    if source.size < SAMPLE_RATE * 0.3:  # under 0.3 s: nothing said
        return ""
    segments, _info = model.transcribe(source, language="en", beam_size=1, vad_filter=True,
                                       condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments).strip()


class Recorder:
    """Records from the default microphone until stop() (desktop app only)."""

    def __init__(self):
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []

            def callback(indata, frames, time_info, status):
                if sum(len(c) for c in self._chunks) < SAMPLE_RATE * MAX_SECONDS:
                    self._chunks.append(indata.copy())

            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback)
            self._stream.start()

    def stop(self) -> np.ndarray:
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            return np.concatenate(self._chunks).flatten() if self._chunks else np.zeros(0, dtype=np.float32)


def speak(text: str) -> None:
    """Read text aloud with the Mac's built-in voice (desktop app)."""
    import re
    import subprocess
    clean = re.sub(r"[*_`#>\[\]]", "", text)[:4000]
    subprocess.Popen(["say", clean])


def stop_speaking() -> None:
    import subprocess
    subprocess.run(["pkill", "-x", "say"], check=False)
