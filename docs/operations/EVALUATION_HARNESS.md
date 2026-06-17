# Evaluation Harness & Benchmark Tools

VocalMind includes a command-line evaluation harness to benchmark transcription, speaker alignment, emotion detection, and compliance reasoning against gold-standard ground truths.

---

## 1. Directory Structure & Files

The evaluation scripts are located under `tools/` and reference ground truth transcripts and benchmark reports:

*   **Ground Truth Files**: Located in `storage/audio/{org}/evaluation/` (contains transcripts, speaker divisions, and emotion labels verified by human supervisors).
*   **Evaluation Outputs**: Written to `tools/reports/EVAL_REPORT.md` and `EVAL_REPORT.json`.

---

## 2. Key Evaluation Scripts

*   **`tools/evaluate_pipeline.py`**: Runs the complete audio file pipeline against all evaluation call samples, computing precision, recall, and diarization accuracy metrics.
*   **`tools/reprocess_and_compare.py`**: Reprocesses a specific call and diffs its text output, sentiment flags, and compliance triggers directly against ground truths.
*   **`tools/compare_summary.py`**: Compares two evaluation report files to analyze performance changes (verifies no regressions occurred).
*   **`tools/download_mlflow_model.py`**: Script used to download the speaker classifier model assets directly from DagsHub.

---

## 3. The 8 Evaluation Axes

The harness measures pipeline success across 8 distinct axes:

1.  **`agent_match`**: Accuracy of assigning the interaction to the correct agent.
2.  **`topic_match`**: Precision of the topic classification engine.
3.  **`resolution_match`**: Correctness of call resolution heuristic outcomes.
4.  **`sop_retrieval_match`**: Relevance and precision of SOP document retrieval.
5.  **`avg_turn_ratio`**: Correctness of speaker turn segment divisions.
6.  **`avg_emotion_cosine_fused`**: Sentiment prediction cosine similarity against human labels.
7.  **`avg_diar_share_delta`**: Speaker speak-time duration share accuracy.
8.  **`avg_coverage_recall`**: Recall rate of SOP steps matched in the call.

---

## 4. Operational Commands

### 4.1 Running the Full Evaluation
To evaluate the active codebase against all benchmark files:
```bash
make quality-eval-all
# OR execute the script directly:
python tools/evaluate_pipeline.py
```

### 4.2 Groq Rate Limits Note
Because the compliance judging engine executes three LLM chains per call, running evaluations sequentially can hit Groq API rate limits (TPD/RPM). The LangChain wrappers in `app/llm_trigger/chains.py` implement exponential backoff retry algorithms to handle rate limits.
