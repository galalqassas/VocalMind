# VocalMind Documentation Portal

Welcome to the VocalMind project documentation index. This portal contains all user manuals, operations manuals, system architecture deep dives, API references, and microservices documentation.

---

## 1. Get Started (User & Setup Guides)

*   **[Deployment & Setup Guide](./operations/DEPLOYMENT.md)**: Steps to launch VocalMind in Docker, CPU/GPU options, and local dev setup.
*   **[Manager User Guide](./user-guide/MANAGER_GUIDE.md)**: Navigating the Manager Dashboard, call detail analysis, evidence cards, and Assistant.
*   **[Agent User Guide](./user-guide/AGENT_GUIDE.md)**: Coaching details, performance trends, and the emotion dispute workflow.

---

## 2. System Architecture Deep Dives

*   **[System Architecture Overview](./architecture/SYSTEM_OVERVIEW.md)**: High-level component interactions, network topology, and tenancy.
*   **[Backend Gateway Architecture](./architecture/BACKEND_ARCHITECTURE.md)**: FastAPI gateway directories, lifespan contexts, and workers.
*   **[Audio Processing Pipeline](./architecture/AUDIO_PROCESSING_PIPELINE.md)**: Pipeline stages, in-memory queues, and diarization.
*   **[Database Schema Reference](./architecture/DATABASE_SCHEMA.md)**: Transactional data dictionary mapping 18 SQLModel tables and 10 enums.
*   **[Emotion Fusion Architecture](./architecture/EMOTION_FUSION.md)**: Dual-signal fusion formulas, modality agreement weight metrics, and fallback heuristics.
*   **[Frontend Architecture Guide](./frontend/FRONTEND_ARCHITECTURE.md)**: React 18 SPA directories, routing hierarchies, and explainability UI.
*   **[Evidence-Anchored Explainability](./explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md)**: Span-level triggers and claim retrieval provenance mapping.
*   **[LLM Trigger Engine](./llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md)**: The 3-chain judging engine and prompt protections.
*   **[RAG Retrieval Overview](./rag/RAG_OVERVIEW.md)**: Indexing granularities, parent/child splits, and vector mapping.
*   **[RAG Ingestion Pipeline](./rag/INGESTION_PIPELINE.md)**: Document parsing via Docling, cleans, and Qdrant loads.
*   **[Pipeline Evaluation Findings](./eval/PIPELINE_FINDINGS.md)**: Pipeline performance compared to ground truth samples.

---

## 3. Microservice References

*   **[VAD Service](./microservices/VAD_SERVICE.md)**: Silero Voice Activity Detection voice segmentation service.
*   **[WhisperX Service](./microservices/WHISPERX_SERVICE.md)**: Transcription, PyAnnote diarization, segment merging, and speaker roles.
*   **[Emotion Service](./microservices/EMOTION_SERVICE.md)**: funASR emotion2vec speech emotion and DistilRoBERTa text emotion classifiers.
*   **[RAG Service](./microservices/RAG_SERVICE.md)**: Parent/child collections, RAG retrieval adaptors, and ingestion scripts.

---

## 4. Operational Runbooks

*   **[Knowledge Base & PDF Ingestion](./operations/KNOWLEDGE_BASE_MANAGEMENT.md)**: Adding policies/SOPs, running CLI ingestion, and troubleshooting.
*   **[Audio Auto-Ingest Scanner](./operations/AUDIO_AUTO_INGEST.md)**: Background watcher directories, filename rules, and queues.
*   **[Evaluation & Benchmarking Harness](./operations/EVALUATION_HARNESS.md)**: Command line tools, evaluation metrics, and gold standard runs.
*   **[Manager Assistant NL-to-SQL](./llm_trigger/MANAGER_ASSISTANT.md)**: SQL execution parsers, LLM fallbacks, and security check filters.

---

## 5. API & Configuration References

*   **[REST API Reference](./api/REST_API_REFERENCE.md)**: Controller routes dictionary, authentication endpoints, schema inputs, and responses.
*   **[Configuration Env Dictionary](./backend/CONFIGURATION.md)**: Environment configurations, defaults, and usage.
*   **[Security & RBAC Controls](./backend/SECURITY.md)**: JWT creation, password hashing, OAuth callbacks, and SQL injection guards.
*   **[Testing & Verification Guide](./backend/TESTING.md)**: Running FastAPI pytests, frontend Vitest/Cypress suites, and benchmark tools.
