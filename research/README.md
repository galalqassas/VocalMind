# Research

Notebooks and scripts from the research phase. Nothing here is imported or run by the application.

| Directory | Contents |
|---|---|
| `asr/` | WhisperX ASR experiments (`automatic-speech-recognition.ipynb`) |
| `diarization/` | Speaker diarization experiments (`speaker diarization.ipynb`) |
| `Evaluation/` | Diarization error rate evaluation (`DER eval.ipynb`) |
| `emotion/` | Speech and text emotion model comparisons (4 notebooks) |
| `finetuning/` | LLM LoRA fine-tuning experiment on Kaggle (`finetuning v0.1.ipynb`) |
| `speech-pipeline/` | Combined ASR → diarization → emotion prototype (`pipeline_experiment.py`) |
| `training/` | `customerAgentClassifier.ipynb`: trains agent/customer utterance classifiers on TF-IDF features and logs the runs to MLflow (DagsHub). A final cell downloads the best logistic-regression run and saves `model.pkl` + `vectorizer.pkl` to the working directory. Copy both into `backend/app/core/`, where `interaction_processing.py` loads them. |
| `voice-gen/` | TTS scripts used to generate synthetic calls |

Run the notebooks in your own environment (`pip install jupyterlab && jupyter lab`). Some need a GPU and model downloads.
