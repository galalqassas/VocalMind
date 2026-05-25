"""
WhisperX FastAPI Service
========================
Wraps WhisperX (ASR + alignment + diarization) in a simple REST API.

Endpoints:
    POST /transcribe  — Upload audio file, get back transcribed segments
    GET  /health      — Health check
"""

import os
import gc
import time
import tempfile
import warnings
import inspect
from pathlib import Path
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────────────────────
# Configuration — loads HF_TOKEN from the root .env file
# ──────────────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
load_dotenv(env_path)

HF_TOKEN = os.getenv("HF_TOKEN", "")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "large-v2")
SPEAKER_ROLE_MODEL_ENABLED = os.getenv("SPEAKER_ROLE_MODEL_ENABLED", "true").lower() == "true"
STRICT_DIARIZATION = os.getenv("STRICT_DIARIZATION", "false").lower() == "true"
SPEAKER_ROLE_MODEL_DIR = Path(
    os.getenv(
        "SPEAKER_ROLE_MODEL_DIR",
        str(Path(__file__).resolve().parent / "models" / "speaker_role" / "distilbert"),
    )
)

# ──────────────────────────────────────────────────────────────────────────────
# Compatibility patches — MUST run BEFORE importing whisperx / pyannote
# ──────────────────────────────────────────────────────────────────────────────
import torch

_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

try:
    import torchaudio
    if not hasattr(torchaudio, "AudioMetaData"):
        class AudioMetaData:
            def __init__(self, sample_rate, num_frames, num_channels, bits_per_sample, encoding):
                self.sample_rate = sample_rate
                self.num_frames = num_frames
                self.num_channels = num_channels
                self.bits_per_sample = bits_per_sample
                self.encoding = encoding
        torchaudio.AudioMetaData = AudioMetaData
    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]
    if not hasattr(torchaudio, "get_audio_backend"):
        torchaudio.get_audio_backend = lambda: "soundfile"
except ImportError:
    pass

try:
    import huggingface_hub
    _original_hf_hub_download = huggingface_hub.hf_hub_download
    def _patched_hf_hub_download(*args, **kwargs):
        if "use_auth_token" in kwargs:
            kwargs["token"] = kwargs.pop("use_auth_token")
        return _original_hf_hub_download(*args, **kwargs)
    huggingface_hub.hf_hub_download = _patched_hf_hub_download
except ImportError:
    pass

# ──────────────────────────────────────────────────────────────────────────────
# Now safe to import whisperx (patches are applied)
# ──────────────────────────────────────────────────────────────────────────────
import numpy as np
import whisperx
from whisperx.diarize import DiarizationPipeline
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from speaker_role_classifier import SpeakerRoleClassifier


_ALIGNMENT_CHECKPOINT = Path("/root/.cache/torch/hub/checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth")

if torch.cuda.is_available():
    DEVICE = "cuda"
    COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
else:
    # CPU mode keeps local E2E functional on machines without GPU passthrough.
    DEVICE = "cpu"
    COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# ──────────────────────────────────────────────────────────────────────────────
# Overlap detection (from main_v5_final.py)
# ──────────────────────────────────────────────────────────────────────────────

def detect_overlaps(segments: List[Dict], threshold: float = 0.1) -> List[Dict]:
    segments = sorted(segments, key=lambda x: x["start"])
    for seg in segments:
        seg.setdefault("overlap", False)
    for i, curr in enumerate(segments):
        for j in range(i + 1, len(segments)):
            nxt = segments[j]
            if nxt["start"] >= curr["end"]:
                break
            curr["overlap"] = True
            nxt["overlap"] = True
    return segments


