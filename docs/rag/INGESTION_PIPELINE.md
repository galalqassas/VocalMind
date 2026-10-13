# Ingestion Pipeline

PDF → Markdown → chunks → embeddings → Qdrant. Implementation: `DocumentIngestionPipeline` in `services/rag/ingest.py`; entry point `services/rag/main.py`. Collection roles: [RAG_OVERVIEW.md](RAG_OVERVIEW.md).

## Running

- Models run where `RAG_MODELS_HOST` says (`services/rag/config.py`): `kaggle` (compose default) sends parsing to Kaggle `/parse` and embeddings to `/embed` at `KAGGLE_SERVER_URL`; `local` (Settings default) uses in-process Docling (the `local-models` extra; Docker build arg `RAG_LOCAL_MODELS=true`) and Ollama. Switching changes the embedding model, so re-ingest with `--force`.
- Compose: the `ingestion` container runs `python main.py --watch` (needs healthy `qdrant`; with `local`, also the `local-ml` profile's `ollama` with the model pulled via `make ollama-pull-embed`).
- Manual, from `services/rag`: `uv run python main.py --ingest` (add `--force` to drop and recreate all three collections first).
- `--watch [--interval N]` (default 60 s, minimum 10) snapshots PDF mtimes/sizes under the doc roots and, on any change, re-runs the full ingestion over every PDF.

## Discovery

Roots: `DOCS_DIR`, `POLICY_DOCS_DIR`, `KNOWLEDGE_DOCS_DIR` (all default to `storage/docs`, de-duplicated). For each org directory, PDFs are collected from `policy-docs/`, `sop-procedures/`, `faq-docs/`, `kb/`, `knowledge-base/`. If none of those folders exist, PDFs in the org root are used. If no PDFs are found at all, roots are scanned recursively and the first path component becomes the org.

`doc_type` is chosen from the path: `/kb/` or `/knowledge-base/` → `kb`; `/sop-procedures/` or `/faq-docs/` → `sop`; anything else → `policy`.

## Per-file steps (`_process_file`)

1. **Parse**: Docling `DocumentConverter` → Markdown (in-process, or Kaggle `/parse` with a 600 s timeout).
2. **Clean**: `ftfy` + HTML-entity fixes, re-attach orphaned table rows, normalize spacing around arrow glyphs.
3. **Metadata**: `org`, `department`, `doc_id`, `version`, `effective_date` from a `| Field | Value |` header table or `**Label**: value` lines (default `Unknown`); `org` is overridden by the folder name; plus `source_file` (PDF stem), `ingested_at`, `doc_type`.
4. **Parent split**: `MarkdownHeaderTextSplitter` on H1/H2/H3; sections under 4 words are dropped. Type metadata is added: SOP → `policy_ref` (rule IDs referenced in the text); policy → rule metadata (`rule_id`, `severity`, …); KB → `section` (header path).
5. **Child split** (stored for policies only): pipe-table rows whose first cell matches `[A-Z]{2,5}-RULE-<n>` become one `policy_rule_atomic` chunk each; other tables stay whole (`table_atomic`); text uses `RecursiveCharacterTextSplitter` (400 chars, 80 overlap; `chunk_type=text`).
6. **Validate**: flags chunks under 30 chars, duplicates (MD5), atomic policy-rule chunks missing `rule_id`/`rule_statement`/`severity`, KB chunks without a section.
7. **Debug artifacts** in `{PARSED_POLICY_DIR | PARSED_SOP_DIR}/{org}/parsed-docs/{policies | sops | kb}/`: `{stem}_raw.md`, `{stem}.md`, `{stem}_chunks.md`, `{stem}_validation.json`.
8. **Upload**: delete existing points for the same `org` + `source_file`, then embed the chunks (Kaggle: batches of 32 per request; Ollama: one per request) and upsert. SOP/KB parents → `vocalmind_sop_parents`; policy parents → `vocalmind_parents`, policy children → `vocalmind_children`.

A run summary is written to `{PARSED_DIR}/_pipeline_report.json`.

## Qdrant and embeddings

- Collections are created on startup if missing (cosine, `EMBEDDING_DIMENSION`, default 1024) and recreated if their dimension differs.
- Point IDs are a UUID from MD5 of `source_file:org:content`, so re-ingesting identical content is idempotent.
- Payload = `text` + all chunk metadata (`org`, `doc_type`, `source_file`, `Header 1..3`, `chunk_type`, …).
- Embeddings: `RAG_MODELS_HOST=kaggle` → Kaggle `/embed` (`Snowflake/snowflake-arctic-embed-l-v2.0`, normalized, 1024-d; no fallback). `local` → Ollama `/api/embed` then `/api/embeddings`, up to 4 attempts with backoff (`snowflake-arctic-embed2`), or Ollama Cloud `/embeddings` when `OLLAMA_CLOUD_EMBED_ENABLED=true`.
- Startup check: `_verify_ollama` embeds a test string (Kaggle: `_verify_kaggle`, which also checks the dimension) and aborts on failure.

## Consumers of the parsed Markdown

The backend's manual SOP path reads `storage/docs/{org}/parsed-docs/sops/{stem}.md` for each PDF in `sop-procedures/` or `faq-docs/` (`backend/app/llm_trigger/retrieval.py`).

## Troubleshooting

- No PDFs found: check folder names and the `.pdf` extension.
- Empty retrieval: confirm points exist for the org slug (`org` payload) and that `parsed-docs/` artifacts were written.
- Embedding errors: with `kaggle`, check the notebook is running and `KAGGLE_SERVER_URL` is set for the ingestion process; with `local`, check `OLLAMA_BASE_URL` and that `snowflake-arctic-embed2` is pulled.
- `ModuleNotFoundError: docling` with `local`: install `uv sync --extra local-models` (or rebuild the image with `RAG_LOCAL_MODELS=true`).
- After changing `RAG_MODELS_HOST` or the embedding model: run `--ingest --force`.

Removing a PDF does not delete its points; only a re-ingested file has its old points replaced.

Tests: `cd services/rag && uv run pytest tests/test_ingest.py tests/test_kaggle_models.py -q`.
