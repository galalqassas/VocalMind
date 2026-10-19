# VocalMind Docs

Start with [../AGENTS.md](../AGENTS.md) (architecture, repo map, config, gotchas). Each doc below covers one topic and links to the source files it describes.

| Area | Doc |
|---|---|
| **Use** | [Manager guide](user-guide/MANAGER_GUIDE.md) · [Agent guide](user-guide/AGENT_GUIDE.md) |
| **Architecture** | [System overview](architecture/SYSTEM_OVERVIEW.md) · [Backend](architecture/BACKEND_ARCHITECTURE.md) · [Audio pipeline](architecture/AUDIO_PROCESSING_PIPELINE.md) · [Emotion fusion](architecture/EMOTION_FUSION.md) · [Database](architecture/DATABASE_SCHEMA.md) · [Frontend](frontend/FRONTEND_ARCHITECTURE.md) |
| **Reasoning** | [LLM triggers](llm_trigger/LLM_TRIGGER_FEATURE_GUIDE.md) · [Explainability](explainability/EVIDENCE_ANCHORED_EXPLAINABILITY_LAYER.md) · [Manager assistant](llm_trigger/MANAGER_ASSISTANT.md) |
| **RAG** | [Overview](rag/RAG_OVERVIEW.md) · [Ingestion](rag/INGESTION_PIPELINE.md) · [RAGAS evaluation](rag/RAGAS_EVALUATION.md) · [RAG service](../services/rag/README.md) |
| **Microservices** | [WhisperX](microservices/WHISPERX_SERVICE.md) · [Emotion](microservices/EMOTION_SERVICE.md) · [VAD](microservices/VAD_SERVICE.md) |
| **Reference** | [API routes](api/REST_API_REFERENCE.md) · [Configuration](backend/CONFIGURATION.md) · [Security](backend/SECURITY.md) · [Testing](backend/TESTING.md) |
| **Operations** | [Deployment & production](operations/DEPLOYMENT.md) · [Knowledge base](operations/KNOWLEDGE_BASE_MANAGEMENT.md) · [Audio auto-ingest](operations/AUDIO_AUTO_INGEST.md) · [Evaluation harness](operations/EVALUATION_HARNESS.md) |
| **Results & decisions** | [Pipeline findings](eval/PIPELINE_FINDINGS.md) · [ADR-001 architecture](ADR-001-architecture.md) · [ADR-002 job queue (proposed)](ADR-002-job-queue.md) · [Costs (targets)](COSTS.md) · [SLA (targets)](SLA.md) |