def merge_short_same_speaker_segments(
    segments: List[Dict],
    max_gap_s: float = 1.2,
    min_seg_s: float = 1.5,
    max_merged_s: float = 22.0,
) -> List[Dict]:
    """Merge contiguous same-speaker segments separated by short gaps.

    WhisperX/PyAnnote tend to over-segment a single speaker's turn into many
    sub-1-second fragments ("Hi.", "Perfect.", "Bye."). Each fragment then
    gets its own emotion + diarization label, which dilutes both. This pass
    glues adjacent segments together when:
      - same speaker label
      - gap between current.end and next.start <= max_gap_s
      - merged duration stays under max_merged_s (cap)
    Short fragments (< min_seg_s) are also merged with the PREVIOUS segment
    even when the speaker label differs IF the previous one was much longer
    (likely a mis-attributed micro-segment).
    """
    if not segments:
        return segments

    segments = sorted(segments, key=lambda x: float(x.get("start", 0.0)))
    merged: List[Dict] = []

    def _same_speaker(a: Dict, b: Dict) -> bool:
        sa = (a.get("speaker") or "").strip().lower()
        sb = (b.get("speaker") or "").strip().lower()
        return bool(sa) and sa == sb

    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue
        last = merged[-1]
        gap = float(seg.get("start", 0.0)) - float(last.get("end", 0.0))
        cur_text = (last.get("text") or "").strip()
        new_text = (seg.get("text") or "").strip()
        merged_dur = float(seg.get("end", 0.0)) - float(last.get("start", 0.0))

        # Case 1: same speaker and small gap → merge
        if _same_speaker(last, seg) and gap <= max_gap_s and merged_dur <= max_merged_s:
            last["end"] = float(seg.get("end", last["end"]))
            joined = (cur_text + " " + new_text).strip() if new_text else cur_text
            last["text"] = joined
            if seg.get("overlap"):
                last["overlap"] = True
            continue

        # Case 2: micro-fragment (< min_seg_s) sandwiched between same-speaker
        # neighbors → absorb into the LAST segment. Avoids ".", "Yes." dangling.
        cur_dur = float(seg.get("end", 0.0)) - float(seg.get("start", 0.0))
        if cur_dur < min_seg_s and gap <= max_gap_s and merged_dur <= max_merged_s:
            last_dur = float(last.get("end", 0.0)) - float(last.get("start", 0.0))
            if last_dur >= min_seg_s:
                last["end"] = float(seg.get("end", last["end"]))
                joined = (cur_text + " " + new_text).strip() if new_text else cur_text
                last["text"] = joined
                if seg.get("overlap"):
                    last["overlap"] = True
                continue

        merged.append(dict(seg))

    return merged

# ──────────────────────────────────────────────────────────────────────────────
# Channel-aware diarization (stereo telephony / split-channel recordings)
# ──────────────────────────────────────────────────────────────────────────────

CHANNEL_DIARIZATION_ENABLED = os.getenv("CHANNEL_DIARIZATION_ENABLED", "true").lower() == "true"

try:
    CHANNEL_DIARIZATION_MAX_CORR = float(os.getenv("CHANNEL_DIARIZATION_MAX_CORR", "0.92"))
except (TypeError, ValueError):
    CHANNEL_DIARIZATION_MAX_CORR = 0.92

# Optional override: force a specific channel as agent (0 or 1). When unset,
# detect_stereo_layout picks the louder channel in the first 8s. Real PBX/SBC
# deployments often have a fixed convention (e.g. left=agent) and energy is
# not a reliable discriminator there.
_FORCED_AGENT_CHANNEL_RAW = os.getenv("AGENT_CHANNEL", "").strip()
FORCED_AGENT_CHANNEL: Optional[int] = (
    int(_FORCED_AGENT_CHANNEL_RAW)
    if _FORCED_AGENT_CHANNEL_RAW in ("0", "1")
    else None
)


