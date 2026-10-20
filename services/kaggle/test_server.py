"""Unit tests for the Kaggle GPU server with every heavy model mocked."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

HEAVY = ("torch", "whisper", "funasr", "pyannote", "pyannote.audio", "transformers", "sentence_transformers", "docling")


@pytest.fixture
def server(monkeypatch):
    for name in HEAVY:
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    sys.modules.pop("server", None)
    module = importlib.import_module("server")
    yield module
    module.models.clear()
    sys.modules.pop("server", None)


def test_import_has_no_side_effects(server):
    assert server.models == {}
    health = TestClient(server.app).get("/health").json()
    assert health["status"] == "ok" and not any(health["models"].values())


def test_emotion_window_pads_short_segments_around_centre(server):
    assert server._emotion_window(1.0, 3.0) == (1.0, 2.0)
    start, duration = server._emotion_window(5.0, 5.2)
    assert duration == server.MIN_EMOTION_DURATION_S
    assert start == pytest.approx(4.7)
    assert server._emotion_window(0.1, 0.2) == (0.0, server.MIN_EMOTION_DURATION_S)
    assert server._emotion_window(3.0, 1.0) == (1.0, 2.0)


def test_full_assigns_speaker_by_midpoint(server, monkeypatch):
    clips = []
    monkeypatch.setattr(server, "_vad", lambda path: {"speech_segments": [{"start": 0.0, "end": 4.5}, {"start": 8.9, "end": 9.5}]})
    monkeypatch.setattr(server, "_transcribe", lambda path, clip_timestamps=None: clips.append(clip_timestamps) or {
        "text": "hi there bye",
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "hi"},
            {"start": 2.5, "end": 4.5, "text": "there"},
            {"start": 9.0, "end": 9.4, "text": "bye"},
        ],
    })
    monkeypatch.setattr(server, "_diarize", lambda path: {"segments": [
        {"start": 0.0, "end": 2.2, "speaker": "SPEAKER_00"},
        {"start": 2.2, "end": 6.0, "speaker": "SPEAKER_01"},
    ]})
    windows = []
    monkeypatch.setattr(server, "_ffmpeg_to_wav", lambda src, dst, start=None, duration=None: windows.append((start, duration)))
    monkeypatch.setattr(server, "_emotion", lambda path: {"top_emotion": "angry", "emotions": [{"label": "angry", "score": 0.9}]})

    resp = TestClient(server.app).post("/full", files={"file": ("call.wav", b"RIFF", "audio/wav")})

    assert resp.status_code == 200
    body = resp.json()
    assert [s["speaker"] for s in body["segments"]] == ["SPEAKER_00", "SPEAKER_01", "UNKNOWN"]
    assert all(s["emotion"] == "angry" and s["emotion_scores"] for s in body["segments"])
    assert body["top_emotion"] == "angry" and body["text"] == "hi there bye"
    assert windows[2] == (pytest.approx(8.8), server.MIN_EMOTION_DURATION_S)
    assert clips == [[0.0, 4.5, 8.9, 9.5]]  # Whisper only sees the VAD speech regions
    assert body["speech_segments"] == [{"start": 0.0, "end": 4.5}, {"start": 8.9, "end": 9.5}]


def test_full_without_speech_skips_asr(server, monkeypatch):
    monkeypatch.setattr(server, "_vad", lambda path: {"speech_segments": []})
    monkeypatch.setattr(server, "_transcribe", lambda *a, **k: pytest.fail("ASR must not run without speech"))

    body = TestClient(server.app).post("/full", files={"file": ("call.wav", b"RIFF", "audio/wav")}).json()

    assert body["text"] == "" and body["segments"] == [] and body["top_emotion"] == "unknown"


def test_predict_text_maps_labels_to_vocalmind_vocabulary(server):
    def classifier(texts, truncation=True):
        table = {
            "great": [{"label": "joy", "score": 0.8}, {"label": "neutral", "score": 0.2}],
            "ugh": [{"label": "fear", "score": 0.3}, {"label": "disgust", "score": 0.3}, {"label": "anger", "score": 0.4}],
        }
        return [table[t] for t in texts]

    server.models["text_emotion"] = classifier
    client = TestClient(server.app)

    assert client.post("/predict_text", json={"text": "great"}).json() == {"emotion": "happy", "confidence": 0.8}
    results = client.post("/predict_text", json={"texts": ["ugh", "", "great"]}).json()["results"]
    assert results[0] == {"emotion": "frustrated", "confidence": 0.6}
    assert results[1] == {"emotion": "neutral", "confidence": 0.2}
    assert results[2]["emotion"] == "happy"


def test_missing_model_returns_503(server):
    assert TestClient(server.app).post("/embed", json={"texts": ["x"]}).status_code == 503
