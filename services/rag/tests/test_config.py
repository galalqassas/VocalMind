"""Tests for config.py — Settings defaults and sub-config validation."""

import os
from pathlib import Path

import pytest

# Ensure test env vars are set before importing config
os.environ.setdefault("GROQ_API_KEY", "test_key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

from config import (
    ChildChunkingConfig,
    EmbeddingConfig,
    GroqConfig,
    ParentChunkingConfig,
    QdrantConfig,
    Settings,
    recognized_stage_names,
    resolve_model_for_stage,
)


class TestGroqConfig:
    def test_default_model(self):
        cfg = GroqConfig(GROQ_API_KEY="test")
        assert cfg.model == "llama-3.3-70b-versatile"

    def test_default_temperature(self):
        cfg = GroqConfig(GROQ_API_KEY="test")
        assert cfg.temperature == 0.1

    def test_api_key_is_secret(self):
        cfg = GroqConfig(GROQ_API_KEY="my_secret")
        assert cfg.api_key.get_secret_value() == "my_secret"
        # Should not leak in string representation
        assert "my_secret" not in str(cfg.api_key)


class TestEmbeddingConfig:
    def test_defaults(self):
        cfg = EmbeddingConfig()
        assert cfg.model == "snowflake-arctic-embed2"
        assert cfg.dimension == 1024
        assert cfg.base_url
        assert cfg.base_url.startswith("http://")
        assert cfg.request_timeout == 120.0


class TestQdrantConfig:
    def test_defaults(self):
        cfg = QdrantConfig()
        assert cfg.url
        assert cfg.url.startswith("http://")
        assert cfg.collection_parents == "vocalmind_parents"
        assert cfg.collection_children == "vocalmind_children"


class TestParentChunkingConfig:
    def test_headers(self):
        cfg = ParentChunkingConfig()
        assert len(cfg.headers_to_split_on) == 3
        markers = [h[0] for h in cfg.headers_to_split_on]
        assert markers == ["#", "##", "###"]

    def test_empty_section_min_words(self):
        cfg = ParentChunkingConfig()
        assert cfg.empty_section_min_words == 4


class TestChildChunkingConfig:
    def test_defaults(self):
        cfg = ChildChunkingConfig()
        assert cfg.chunk_size == 400
        assert cfg.chunk_overlap == 80
        assert cfg.min_chunk_length == 30


class TestSettings:
    def test_base_dir_is_path(self):
        s = Settings()
        assert isinstance(s.BASE_DIR, Path)

    def test_response_mode(self):
        s = Settings()
        assert s.response_mode in ("compact", "refine", "tree_summarize")

    def test_similarity_top_k(self):
        s = Settings()
        # Reranker scans a wider pool (RERANK_CANDIDATE_K) and returns the top 3,
        # which keeps unused tail chunks out of the synthesis context.
        assert s.similarity_top_k == 3

    def test_validate_config_raises_on_missing_docs_dir(self, tmp_path):
        s = Settings()
        s.DOCS_DIR = tmp_path / "nonexistent"
        with pytest.raises(ValueError, match="does not exist"):
            s.validate_config()

    def test_validate_config_passes_with_existing_dir(self, tmp_path):
        s = Settings()
        s.DOCS_DIR = tmp_path
        s.validate_config()  # Should not raise


def test_resolve_model_for_stage_prefers_new_override(monkeypatch):
    monkeypatch.setattr("config.settings.OLLAMA_MODEL_RAG_JUDGE", "ministral-3:8b")
    monkeypatch.setattr("config.settings.OLLAMA_CLOUD_FAST_MODEL", "fast-default")
    assert resolve_model_for_stage("rag_judge") == "ministral-3:8b"


def test_resolve_model_for_stage_uses_legacy_override(monkeypatch):
    monkeypatch.setattr("config.settings.OLLAMA_MODEL_NLI_POLICY", "")
    monkeypatch.setattr("config.settings.OLLAMA_NLI_MODEL", "legacy-nli")
    monkeypatch.setattr("config.settings.OLLAMA_CLOUD_FAST_MODEL", "fast-default")
    assert resolve_model_for_stage("nli_policy") == "legacy-nli"


def test_resolve_model_for_stage_class_fallbacks(monkeypatch):
    monkeypatch.setattr("config.settings.LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setattr("config.settings.OLLAMA_CLOUD_FAST_MODEL", "fast-default")
    monkeypatch.setattr("config.settings.OLLAMA_CLOUD_HEAVY_MODEL", "heavy-default")
    monkeypatch.setattr("config.settings.OLLAMA_MODEL_RAG_SYNTHESIS", "")
    monkeypatch.setattr("config.settings.OLLAMA_MODEL_TEXT_TO_SQL", "")
    assert resolve_model_for_stage("text_to_sql") == "heavy-default"


def test_resolve_model_for_stage_rag_synthesis_preserves_legacy_default(monkeypatch):
    monkeypatch.setattr("config.settings.LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setattr("config.settings.OLLAMA_MODEL_RAG_SYNTHESIS", "")
    monkeypatch.setattr("config.settings.groq.model", "llama-3.3-70b-versatile")
    monkeypatch.setattr("config.settings.OLLAMA_CLOUD_FAST_MODEL", "fast-default")
    monkeypatch.setattr("config.settings.OLLAMA_CLOUD_HEAVY_MODEL", "heavy-default")
    assert resolve_model_for_stage("rag_synthesis") == "llama-3.3-70b-versatile"


def test_resolve_model_for_stage_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown LLM stage"):
        resolve_model_for_stage("unknown_stage")


def test_recognized_stage_names_match_contract():
    assert recognized_stage_names() == (
        "emotion_shift",
        "fast_classification",
        "nli_policy",
        "process_adherence",
        "rag_judge",
        "rag_synthesis",
        "text_to_sql",
    )
