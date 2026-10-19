# Final Model Justification v10

> Historical record (2026-06-14). The raw run files and scripts it links to were removed from the tree; recover them with `git checkout archive/pre-cleanup-2026-10-13 -- infra/benchmarks infra/scripts`.

**Generated:** 2026-06-16 15:38 UTC  
**Scope:** full-population `emotion_shift` (170) + `nli_policy` (172), 8 models
**Source:** `D:\University\Grad\VocalMind\infra\benchmarks\reports\overnight_20260614\final_run_es_nli_8models_v10.json`  
**Rows after de-dup:** 2736

## Selection Criteria

1. Primary: exact match rate vs GT
2. Tie-breaker: parseable rate
3. Operational tie-breaker: p50 latency

## emotion_shift (friction diagnosis)

| Model | n | exact % | parseable % | p50 ms | GT avg |
|---|---:|---:|---:|---:|---:|
| ministral-3:8b | 170 | 54.1% | 90.6% | 74352 | 5.41 |
| kimi-k2.5:cloud | 170 | 51.8% | 86.5% | 93046 | 5.18 |
| deepseek-v3.1:671b | 170 | 51.2% | 85.9% | 96445 | 5.12 |
| gemma3:12b | 170 | 49.4% | 86.5% | 61345 | 4.94 |
| kimi-k2.6:cloud | 170 | 48.8% | 83.5% | 79533 | 4.88 |
| ministral-3:14b | 170 | 47.1% | 88.8% | 68350 | 4.71 |
| qwen3.5:cloud | 170 | 44.1% | 89.4% | 125163 | 4.41 |
| gpt-oss:20b | 170 | 10.0% | 20.6% | 72524 | 1.00 |

## nli_policy

| Model | n | exact % | parseable % | p50 ms | GT avg |
|---|---:|---:|---:|---:|---:|
| qwen3.5:cloud | 172 | 60.5% | 82.6% | 124371 | 6.05 |
| ministral-3:14b | 172 | 58.1% | 69.2% | 93896 | 5.81 |
| ministral-3:8b | 172 | 51.2% | 74.4% | 86521 | 5.12 |
| gemma3:12b | 172 | 50.6% | 59.9% | 83691 | 5.06 |
| kimi-k2.5:cloud | 172 | 48.8% | 69.2% | 103732 | 4.88 |
| kimi-k2.6:cloud | 172 | 44.2% | 62.8% | 95165 | 4.42 |
| deepseek-v3.1:671b | 172 | 43.6% | 57.0% | 92910 | 4.36 |
| gpt-oss:20b | 172 | 16.9% | 28.5% | 93668 | 1.69 |

## Recommended Production Models

- `OLLAMA_EMOTION_SHIFT_MODEL=ministral-3:8b`
- `OLLAMA_NLI_MODEL=qwen3.5:cloud`

Justification: highest exact with strong parseability and acceptable latency on full-population samples.