def detect_stereo_layout(path: str) -> Optional[dict]:
    """Detect if audio is genuinely stereo-separated (e.g. agent on L, customer on R).

    Real call-center recordings from a PBX/SBC keep the two parties on separate
    channels with low cross-channel correlation. TTS / consumer audio is usually
    mono or "mono duplicated to stereo" (correlation ~1.0).

    Returns ``{'is_stereo_separated': True, 'agent_channel': int, ...}`` when
    channel-based diarization is appropriate, else ``None``. Never raises —
    falls back to cluster diarization on any error.
    """
    if not CHANNEL_DIARIZATION_ENABLED:
        return None
    try:
        import soundfile as sf
    except ImportError:
        return None
    try:
        info = sf.info(path)
        if info.channels != 2 or info.frames <= 0:
            return None
        window_frames = min(int(info.samplerate * 30), info.frames)
        data, sr = sf.read(path, frames=window_frames, dtype="float32", always_2d=True)
        if data.ndim != 2 or data.shape[1] != 2:
            return None
        ch0 = data[:, 0].astype(np.float32)
        ch1 = data[:, 1].astype(np.float32)
        c0 = ch0 - ch0.mean()
        c1 = ch1 - ch1.mean()
        denom = float(np.linalg.norm(c0) * np.linalg.norm(c1)) + 1e-9
        corr = float(np.dot(c0, c1) / denom)
        if abs(corr) >= CHANNEL_DIARIZATION_MAX_CORR:
            return None  # essentially mono duplicated to stereo
        first_window = data[: int(sr * 8.0)]
        e0 = float(np.sqrt(np.mean(first_window[:, 0] ** 2) + 1e-12))
        e1 = float(np.sqrt(np.mean(first_window[:, 1] ** 2) + 1e-12))
        if FORCED_AGENT_CHANNEL is not None:
            agent_channel = FORCED_AGENT_CHANNEL
            agent_source = "forced"
        else:
            agent_channel = 0 if e0 >= e1 else 1
            agent_source = "energy"
        return {
            "is_stereo_separated": True,
            "agent_channel": agent_channel,
            "agent_source": agent_source,
            "channels": 2,
        }
    except Exception as exc:
        print(f"⚠ detect_stereo_layout failed: {exc.__class__.__name__}: {exc}")
        return None


def assign_speakers_by_channel(
    path: str,
    segments: List[Dict],
    agent_channel: int,
) -> List[Dict]:
    """Assign per-segment speaker by which channel dominates in the segment window.

    For each segment, compute RMS energy on both channels over [start, end] and
    label the segment with whichever channel was louder. Falls back to the
    segment's existing speaker label on any per-segment error.
    """
    try:
        import soundfile as sf
    except ImportError:
        print("⚠ assign_speakers_by_channel: soundfile not available, falling back")
        return segments
    customer_channel = 1 - agent_channel
    try:
        info = sf.info(path)
    except Exception as exc:
        print(f"⚠ assign_speakers_by_channel: sf.info failed ({exc.__class__.__name__}: {exc})")
        return segments
    if info.channels != 2:
        return segments
    sr = info.samplerate
    total_frames = info.frames
    relabel_failures = 0
    for idx, seg in enumerate(segments):
        try:
            start_frame = max(0, int(float(seg.get("start", 0.0)) * sr))
            end_frame = min(total_frames, int(float(seg.get("end", 0.0)) * sr))
            if end_frame - start_frame < int(0.05 * sr):  # < 50ms — too short to measure
                continue
            data, _ = sf.read(
                path, start=start_frame, stop=end_frame, dtype="float32", always_2d=True
            )
            if data.ndim != 2 or data.shape[1] != 2:
                continue
            e_agent = float(np.sqrt(np.mean(data[:, agent_channel] ** 2) + 1e-12))
            e_customer = float(np.sqrt(np.mean(data[:, customer_channel] ** 2) + 1e-12))
            seg["speaker"] = "AGENT" if e_agent >= e_customer else "CUSTOMER"
            meta = seg.setdefault("speaker_meta", {})
            meta["source"] = "channel"
            meta["strategy"] = "channel"
            meta["agent_channel"] = int(agent_channel)
            meta["confidence"] = round(
                max(e_agent, e_customer) / (e_agent + e_customer + 1e-12), 3
            )
        except Exception as exc:
            relabel_failures += 1
            if relabel_failures <= 3:  # log up to 3, then suppress to avoid spam
                print(
                    f"⚠ assign_speakers_by_channel: segment {idx} relabel failed "
                    f"({exc.__class__.__name__}: {exc})"
                )
            continue
    if relabel_failures:
        print(
            f"⚠ assign_speakers_by_channel: {relabel_failures}/{len(segments)} "
            f"segments failed channel relabel — those keep their pre-channel labels"
        )
    return segments


