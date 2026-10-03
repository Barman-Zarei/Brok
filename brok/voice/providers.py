"""Voice: STTProvider/TTSProvider interfaces, real providers, and a pipeline that degrades to text."""

from __future__ import annotations

import platform
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Callable, List, Optional


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

    def _argv(self, text: str, language: str) -> Optional[List[str]]:
        sysname = platform.system()
        if sysname == "Darwin" and shutil.which("say"):
            return ["say", "--", text]
        if sysname == "Windows" and shutil.which("powershell"):
            safe = text.replace("'", "''")
            return ["powershell", "-NoProfile", "-Command",
                    f"Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"]
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
        subprocess.run(argv, check=False, timeout=120, stdin=subprocess.DEVNULL, capture_output=True)


class CommandSTT(STTProvider):
    """Wrap any local transcriber CLI (e.g. whisper.cpp) that prints the transcript. ``{audio}``/``{lang}`` placeholders."""

    name = "command"

    def __init__(self, template: str = "") -> None:
        self.template = template

    def available(self) -> bool:
        return bool(self.template) and shutil.which(self.template.split()[0]) is not None

    def transcribe(self, audio_path: str, language: str = "fa") -> str:
        if not self.available():
            raise VoiceUnavailable("speech-to-text is not configured")
        import shlex

        argv = [a.replace("{audio}", audio_path).replace("{lang}", language) for a in shlex.split(self.template)]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise VoiceUnavailable(r.stderr.strip()[:200] or "transcriber failed")
        return r.stdout.strip()


class VoicePipeline:
    """mic → STT → Brok → TTS, with avatar events; any missing piece falls back to plain text."""

    def __init__(self, stt: Optional[STTProvider], tts: Optional[TTSProvider], ask: Callable[[str], str],
                 record: Optional[Callable[[], str]] = None, on_event: Optional[Callable[[str], None]] = None,
                 language: str = "fa") -> None:
        self.stt, self.tts, self.ask, self.record = stt, tts, ask, record
        self.on_event, self.language = on_event or (lambda e: None), language
        self.notes: List[str] = []

    def _ev(self, e: str) -> None:
        self.on_event(e)

    def handle_audio(self) -> str:
        if not (self.stt and self.stt.available() and self.record):
            raise VoiceUnavailable("voice input unavailable; type your message instead")
        self._ev("listening")
        text = self.stt.transcribe(self.record(), self.language)
        return self.respond(text)

    def respond(self, text: str) -> str:
        self._ev("ai_thinking")
        answer = self.ask(text)
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
