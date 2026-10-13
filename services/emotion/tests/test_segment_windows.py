"""Unit tests for /predict segment windowing; heavy ML deps are stubbed."""
import sys
import types
from pathlib import Path

for name in ("torch", "funasr", "transformers"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["funasr"].AutoModel = object
sys.modules["transformers"].pipeline = None
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app  # noqa: E402

SR = app.SAMPLE_RATE


def test_short_segment_gets_centered_min_window():
    [(lo, hi)] = app.segment_windows([{"start": 2.0, "end": 2.2}], 10 * SR)
    assert (lo, hi) == (int(1.7 * SR), int(2.5 * SR))


def test_long_segment_keeps_its_bounds():
    assert app.segment_windows([{"start": 1.0, "end": 4.0}], 10 * SR) == [(SR, 4 * SR)]


def test_window_is_shifted_inside_audio_edges():
    windows = app.segment_windows([{"start": 0.0, "end": 0.1}, {"start": 9.95, "end": 10.0}], 10 * SR)
    assert windows == [(0, int(0.8 * SR)), (int(9.2 * SR), 10 * SR)]


def test_window_is_capped_at_max_inference_seconds():
    [(lo, hi)] = app.segment_windows([{"start": 0.0, "end": 100.0}], 120 * SR)
    assert hi - lo == app.MAX_INFERENCE_SECONDS * SR
