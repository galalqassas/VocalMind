# WhisperX Audio Transcription & Diarization Microservice

This microservice provides automated speech recognition (ASR), word-level alignment, speaker diarization, and speaker-role classification by wrapping the **WhisperX** pipeline.

---

## 1. System Specifications & Configuration

*   **Port**: `:8003`
*   **Technology Stack**: Python, WhisperX, PyAnnote (diarization), PyTorch, torchaudio, DistilBERT (for text-based speaker role classification)
*   **CUDA passthrough**: Runs on `cuda` if GPU is available (using `float16` compute type), otherwise falls back to `cpu` (using `int8` compute type).
*   **Key Environment Settings**:
    *   `HF_TOKEN`: Required. Authenticates access to the PyAnnote diarization model on Hugging Face.
    *   `WHISPER_MODEL_SIZE`: Whisper model size (defaults to `large-v2`).
    *   `CHANNEL_DIARIZATION_ENABLED`: Enables channel-based layout checks for stereo telephony calls.
    *   `SPEAKER_ROLE_MODEL_ENABLED`: Enables DistilBERT classifier.
    *   `BACKEND_SPEAKER_RELABEL_ENABLED`: **Must remain `false`** to prevent duplicate relabeling loops.

---

## 2. API Specifications

### `POST /transcribe`
Ingests an audio recording, transcribes speech, divides segments by speaker, and labels roles.
*   **Content-Type**: `multipart/form-data`
*   **Request Body**:
    *   `file` (binary, required): The WAV/MP3 recording file.
    *   `diarization_strategy` (string, optional): Overrides strategy (`stereo_only`, `pyannote_only`, or `auto`).
*   **Response**:
    ```json
    {
      "segments": [
        {
          "start": 0.45,
          "end": 3.82,
          "text": "Hello, thank you for calling customer service.",
          "speaker": "SPEAKER_00",
          "speaker_role": "agent",
          "confidence": 0.941
        },
        {
          "start": 4.12,
          "end": 8.91,
          "text": "Hi, I have a dispute on my last billing statement.",
          "speaker": "SPEAKER_01",
          "speaker_role": "customer",
          "confidence": 0.887
        }
      ],
      "language": "en",
      "diarization_strategy": "stereo_by_channel"
    }
    ```

### `GET /health`
*   **Response**:
    ```json
    {
      "status": "ok",
      "device": "cuda",
      "whisper_model": "large-v2"
    }
    ```

---

## 3. Stereo Channel & Segment Merge Heuristics

### 3.1 Stereo channel-aware diarization
If `CHANNEL_DIARIZATION_ENABLED` is true and a stereo file is uploaded, the service analyzes the channels:
1.  **Correlation Check**: Computes correlation between channels. If correlation is lower than `CHANNEL_DIARIZATION_MAX_CORR`, it treats the channels as isolated speaker lines (common in PBX setups).
2.  **Layout Selection**: Determines which channel maps to the `agent` vs. `customer` by evaluating signal energy in the first 8 seconds.

### 3.2 Segment Merge Pass (`merge_short_same_speaker_segments`)
WhisperX/PyAnnote tend to fragment continuous turns into micro-segments (e.g. "Okay.", "Sure."). The merger:
*   Glues adjacent turns by the same speaker when gaps are under `1.2s` (`max_gap_s`).
*   Prevents bloated segments by capping merged turns at `22.0s` (`max_merged_s`).
*   Absorbs short fragments (< `1.5s`) into neighboring segments to clean up noise.

---

## 4. DistilBERT Speaker Role Classifier

If enabled (`SPEAKER_ROLE_MODEL_ENABLED`), the service uses a 3-tier classification path:
1.  **Lexical Cue Rules**: Identifies standard greetings or structural agent markers (e.g. *"Thank you for calling NexaLink, my name is..."*).
2.  **DistilBERT Classifier**: A text model trained on conversational scripts to classify agent vs. customer turns.
3.  **Diarization Fallback**: If models disagree or return low confidence, the pipeline falls back to assigning speaker IDs based on turn density.
