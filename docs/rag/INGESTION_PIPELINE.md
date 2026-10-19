# Ingestion Pipeline

PDF → Markdown → chunks → embeddings → Qdrant. Implementation: `DocumentIngestionPipeline` in `services/rag/ingest.py`; entry point `services/rag/main.py`. Collection roles: [RAG_OVERVIEW.md](RAG_OVERVIEW.md).

## Running

- Compose: the `ingestion` container runs `python main.py --watch` (needs healthy `qdrant` and `ollama`; pull the model once with `make ollama-pull-embed`).
- Manual, from `services/rag`: `uv run python main.py --ingest` (add `--force` to drop and recreate all three collections first).
- `--watch [--interval N]` (default 60 s, minimum 10) snapshots PDF mtimes/sizes under the doc roots and, on any change, re-runs the full ingestion over every PDF.

## Discovery

Roots: `DOCS_DIR`, `POLICY_DOCS_DIR`, `KNOWLEDGE_DOCS_DIR` (all default to `storage/docs`, de-duplicated). For each org directory, PDFs are collected from `policy-docs/`, `sop-procedures/`, `faq-docs/`, `kb/`, `knowledge-base/`. If none of those folders exist, PDFs in the org root are used. If no PDFs are found at all, roots are scanned recursively and the first path component becomes the org.

`doc_type` is chosen from the path: `/kb/` or `/knowledge-base/` → `kb`; `/sop-procedures/` or `/faq-docs/` → `sop`; anything else → `policy`.

## Per-file steps (`_process_file`)

1. **Parse**: Docling `DocumentConverter` → Markdown.
2. **Clean**: `ftfy` + HTML-entity fixes, re-attach orphaned table rows, normalize spacing around arrow glyphs.
3. **Metadata**: `org`, `department`, `doc_id`, `version`, `effective_date` from a `| Field | Value |` header table or `**Label**: value` lines (default `Unknown`); `org` is overridden by the folder name; plus `source_file` (PDF stem), `ingested_at`, `doc_type`.
4. **Parent split**: `MarkdownHeaderTextSplitter` on H1/H2/H3; sections under 4 words are dropped. Type metadata is added: SOP → `policy_ref` (rule IDs referenced in the text); policy → rule metadata (`rule_id`, `severity`, …); KB → `section` (header path).
5. **Child split** (stored for policies only): pipe-table rows whose first cell matches `[A-Z]{2,5}-RULE-<n>` become one `policy_rule_atomic` chunk each; other tables stay whole (`table_atomic`); text uses `RecursiveCharacterTextSplitter` (400 chars, 80 overlap; `chunk_type=text`).
6. **Validate**: flags chunks under 30 chars, duplicates (MD5), atomic policy-rule chunks missing `rule_id`/`rule_statement`/`severity`, KB chunks without a section.
7. **Debug artifacts** in `{PARSED_POLICY_DIR | PARSED_SOP_DIR}/{org}/parsed-docs/{policies | sops | kb}/`: `{stem}_raw.md`, `{stem}.md`, `{stem}_chunks.md`, `{stem}_validation.json`.
8. **Upload**: delete existing points for the same `org` + `source_file`, then embed each chunk and upsert. SOP/KB parents → `vocalmind_sop_parents`; policy parents → `vocalmind_parents`, policy children → `vocalmind_children`.

A run summary is written to `{PARSED_DIR}/_pipeline_report.json`.

## Qdrant and embeddings

- Collections are created on startup if missing (cosine, `EMBEDDING_DIMENSION`, default 1024) and recreated if their dimension differs.
- Point IDs are a UUID from MD5 of `source_file:org:content`, so re-ingesting identical content is idempotent.
- Payload = `text` + all chunk metadata (`org`, `doc_type`, `source_file`, `Header 1..3`, `chunk_type`, …).
- Embeddings: Ollama `/api/embed` then `/api/embeddings`, up to 4 attempts with backoff; Ollama Cloud `/embeddings` when `OLLAMA_CLOUD_EMBED_ENABLED=true`.

## Consumers of the parsed Markdown

The backend's manual SOP path reads `storage/docs/{org}/parsed-docs/sops/{stem}.md` for each PDF in `sop-procedures/` or `faq-docs/` (`backend/app/llm_trigger/retrieval.py`).

## Troubleshooting

- No PDFs found: check folder names and the `.pdf` extension.
- Empty retrieval: confirm points exist for the org slug (`org` payload) and that `parsed-docs/` artifacts were written.
- Embedding errors: check `OLLAMA_BASE_URL` and that `snowflake-arctic-embed2` is pulled.
- Dimension warnings after changing models: run `--ingest --force`.

Removing a PDF does not delete its points; only a re-ingested file has its old points replaced.

Tests: `cd services/rag && uv run pytest tests/test_ingest.py -q`.
