# RAG Vector Retrieval Microservice

The RAG (Retrieval-Augmented Generation) system provides document ingestion, vector database management, and query adapters to ground LLM evaluations and assistant responses.

---

## 1. Core Architecture: Dual Collections

VocalMind utilizes Qdrant as its vector database, isolating documents across two distinct collections to optimize for different retrieval granularities:

| Collection | Granularity | Encodings | Primary Consumers |
| :--- | :--- | :--- | :--- |
| **`vocalmind_parents`** | Parent headers (H1/H2/H3 splits) | 1024-dim dense vectors (`snowflake-arctic-embed2`) | Compliance evaluations, NLI policy checks, and SOP step analysis. Surfaced as *Provenance Cards*. |
| **`vocalmind_children`** | 400-character child segments with 80-character overlap | 1024-dim dense vectors (`snowflake-arctic-embed2`) | Text-to-SQL Manager Assistant Q&A answer synthesis. |

> [!NOTE]
> Policy documents are indexed at both parent and child levels. SOP and KB documents are only indexed at the parent level, as compliance evaluations require the entire context (exceptions, rules) of a step.

---

## 2. Ingestion Pipeline & CLI Commands

The ingestion pipeline parses PDFs, cleans text formatting, generates deterministic UUIDs using content hashing (ensuring duplicate uploads overwrite rather than double-index), embeds chunks using Ollama, and uploads them to Qdrant.

### Ingestion CLI commands
Ingestion is executed via the `services/rag/main.py` entry point:
*   **Full Ingestion**: Ingests new PDF documents.
    ```bash
    python main.py --ingest
    ```
*   **Force Re-ingest**: Wipes existing Qdrant collections and builds them fresh from source files.
    ```bash
    python main.py --ingest --force
    ```
*   **Document Watcher**: Continuously monitors the document directories, executing ingestion on file changes.
    ```bash
    python main.py --watch
    ```

---

## 3. Deep Dive References

For detailed guides on RAG subsystems, read the dedicated documentation:
*   **[RAG Retrieval Overview](../rag/RAG_OVERVIEW.md)**: Details vector layouts, similarity formulas, and runtime adapters.
*   **[RAG Ingestion Pipeline](../rag/INGESTION_PIPELINE.md)**: Details PDF parsing via Docling, text cleaning, chunking rules, and metadata generation.
