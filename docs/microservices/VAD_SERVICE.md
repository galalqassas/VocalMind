# VAD Preprocessing Microservice

This service is a thin voice activity detection (VAD) server wrapping the **Silero VAD** PyTorch model. It isolates speech intervals from raw `.wav` audio files.

---

## 1. Operations Details

*   **Port**: `:8002`
*   **Technology Stack**: Python, FastAPI, PyTorch, Snakers4 Silero VAD, Pydub (for slice editing)
*   **Startup Lifecycle**: The PyTorch VAD model is loaded dynamically from the hub during FastAPI's lifespan setup hook.

---

## 2. API Specifications

### `POST /split`
Accepts a raw `.wav` audio upload and slices it into segments where speech is active:
*   **Content-Type**: `multipart/form-data`
*   **Request Body**:
    *   `file`: Binary `.wav` file (must end in `.wav`).
*   **Response**:
    ```json
    {
      "total_segments": 2,
      "segments": [
        {
          "index": 0,
          "start_time": 0.32,
          "end_time": 3.45,
          "audio_base64": "UklGRiS..."
        },
        {
          "index": 1,
          "start_time": 4.12,
          "end_time": 9.87,
          "audio_base64": "UklGRiS..."
        }
      ]
    }
    ```

### `GET /health`
Liveness check to verify the PyTorch model has loaded successfully:
*   **Response**:
    ```json
    {
      "status": "ok",
      "model_loaded": true
    }
    ```

---

## 3. Integration & Configuration

The service is configured in backend environments using the `VAD_API_URL` setting.
If a `.wav` file fails to load or contain speech, `/split` returns an empty `segments` list rather than crashing. 
If VAD fails entirely, the backend catcher logs a traceback error and skips speech slicing.
