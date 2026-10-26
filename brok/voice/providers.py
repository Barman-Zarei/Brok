"""Voice: STTProvider/TTSProvider interfaces, real providers, and a pipeline that degrades to text."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Callable


class VoiceUnavailable(Exception):
    pass


class TTSProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def speak(self, text: str, language: str = "fa") -> None: ...


class STTProvider(ABC):
    name = "base"

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def transcribe(self, audio_path: str, language: str = "fa") -> str: ...


class SystemTTS(TTSProvider):
    """OS speech: espeak-ng (Linux, has Persian ``fa``), ``say`` (macOS), SAPI via PowerShell (Windows)."""

    name = "system"

    def _argv(self, text: str, language: str) -> list[str] | None:
        sysname = platform.system()
        if sysname == "Darwin" and shutil.which("say"):
            return ["say", "--", text]
        if sysname == "Windows" and shutil.which("powershell"):
            # The text travels in an environment variable, never inside the script: doubling "'" is not enough in
            # PowerShell (the typographic quotes U+2018/2019/201A/201B also close a '...' string), so a reply such as
            # "don’t'; calc; '" would have run code.
            return [
                "powershell",
                "-NoProfile",
                "-Command",
                "Add-Type -AssemblyName System.Speech; "
                "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($env:BROK_TTS_TEXT)",
            ]
        for exe in ("espeak-ng", "espeak"):
            if shutil.which(exe):
                return [exe, "-v", language, "--", text]
        return None

    def available(self) -> bool:
        return self._argv("x", "en") is not None

    def speak(self, text: str, language: str = "fa") -> None:
        argv = self._argv(text, language)
        if not argv:
            raise VoiceUnavailable("no system text-to-speech engine found (install espeak-ng on Linux)")
        env = {**os.environ, "BROK_TTS_TEXT": text} if argv[0] == "powershell" else None
        subprocess.run(argv, check=False, timeout=120, stdin=subprocess.DEVNULL, capture_output=True, env=env)


class CommandSTT(STTProvider):
    """Wrap a local transcriber CLI (e.g. whisper.cpp) that prints the transcript.

    ``{audio}`` and ``{lang}`` in the template are replaced."""

    name = "command"

    def __init__(self, template: str = "") -> None:
        self.template = template

    def _split(self) -> list[str]:
        """Split like a shell would, but keep Windows backslashes (posix mode would eat them) and drop the quotes."""
        import shlex

        try:
            parts = shlex.split(self.template, posix=os.name != "nt")
        except ValueError:  # unbalanced quote
            return []
        if os.name == "nt":
            parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]
        return parts

    def available(self) -> bool:
        # `template.split()[0]` cut a quoted program path with spaces ("C:\\Program Files\\...") at the first space.
        parts = self._split()
        return bool(parts) and shutil.which(parts[0]) is not None

    def transcribe(self, audio_path: str, language: str = "fa") -> str:
        if not self.available():
            raise VoiceUnavailable("speech-to-text is not configured")
        argv = [a.replace("{audio}", audio_path).replace("{lang}", language) for a in self._split()]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise VoiceUnavailable(r.stderr.strip()[:200] or "transcriber failed")
        return r.stdout.strip()


class WhisperSTT(STTProvider):
    """Offline speech-to-text via the optional ``faster-whisper`` package (``pip install "brok[voice]"``).

    Persian is supported by Whisper; quality depends on the model size (``small``+ recommended).
    """

    name = "whisper"

    def __init__(self, model: str = "small") -> None:
        self.model_name = model
        self._model: Any = None  # loaded lazily once: loading is slow and must not be repeated per request

    def available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(self, audio_path: str, language: str = "fa") -> str:
        if not self.available():
            raise VoiceUnavailable('speech-to-text needs faster-whisper: pip install "brok[voice]"')
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_name, compute_type="int8")
        segments, _info = self._model.transcribe(audio_path, language=language or None)
        return " ".join(seg.text.strip() for seg in segments).strip()


class MicRecorder:
    """Record a fixed-length clip from the default microphone to a temp WAV (needs ``sounddevice``)."""

    def __init__(self, seconds: float = 6.0, samplerate: int = 16000) -> None:
        self.seconds, self.samplerate = seconds, samplerate

    def available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("sounddevice") is not None

    def __call__(self) -> str:
        if not self.available():
            raise VoiceUnavailable('microphone capture needs sounddevice: pip install "brok[voice]"')
        import tempfile
        import wave

        import sounddevice as sd

        try:
            data = sd.rec(int(self.seconds * self.samplerate), samplerate=self.samplerate, channels=1, dtype="int16")
            sd.wait()
        except Exception as exc:  # noqa: BLE001 - no mic / permission denied
            raise VoiceUnavailable(f"no usable microphone ({exc})") from exc
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="brok-")
        import os

        os.close(fd)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.samplerate)
            w.writeframes(data.tobytes())
        return path


def build_stt(kind: str, command: str = "") -> STTProvider | None:
    """Config value ``voice.stt`` → provider: ``whisper`` | ``command`` | anything else = no STT."""
    if kind == "whisper":
        return WhisperSTT()
    if kind == "command":
        return CommandSTT(command)
    return None


def _discard_recording(path: str) -> None:
    """Delete a temp recording made by MicRecorder (only files it names: brok-*.wav in the temp directory)."""
    import tempfile

    try:
        real = os.path.realpath(path)
        if (
            path
            and os.path.basename(real).startswith("brok-")
            and real.endswith(".wav")
            and os.path.dirname(real) == os.path.realpath(tempfile.gettempdir())
        ):
            os.remove(real)
    except OSError:
        pass


class VoicePipeline:
    """mic → STT → Brok → TTS, with avatar events; any missing piece falls back to plain text."""

    def __init__(
        self,
        stt: STTProvider | None,
        tts: TTSProvider | None,
        ask: Callable[[str], str],
        record: Callable[[], str] | None = None,
        on_event: Callable[[str], None] | None = None,
        language: str = "fa",
    ) -> None:
        self.stt, self.tts, self.ask, self.record = stt, tts, ask, record
        self.on_event, self.language = on_event or (lambda e: None), language
        self.notes: list[str] = []

    def _ev(self, e: str) -> None:
        self.on_event(e)

    def handle_audio(self) -> str:
        if not (self.stt and self.stt.available() and self.record):
            raise VoiceUnavailable("voice input unavailable; type your message instead")
        self._ev("listening")
        audio = ""
        try:
            audio = self.record()
            text = self.stt.transcribe(audio, self.language)
        except BaseException:
            self._ev("idle")
            raise
        finally:
            _discard_recording(audio)  # a recording of the user's voice must not pile up in the temp folder
        return self.respond(text)

    def respond(self, text: str) -> str:
        self._ev("ai_thinking")
        try:
            answer = self.ask(text)
        except BaseException:
            self._ev("idle")
            raise
        if self.tts and self.tts.available():
            self._ev("speaking")
            try:
                self.tts.speak(answer, self.language)
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f"voice output failed ({exc}); showing text only")
        else:
            self.notes.append("voice output unavailable; showing text only")
        self._ev("idle")
        return answer
