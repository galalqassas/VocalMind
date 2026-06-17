# Knowledge Base & Policy Management

This operations guide explains how to add, ingest, and manage compliance policies, Standard Operating Procedures (SOPs), and FAQ documents within the VocalMind RAG system.

---

## 1. Document Directories & Paths

To ground the retrieval systems, documents are organized by tenant organization within the `storage/docs/{org_slug}/` directory:

| Category | Storage Folder | Description |
| :--- | :--- | :--- |
| **Policies** | `policy-docs/` | Organization compliance rules (e.g. *Refund Eligibility*). checked during NLI compliance runs. |
| **SOP Procedures** | `sop-procedures/` | Step-by-step resolution scripts (e.g. *Billing Dispute SOP*). Used to evaluate agent process adherence. |
| **Knowledge Base** | `knowledge-base/` | General reference guides and FAQs used by the AI Assistant to synthesize responses. |

> [!IMPORTANT]
> All source files added to these folders **must be in PDF format**. Other formats (such as `.txt`, `.docx`, or `.md`) will be ignored by the ingestion scanner.

---

## 2. Ingestion Workflow

When new PDFs are added to the storage folders, they must be parsed and uploaded to the Qdrant vector database:

1.  **Add Document**: Drop the PDF file into the appropriate directory.
2.  **Execute Ingestion**: Run the ingestion CLI in the RAG service directory:
    ```bash
    cd services/rag
    python main.py --ingest
    ```
    This triggers the Docling parser, cleans formatting, generates embeddings via Ollama, and inserts vector points into Qdrant.
3.  **Force Reindexing**: If a file was updated or collection schemas changed, wipe collections and re-ingest all files using the `--force` flag:
    ```bash
    python main.py --ingest --force
    ```
4.  **Verification**: Confirm that parsed markdown outputs were created in `storage/docs/{org_slug}/parsed-docs/`.

---

## 3. UI Management & Troubleshooting

### 3.1 Policy & FAQ Toggles
Managers do not need to run terminal commands to enable or disable policies:
*   Navigate to the **Knowledge Base** screen in the Manager Portal.
*   Toggle the rule's active switch. Disabled policies remain in the database but are excluded from active retrieval operations at runtime.

### 3.2 Troubleshooting Common RAG Issues
*   **Empty Retrievals**: Verify that the document organization slug matches the interaction's tenant slug. Check if `audio_folder_watcher.py` mapped the call to the correct org.
*   **Connection Refused**: Asserts that Qdrant (`:6333`) and Ollama (`:11434`) containers are running and reachable.
*   **Dimension Mismatch**: If you change the Ollama embedding model, wipe Qdrant collections completely using `--ingest --force` to prevent dimension mismatch errors.