# ──────────────────────────────────────────────────────────────────────────────
# Model holder — loaded once at startup
# ──────────────────────────────────────────────────────────────────────────────

class Models:
    asr_model = None
    diarize_model = None
    diarization_enabled = False
    diarization_reason = "not_loaded"
    speaker_role_classifier = SpeakerRoleClassifier(
        model_dir=SPEAKER_ROLE_MODEL_DIR,
        enabled=SPEAKER_ROLE_MODEL_ENABLED,
    )

def load_models():
    print(f"Loading WhisperX model ({WHISPER_MODEL_SIZE}) on {DEVICE} ({COMPUTE_TYPE})...")
    Models.asr_model = whisperx.load_model(
        WHISPER_MODEL_SIZE, DEVICE, compute_type=COMPUTE_TYPE
    )
    print("[OK] WhisperX ASR loaded")

    if not HF_TOKEN:
        Models.diarize_model = None
        Models.diarization_enabled = False
        Models.diarization_reason = "hf_token_missing"
        if STRICT_DIARIZATION:
            raise RuntimeError("STRICT_DIARIZATION=true but HF_TOKEN is not configured")
        print("⚠ WARNING: HF_TOKEN not set — diarization disabled")
        return

    diarize_kwargs = {"device": DEVICE}
    try:
        signature = inspect.signature(DiarizationPipeline)
        if HF_TOKEN:
            if "use_auth_token" in signature.parameters:
                diarize_kwargs["use_auth_token"] = HF_TOKEN
            elif "token" in signature.parameters:
                diarize_kwargs["token"] = HF_TOKEN
            elif "hf_token" in signature.parameters:
                diarize_kwargs["hf_token"] = HF_TOKEN

        try:
            Models.diarize_model = DiarizationPipeline(**diarize_kwargs)
        except TypeError:
            # Some pyannote/whisperx versions reject token kwargs even when
            # signature introspection suggests they exist.
            Models.diarize_model = DiarizationPipeline(device=DEVICE)
        Models.diarization_enabled = True
        Models.diarization_reason = "ready"
        print("[OK] Diarization pipeline loaded")
    except Exception as exc:
        Models.diarize_model = None
        Models.diarization_enabled = False
        Models.diarization_reason = f"{exc.__class__.__name__}: {exc}"
        if STRICT_DIARIZATION:
            raise RuntimeError(f"STRICT_DIARIZATION=true and diarization failed: {exc}") from exc
        print(f"⚠ WARNING: diarization unavailable ({exc.__class__.__name__}: {exc})")

def unload_models():
    Models.asr_model = None
    Models.diarize_model = None
    Models.diarization_enabled = False
    Models.diarization_reason = "not_loaded"
    gc.collect()
    if DEVICE == "cuda":
        torch.cuda.empty_cache()

# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_models()
    yield
    unload_models()

app = FastAPI(
    title="WhisperX Service",
    description="ASR + alignment + speaker diarization powered by WhisperX",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "device": DEVICE,
        "model": WHISPER_MODEL_SIZE,
        "models_loaded": Models.asr_model is not None,
        "diarization_enabled": Models.diarization_enabled,
        "diarization_reason": Models.diarization_reason,
        "speaker_role_model_available": Models.speaker_role_classifier.is_available,
    }


