"""Tests for RAG_MODELS_HOST=kaggle — embed/parse/rerank go to the Kaggle server."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("GROQ_API_KEY", "test_key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

import config
from ingest import DocumentIngestionPipeline
from llm_circuit_breaker import reset_breakers
from query_engine import RAGQueryEngine
from reranker import rerank_points


@pytest.fixture()
def kaggle(monkeypatch):
    monkeypatch.setattr(config.settings, "RAG_MODELS_HOST", "kaggle")
    monkeypatch.setattr(config.settings, "KAGGLE_SERVER_URL", "https://kaggle.example/")
    calls = []

    def _post(url, json=None, files=None, headers=None, timeout=None):
        calls.append(SimpleNamespace(url=url, json=json, files=files, headers=headers))
        if url.endswith("/embed"):
            body = {"embeddings": [[float(i)] * 3 for i, _ in enumerate(json["texts"])]}
        elif url.endswith("/rerank"):
            body = {"scores": [float(len(d)) for d in json["documents"]]}
        else:
            body = {"markdown": "# Parsed"}
        return MagicMock(json=MagicMock(return_value=body), raise_for_status=MagicMock())

    with patch("httpx.post", side_effect=_post):
        yield calls


def test_kaggle_post_requires_url(monkeypatch):
    monkeypatch.setattr(config.settings, "KAGGLE_SERVER_URL", "")
    with pytest.raises(ValueError, match="KAGGLE_SERVER_URL"):
        config.kaggle_post("/embed", json={"texts": ["x"]})


def test_ingest_embedding_uses_kaggle(kaggle):
    with patch.object(DocumentIngestionPipeline, "__init__", lambda self: None):
        pipeline = DocumentIngestionPipeline()
    assert pipeline._get_embedding("hello") == [0.0, 0.0, 0.0]
    assert kaggle[0].url == "https://kaggle.example/embed"
    assert kaggle[0].json == {"texts": ["hello"]}
    assert kaggle[0].headers == {"ngrok-skip-browser-warning": "true"}


def test_upload_chunks_batches_kaggle_embeddings(kaggle):
    with patch.object(DocumentIngestionPipeline, "__init__", lambda self: None):
        pipeline = DocumentIngestionPipeline()
    pipeline.qdrant = MagicMock()
    chunks = [SimpleNamespace(page_content=f"chunk {i}", metadata={"org": "acme"}) for i in range(40)]

    assert pipeline._upload_chunks(chunks, "col", "test") == 40
    assert [len(c.json["texts"]) for c in kaggle] == [32, 8]
    points = pipeline.qdrant.upsert.call_args.kwargs["points"]
    assert points[33].payload == {"text": "chunk 33", "org": "acme"}
    assert points[33].vector == [1.0, 1.0, 1.0]


def test_parse_pdf_posts_to_kaggle(kaggle, tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert DocumentIngestionPipeline._parse_pdf(str(pdf)) == "# Parsed"
    assert kaggle[0].url == "https://kaggle.example/parse"
    assert kaggle[0].files["file"][0] == "doc.pdf"


def test_rerank_uses_kaggle_scores(kaggle, monkeypatch):
    monkeypatch.setattr(config.settings, "RERANK_ENABLED", True)
    points = [SimpleNamespace(payload={"text": t}, score=0.5) for t in ("a", "ccc", "bb")]
    ranked = rerank_points("q", points, top_k=2)
    assert [p.payload["text"] for p in ranked] == ["ccc", "bb"]
    assert kaggle[0].json == {"query": "q", "documents": ["a", "ccc", "bb"]}


def test_query_embedding_uses_kaggle(kaggle):
    reset_breakers()
    with patch.object(RAGQueryEngine, "__init__", lambda self: None):
        engine = RAGQueryEngine()
    assert engine._embed_query("question") == [0.0, 0.0, 0.0]
    assert kaggle[0].url == "https://kaggle.example/embed"


def test_query_embedding_kaggle_failure_has_no_fallback(monkeypatch):
    reset_breakers()
    monkeypatch.setattr(config.settings, "RAG_MODELS_HOST", "kaggle")
    monkeypatch.setattr(config.settings, "KAGGLE_SERVER_URL", "https://kaggle.example")
    with patch.object(RAGQueryEngine, "__init__", lambda self: None):
        engine = RAGQueryEngine()
    with patch("httpx.post", side_effect=RuntimeError("down")) as post, pytest.raises(
        ConnectionError, match="Kaggle /embed failed"
    ):
        engine._embed_query("question")
    assert post.call_count == 1
