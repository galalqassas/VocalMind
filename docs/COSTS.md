# VocalMind — Per-Call Cost Model

> Back-of-envelope estimate to satisfy the maturity-gap §15 cost-awareness
> requirement. **Numbers marked `[VERIFY]` are public list prices or
> typical cloud rates that someone with billing access should confirm
> before quoting these in a proposal.** Numbers marked `[MEASURE]` are
> placeholders the team should replace with actual telemetry once the
> Prometheus `/metrics` endpoint we just landed has a week of data.

## 1. Cost surface per processed call

A single ~5-minute call touches five priced components:

| Component | Resource | Variable | Fixed |
|---|---|---|---|
| WhisperX | GPU compute | ✓ (scales with audio length) | |
| Acoustic emotion | GPU/CPU | ✓ | |
| LLM trigger | Groq tokens | ✓ (scales with transcript length) | |
| RAG | Ollama CPU + Qdrant RAM | mostly fixed | ✓ |
| Postgres + storage | DB compute + disk | small | ✓ |

The two that dominate by an order of magnitude: **WhisperX** and **LLM
trigger**.

## 2. WhisperX (the long pole)

Single call ≈ 1× audio realtime on a T4-class GPU after the optimisations
in [`docs/eval/PIPELINE_FINDINGS.md`](eval/PIPELINE_FINDINGS.md). So a
5-minute call = ~5 GPU-minutes.

| GPU class | Spot $/hr `[VERIFY]` | Cost per 5-min call |
|---|---|---|
| T4 (16 GB) | ~$0.35 | ~$0.029 |
| L4 (24 GB) | ~$0.55 | ~$0.046 |
| A10G (24 GB) | ~$0.75 | ~$0.063 |

Add ~20 % overhead for cold-start and queue idle time → **~$0.04–0.08
per call** on a T4–A10G, depending on provider.

If batching ≥ 4 calls into a single WhisperX worker (currently we don't
— one job at a time), the per-call cost drops roughly 35 %.

## 3. LLM trigger (Groq)

Three chains fan out via `asyncio.gather` per call:

1. **Emotion shift analysis** — prompt + few-shot ≈ `[MEASURE]` tokens in, ≈ `[MEASURE]` out
2. **Process adherence** — prompt + retrieved SOP chunks ≈ `[MEASURE]` in, ≈ `[MEASURE]` out
3. **NLI policy check** — prompt + policy chunks ≈ `[MEASURE]` in, ≈ `[MEASURE]` out

Order-of-magnitude estimate while we wait for real numbers:

| Chain | Input tokens | Output tokens |
|---|---|---|
| Emotion shift | ~2,500 | ~400 |
| Process adherence | ~3,500 | ~500 |
| NLI policy | ~3,000 | ~400 |
| **Total per call** | **~9,000 in** | **~1,300 out** |

At `llama-3.3-70b-versatile` Groq list pricing `[VERIFY]` (~$0.59 / 1 M
input, ~$0.79 / 1 M output as of early 2026):

```
in:  9,000  / 1,000,000 × $0.59 = $0.0053
out: 1,300  / 1,000,000 × $0.79 = $0.0010
                                  ─────────
                                  $0.0063
```

→ **~$0.006–0.01 per call** for the LLM trigger.

## 4. Manager Assistant (separate from per-call)

The Manager Assistant uses **Gemini 2.0-flash** primary + **Qwen2.5:7b
Ollama** fallback. It's not invoked per call — it's invoked when a
manager asks the assistant a question.

- Gemini 2.0-flash list `[VERIFY]`: ~$0.075 / 1 M input, ~$0.30 / 1 M
  output. A typical assistant query ≈ 4,000 in / 500 out → ~$0.0005.
- Ollama fallback runs on the host (Qwen2.5:7b) — $0 marginal cost but
  ~5 GB RAM permanently reserved.

Negligible against per-call cost.

## 5. RAG (mostly fixed)

| Item | Cost shape |
|---|---|
| Qdrant container | ~1 GB RAM, single node — fixed |
| Ollama `snowflake-arctic-embed2` | ~2 GB RAM, single node — fixed |
| Embedding generation at ingest | ~200 chunks/policy doc × ~0.05 s on Ollama — one-off per policy |

Treat RAG as part of fixed infra (§7) — it doesn't scale linearly with
call volume.

## 6. Per-call total

| Component | Per call (low) | Per call (high) |
|---|---|---|
| WhisperX GPU | $0.04 | $0.08 |
| LLM trigger (Groq) | $0.006 | $0.01 |
| Postgres + storage | ~$0.0005 | ~$0.001 |
| **Total per call** | **~$0.05** | **~$0.09** |

## 7. Monthly run-rate scenarios

Assuming 22 working days / month and a 5-minute average call.

| Scale | Calls / day | Calls / month | Per-call (avg $0.07) | Fixed infra `[VERIFY]` | **Monthly $** |
|---|---|---|---|---|---|
| Demo (graduation) | 50 | 1,100 | $77 | $80 (1× small VM + dev GPU on-demand) | **~$160** |
| Small contact centre | 500 | 11,000 | $770 | $250 (small VM + persistent GPU spot + managed Postgres) | **~$1,020** |
| Mid contact centre | 5,000 | 110,000 | $7,700 | $600 (HA backend + 2× GPU + managed Postgres + Qdrant cloud) | **~$8,300** |

Cost per processed call stays in the $0.05–0.09 band across all scales
— the variable component dominates. Fixed infra rises only when we move
from one box to HA + managed services.

## 8. Where the cost actually comes from

If you have $100 of budget to optimise, spend it in this order:

1. **WhisperX batching** — biggest single lever. 4-way batching cuts
   the dominant per-call cost ~35 %.
2. **LLM prompt size** — every 1,000 tokens trimmed from the three
   prompts saves ~$0.0006 per call (×100,000 calls/month = $60).
3. **Spot vs on-demand GPU** — ~3× swing. Already assumed spot above.
4. **WhisperX model size** — `large-v3` → `medium.en` would roughly
   halve GPU time but breaks the WER guarantee in
   [`PIPELINE_FINDINGS.md`](eval/PIPELINE_FINDINGS.md). Don't.

## 9. Replacing the placeholders

`[MEASURE]` token counts will be replaced once the Prometheus `/metrics`
endpoint (landed in [`app/main.py`](../backend/app/main.py)) has been
scraped for a week. The LLM-trigger team is also looking at swapping
the provider (see thread on the in-flight branch); when that lands,
re-run section §3 with the new pricing — the structure of the model
stays the same.

`[VERIFY]` cloud / API prices need someone with billing access to pull
the current rate card. The numbers above are public list prices and
will be roughly correct at this order of magnitude.

---

> Cross-references: [`docs/MATURITY_GAP_ANALYSIS.md`](MATURITY_GAP_ANALYSIS.md) §15,
> [`docs/SLA.md`](SLA.md) §2 (latency targets that constrain the GPU
> sizing choice), [`docs/ADR-001-architecture.md`](ADR-001-architecture.md)
> (why WhisperX is an isolated service — informs the spot-GPU strategy).
