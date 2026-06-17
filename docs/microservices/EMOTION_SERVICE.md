# Speech & Text Emotion Recognition Microservice

This microservice provides speech emotion classification using Alibaba's **funASR emotion2vec** model, alongside text sentiment classification using a **DistilRoBERTa** model.

---

## 1. Operational Parameters

*   **Host Port**: `:8001`
*   **Technology Stack**: Python, FastAPI, funASR, PyTorch, Hugging Face Transformers (`j-hartmann/emotion-english-distilroberta-base`), FFmpeg (for runtime audio normalizations)
*   **Device Allocation**: CUDA acceleration is automatically bound if NVIDIA drivers are present, otherwise execution defaults to CPU.

---

## 2. API Specifications

### `POST /predict`
Classifies acoustic emotional state from an uploaded WAV/MP3 clip.
*   **Audio Norms**: FFmpeg is executed at runtime to downmix files to mono, resample to 16kHz, and truncate them to 30 seconds (`EMOTION_MAX_AUDIO_SECONDS`).
*   **Content-Type**: `multipart/form-data`
*   **Request Body**:
    *   `file`: Binary audio file (MP3 or WAV).
*   **Response**:
    ```json
    {
      "emotion": "happy",
      "confidence": 0.842,
      "raw_result": {
        "labels": ["happy", "angry", "sad", "neutral", "frustrated", "surprised", "fearful"],
        "scores": [0.842, 0.01, 0.02, 0.05, 0.03, 0.02, 0.03]
      }
    }
    ```

### `POST /predict_text`
Evaluates text emotion using DistilRoBERTa.
*   **Request Body** (`application/json`):
    ```json
    {
      "text": "This is ridiculous! I want a refund."
    }
    ```
*   **Response**:
    ```json
    {
      "emotion": "anger",
      "confidence": 0.923,
      "raw_result": [
        { "label": "anger", "score": 0.923 },
        { "label": "disappointment", "score": 0.04 }
      ]
    }
    ```

### `GET /health`
*   **Response**:
    ```json
    {
      "status": "ok",
      "audio_model_loaded": true,
      "text_model_loaded": true
    }
    ```

---

## 3. Modality Normalizations & Fallbacks

1.  **Label Normalization**: Raw emotion labels from models are mapped to VocalMind's 7 canonical emotion states: `happy`, `frustrated`, `neutral`, `sad`, `angry`, `surprised`, `fearful`.
    *   Acoustic mappings: `joy -> happy`, `calm -> neutral`, `satisfied -> happy`, `fear -> frustrated`, `disgust -> frustrated`.
    *   Text mappings: `joy / happiness -> happy`, `anger -> angry`, `fear / disgust / annoyance -> frustrated`, `surprise -> neutral`, `sadness -> sad`.
2.  **Text Fallback**: If the text emotion model fails to load, `/predict_text` returns a `503 Service Unavailable`. The backend seamlessly catches this and falls back to a rule-based lexicon match (`emotion_fusion.py`), ensuring system robustness.
