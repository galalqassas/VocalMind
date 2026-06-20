"""Unit tests for the RAGAS evaluation module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    from ragas_eval import (
        RagasReport,
        _OllamaEmbeddings,
        run_reference_free_eval,
        generate_synthetic_testset,
        run_full_eval,
    )
except ImportError:
    # Handle pytest running from root vs services/rag
    import sys
    sys.path.append(str(Path(__file__).parent.parent))
    from ragas_eval import (
        RagasReport,
        _OllamaEmbeddings,
        run_reference_free_eval,
        generate_synthetic_testset,
        run_full_eval,
    )


class MockResult:
    """Stand-in for a RAGAS EvaluationResult; only ``to_pandas`` is exercised."""

    def __init__(self) -> None:
        self.to_pandas = MagicMock()


@pytest.fixture
def mock_engine():
    with patch("ragas_eval.RAGQueryEngine") as mock:
        engine_instance = MagicMock()
        engine_instance.query_compliance.return_value = {
            "chunks": [{"text": "policy chunk 1"}],
            "response": "policy response",
        }
        engine_instance.query_answer.return_value = {
            "chunks": [{"text": "qa chunk 1"}],
            "response": "qa response",
        }
        engine_instance.query.return_value = {
            "chunks": [{"text": "full chunk 1"}],
            "response": "full response",
        }
        mock.return_value = engine_instance
        yield engine_instance


@pytest.fixture
def mock_ragas_evaluate():
    # ``evaluate`` is imported lazily inside the eval functions, so patch it
    # at its source module rather than on ragas_eval.
    with patch("ragas.evaluate") as mock:
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([
            (0, {"user_input": "q1", "faithfulness": 0.9, "answer_relevancy": 0.8, "context_precision": 0.7})
        ])
        mock_df.__contains__.side_effect = lambda x: True
        mock_df.__getitem__.return_value.mean.return_value = 0.8
        
        result = MockResult()
        result.to_pandas.return_value = mock_df
        mock.return_value = result
        yield mock


@pytest.fixture
def mock_testset_generator():
    with patch("ragas.testset.TestsetGenerator") as mock:
        gen_instance = MagicMock()
        mock_testset = MagicMock()
        
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([
            (0, {"user_input": "q1", "reference": "ref1", "context": ["ctx1"]})
        ])
        mock_df.columns = ["user_input", "reference", "context"]
        mock_testset.to_pandas.return_value = mock_df
        
        gen_instance.generate_with_langchain_docs.return_value = mock_testset
        mock.return_value = gen_instance
        yield gen_instance


@pytest.fixture
def mock_build_llm():
    with patch("ragas_eval._build_ragas_llm") as mock:
        mock.return_value = MagicMock()
        yield mock


@pytest.fixture
def mock_build_embeddings():
    with patch("ragas_eval._build_ragas_embeddings") as mock:
        mock.return_value = MagicMock()
        yield mock


def test_ragas_report_serialization():
    """Test that RagasReport serializes correctly."""
    report = RagasReport(
        mode="test",
        total_samples=2,
        metrics={"faithfulness": 0.95},
        per_sample=[{"user_input": "q1"}],
        duration_seconds=1.5
    )
    data = json.loads(report.model_dump_json())
    assert data["mode"] == "test"
    assert data["total_samples"] == 2
    assert data["metrics"]["faithfulness"] == 0.95


@patch("ragas_eval._save_report")
def test_run_reference_free_eval(
    mock_save,
    mock_engine,
    mock_ragas_evaluate,
    mock_build_llm,
    mock_build_embeddings,
):
    """Test reference-free evaluation mode."""
    with patch("ragas_eval._POLICY_COMPLIANCE_QUERIES", ["query 1"]), \
         patch("ragas_eval._QA_QUERIES", ["query 2"]):
        
        report = run_reference_free_eval(org_filter="test-org")
        
        assert report.mode == "reference-free"
        assert report.org_filter == "test-org"
        assert mock_engine.query_compliance.called
        assert mock_engine.query_answer.called
        assert mock_ragas_evaluate.called
        assert mock_save.called


@patch("langchain_community.document_loaders.DirectoryLoader")
def test_generate_synthetic_testset(
    mock_loader_cls,
    mock_testset_generator,
    mock_build_llm,
    mock_build_embeddings,
    tmp_path,
):
    """Test synthetic testset generation."""
    # Setup mock documents
    mock_doc = MagicMock()
    mock_doc.metadata = {"source": "doc1.md"}
    mock_loader = MagicMock()
    mock_loader.load.return_value = [mock_doc]
    mock_loader_cls.return_value = mock_loader

    # Setup mock directory structure
    settings_mock = MagicMock()
    settings_mock.DOCS_DIR = tmp_path
    settings_mock.BASE_DIR = tmp_path
    
    org_dir = tmp_path / "test-org"
    org_dir.mkdir()
    parsed_dir = org_dir / "parsed-docs"
    parsed_dir.mkdir()
    
    output_path = tmp_path / "testset.json"

    with patch("ragas_eval.settings", settings_mock):
        result_path = generate_synthetic_testset(
            org_filter="test-org",
            testset_size=1,
            output_path=output_path
        )

        assert result_path == output_path
        assert result_path.exists()
        
        with open(result_path) as f:
            data = json.load(f)
            assert data["org"] == "test-org"
            assert len(data["samples"]) == 1
            assert data["samples"][0]["user_input"] == "q1"


@patch("ragas_eval._save_report")
@patch("ragas_eval._check_thresholds")
def test_run_full_eval(
    mock_check,
    mock_save,
    mock_engine,
    mock_ragas_evaluate,
    mock_build_llm,
    mock_build_embeddings,
    tmp_path,
):
    """Test full evaluation mode with ground truth."""
    # Create mock testset
    testset_path = tmp_path / "testset.json"
    with open(testset_path, "w") as f:
        json.dump({
            "samples": [
                {"user_input": "q1", "reference": "ref1"}
            ]
        }, f)

    with patch("ragas_eval.settings") as settings_mock:
        settings_mock.BASE_DIR = tmp_path
        
        report = run_full_eval(
            org_filter="test-org",
            testset_path=testset_path
        )
        
        assert report.mode == "full"
        assert report.total_samples == 1
        assert mock_engine.query.called
        assert mock_ragas_evaluate.called
        assert mock_save.called
        assert mock_check.called


@patch("ragas_eval.httpx.post")
def test_ollama_embeddings_success(mock_post):
    """Test _OllamaEmbeddings success path."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    mock_post.return_value = mock_response

    embeddings = _OllamaEmbeddings()
    vector = embeddings.embed_query("test query")
    
    assert vector == [0.1, 0.2, 0.3]
    assert mock_post.called


@patch("ragas_eval.httpx.post")
def test_ollama_embeddings_failure(mock_post):
    """Test _OllamaEmbeddings failure path."""
    mock_post.side_effect = Exception("Connection error")

    embeddings = _OllamaEmbeddings()
    with pytest.raises(ConnectionError, match="Cannot reach Ollama embeddings"):
        embeddings.embed_query("test query")
