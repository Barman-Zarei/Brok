import sys
import types

import pytest

from brok.voice.providers import CommandSTT, MicRecorder, VoiceUnavailable, WhisperSTT, build_stt


def test_build_stt_kinds():
    assert isinstance(build_stt("whisper"), WhisperSTT)
    assert isinstance(build_stt("command", "x {audio}"), CommandSTT)
    assert build_stt("none") is None


def test_whisper_reports_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # makes import (and find_spec) fail
    w = WhisperSTT()
    monkeypatch.setattr(WhisperSTT, "available", lambda self: False)
    with pytest.raises(VoiceUnavailable, match="brok\\[voice\\]"):
        w.transcribe("a.wav")


def test_whisper_transcribes_with_fake_model_and_loads_it_once(monkeypatch):
    loads = []

    class Seg:
        def __init__(self, text):
            self.text = text

    class Model:
        def __init__(self, name, compute_type):
            loads.append(name)

        def transcribe(self, path, language=None):
            assert language == "fa"
            return [Seg(" سلام "), Seg("بروک")], None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    monkeypatch.setattr(WhisperSTT, "available", lambda self: True)
    w = WhisperSTT("tiny")
    assert w.transcribe("x.wav", "fa") == "سلام بروک"
    w.transcribe("x.wav", "fa")
    assert loads == ["tiny"]


def test_mic_recorder_without_sounddevice_degrades(monkeypatch):
    monkeypatch.setattr(MicRecorder, "available", lambda self: False)
    with pytest.raises(VoiceUnavailable, match="sounddevice"):
        MicRecorder()()


def test_mic_recorder_writes_wav_with_fake_device(monkeypatch, tmp_path):
    import wave


    class Buf:
        def tobytes(self):
            return b"\x00\x00" * 160

    fake = types.SimpleNamespace(rec=lambda n, **k: Buf(), wait=lambda: None)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(MicRecorder, "available", lambda self: True)
    path = MicRecorder(seconds=0.01)()
    with wave.open(path) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