def _numpy_to_python(obj):
    """Recursively convert numpy types to native Python types for JSON."""
    if isinstance(obj, dict):
        return {k: _numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numpy_to_python(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _load_align_model_with_retry(language_code: str):
    """Load WhisperX alignment model and recover once from a corrupted torch checkpoint."""
    try:
        return whisperx.load_align_model(language_code=language_code, device=DEVICE)
    except Exception as exc:
        message = str(exc)
        if "PytorchStreamReader failed reading zip archive" not in message:
            raise
        if _ALIGNMENT_CHECKPOINT.exists():
            _ALIGNMENT_CHECKPOINT.unlink()
        return whisperx.load_align_model(language_code=language_code, device=DEVICE)


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
):
    """
    Upload an audio file and get back transcribed, aligned, and diarized segments.

    Returns JSON with:
      - language: detected language code
      - segments: list of {start, end, text, speaker, overlap}
      - processing_time_s: wall-clock time
    """
    if Models.asr_model is None:
        raise HTTPException(status_code=503, detail="Models not loaded yet")

    # Save uploaded file to a temp location
    suffix = Path(file.filename).suffix if file.filename else ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        start_time = time.time()

        # Step 0 — Detect stereo layout (split-channel telephony recordings).
        # When present, we bypass PyAnnote and assign roles by channel energy.
        stereo_layout = detect_stereo_layout(tmp_path)
        diarization_strategy = "channel" if stereo_layout else "cluster"

        # Step 1 — Transcribe
        audio = whisperx.load_audio(tmp_path)
        result = Models.asr_model.transcribe(audio, batch_size=16, language=language)
        detected_language = result["language"]

        # Step 2 — Align
        try:
            model_a, metadata = _load_align_model_with_retry(detected_language)
            result = whisperx.align(
                result["segments"], model_a, metadata, audio, DEVICE,
                return_char_alignments=False,
            )
            # Free alignment model right away
            del model_a, metadata
            gc.collect()
            if DEVICE == "cuda":
                torch.cuda.empty_cache()
        except Exception as align_exc:
            print(f"⚠ WARNING: alignment unavailable ({align_exc.__class__.__name__}: {align_exc})")

        # Step 3 — Diarize. Channel-aware path bypasses PyAnnote when the
        # source is split-channel telephony (agent on L, customer on R).
        if diarization_strategy == "channel":
            assert stereo_layout is not None  # set in lockstep above
            result["segments"] = assign_speakers_by_channel(
                tmp_path,
                result["segments"],
                agent_channel=stereo_layout["agent_channel"],
            )
        elif Models.diarize_model is not None:
            diarize_segments = Models.diarize_model(audio)
            result = whisperx.assign_word_speakers(diarize_segments, result)
            for segment in result["segments"]:
                segment.setdefault("speaker_meta", {})
                segment["speaker_meta"].setdefault("source", "diarization")
                segment["speaker_meta"].setdefault("strategy", "cluster")
                segment["speaker_meta"].setdefault("confidence", 1.0)
        else:
            for segment in result["segments"]:
                segment.setdefault("speaker", "UNKNOWN")
                segment.setdefault("speaker_meta", {})
                segment["speaker_meta"].setdefault("source", "unknown")
                segment["speaker_meta"].setdefault("strategy", "cluster")
                segment["speaker_meta"].setdefault("fallback_reason", "diarization_unavailable")

        # Step 4 — Optional speaker role relabeling.
        # Skip the text-based relabel in channel mode — the channel signal is
        # already ground-truth-grade and shouldn't be second-guessed.
        if diarization_strategy != "channel":
            result["segments"] = Models.speaker_role_classifier.relabel_segments(result["segments"])

        # Step 4b — Merge over-segmented same-speaker fragments. WhisperX VAD
        # tends to split sentences into many sub-second pieces; downstream
        # emotion + diarization both suffer from that. We collapse them here.
        result["segments"] = merge_short_same_speaker_segments(result["segments"])

        # Step 5 — Overlap detection
        result["segments"] = detect_overlaps(result["segments"])

        # Build clean response
        segments = []
        for seg in result["segments"]:
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg.get("text", "").strip(),
                "speaker": seg.get("speaker", "UNKNOWN"),
                "overlap": seg.get("overlap", False),
                "speaker_meta": seg.get("speaker_meta") or {},
            })

        elapsed = time.time() - start_time

        return JSONResponse(content=_numpy_to_python({
            "language": detected_language,
            "segments": segments,
            "processing_time_s": round(elapsed, 2),
            "diarization_strategy": diarization_strategy,
            "stereo_layout": stereo_layout,
        }))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        os.unlink(tmp_path)
