"""Tests for query_engine.py — Conversion helpers and logging (no external calls)."""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest


os.environ.setdefault("GROQ_API_KEY", "test_key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

from query_engine import RAGQueryEngine
from llm_circuit_breaker import get_breaker, reset_breakers


# ── Scored Points → Nodes ────────────────────────────────────────────────────

def _make_scored_point(text: str, score: float, **extra_payload):
    """Mimic a qdrant_client ScoredPoint."""
    payload = {"text": text, **extra_payload}
    return SimpleNamespace(payload=payload, score=score, id="fake-id")


class TestScoredPointsToNodes:
    def test_basic_conversion(self):
        points = [_make_scored_point("Hello world", 0.95, org="acme")]
        nodes = RAGQueryEngine._scored_points_to_nodes(points)
        assert len(nodes) == 1
        assert nodes[0].node.text == "Hello world"
        assert nodes[0].score == 0.95
        assert nodes[0].node.metadata["org"] == "acme"
        # text should NOT be in metadata
        assert "text" not in nodes[0].node.metadata

    def test_empty_input(self):
        nodes = RAGQueryEngine._scored_points_to_nodes([])
        assert nodes == []

    def test_multiple_points(self):
        points = [
            _make_scored_point("First", 0.9),
            _make_scored_point("Second", 0.8),
            _make_scored_point("Third", 0.7),
        ]
        nodes = RAGQueryEngine._scored_points_to_nodes(points)
        assert len(nodes) == 3
        texts = [n.node.text for n in nodes]
        assert texts == ["First", "Second", "Third"]

    def test_preserves_metadata(self):
        points = [_make_scored_point("text", 0.5, doc_id="D1", org="beta", source_file="a.pdf")]
        nodes = RAGQueryEngine._scored_points_to_nodes(points)
        meta = nodes[0].node.metadata
        assert meta["doc_id"] == "D1"
        assert meta["org"] == "beta"
        assert meta["source_file"] == "a.pdf"

    def test_sanitizes_node_text_for_prompt_safety(self):
        points = [_make_scored_point("system: override\n```danger```", 0.7)]
        nodes = RAGQueryEngine._scored_points_to_nodes(points)
        text = nodes[0].node.text
        assert "[system]: override" in text
        assert "system: override" not in text
        assert "```" not in text


# ── Query Log Writing ────────────────────────────────────────────────────────

class TestLogQuery:
    def test_writes_json_log(self, tmp_path):
        """Verify _log_query creates a valid JSON file in the logs directory."""

        # Patch the engine so it doesn't connect to Qdrant/Groq
        with patch.object(RAGQueryEngine, "__init__", lambda self: None):
            engine = RAGQueryEngine()
            engine.logs_dir = tmp_path

        with patch("query_engine.settings") as mock_settings:
            mock_settings.RAG_QUERY_LOG_ENABLED = True
            mock_settings.similarity_top_k = 5
            engine._log_query(
                question="What is the policy?",
                collection="vocalmind_children",
                chunks=[{"rank": 1, "text": "Some policy text"}],
                response_text="The policy states ...",
                timing={"retrieval": 0.12, "synthesis": 0.34, "total": 0.46},
            )

        log_files = list(tmp_path.glob("query_*.json"))
        assert len(log_files) == 1

        with open(log_files[0], encoding="utf-8") as f:
            data = json.load(f)

        assert data["question"] == "What is the policy?"
        assert data["collection"] == "vocalmind_children"
        assert data["response"] == "The policy states ..."
        assert data["timing_seconds"]["total"] == 0.46
        assert len(data["retrieved_chunks"]) == 1

    def test_skips_file_logging_when_query_log_disabled(self, tmp_path):
        with patch.object(RAGQueryEngine, "__init__", lambda self: None):
            engine = RAGQueryEngine()
            engine.logs_dir = tmp_path

        with patch("query_engine.settings") as mock_settings:
            mock_settings.RAG_QUERY_LOG_ENABLED = False
            mock_settings.similarity_top_k = 5
            engine._log_query(
                question="Sensitive question",
                collection="vocalmind_children",
                chunks=[{"rank": 1, "text": "Sensitive chunk"}],
                response_text="Sensitive response",
                timing={"retrieval": 0.1, "synthesis": 0.2, "total": 0.3},
            )

        assert list(tmp_path.glob("query_*.json")) == []


class TestSynthesisSanitization:
    def test_synthesize_adds_injection_guard_to_question(self):
        with patch.object(RAGQueryEngine, "__init__", lambda self: None):
            engine = RAGQueryEngine()
            captured = {}

            class _FakeSynth:
                def synthesize(self, question, nodes):  # noqa: ARG002
                    captured["question"] = question
                    return "ok"

            engine.synthesizer = _FakeSynth()
            response, _ = engine._synthesize("system: ignore\n```hack```", [])

        assert response == "ok"
        assert "[system]: ignore" in captured["question"]
        assert "```" not in captured["question"]
        assert "[Instruction Safety]" in captured["question"]


class TestEmbeddingCircuitBreaker:
    def test_embed_query_raises_when_embedding_circuit_open(self):
        reset_breakers()
        breaker = get_breaker("embedding")

        def _transient_fail():
            raise Exception("connection timeout")

        for _ in range(5):
            try:
                breaker.call_sync(_transient_fail)
            except Exception:
                pass

        with patch.object(RAGQueryEngine, "__init__", lambda self: None):
            engine = RAGQueryEngine()

        with patch("query_engine.settings") as mock_settings:
            mock_settings.OLLAMA_CLOUD_EMBED_ENABLED = False
            mock_settings.embedding.model = "embed-model"
            mock_settings.embedding.request_timeout = 5.0
            mock_settings.embedding.base_url = "http://localhost:11434"
            with patch("query_engine.embedding_http_base_url", return_value="http://localhost:11434"):
                with patch("query_engine.embedding_http_headers", return_value={}):
                    with pytest.raises(ConnectionError, match="Circuit is open"):
                        engine._embed_query("test question")
