from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.llm_trigger.retrieval import RetrievedChunk
from app.llm_trigger.prompt_constants import RESOLUTION_GRAPHS, UNKNOWN_TOPIC
from app.llm_trigger.schemas import (
    EmotionShiftAnalysis,
    NLIEvaluation,
    ProcessAdherenceReport,
    TopicClassification,
)
from app.llm_trigger.service import (
    LLMUnavailableError,
    _build_policy_reference_from_chunk,
    _build_emotion_transition_attributions,
    _build_rolling_windows,
    _detect_topic_from_sop_chunks,
    _derive_llm_inputs,
    _quote_anchored_in_policy,
    _render_window_bundle,
    analyze_emotion_shift,
    classify_topic,
    evaluate_process_adherence,
    run_single_claim_nli_policy_check,
)
from app.llm_trigger.chains import get_model_for_stage, recognized_stage_names


class _FakeProcessChain:
    async def ainvoke(self, payload):
        return ProcessAdherenceReport(
            detected_topic=payload.get("topic_hint", "refund_request"),
            is_resolved=True,
            efficiency_score=8,
            justification="Agent completed key verification steps but skipped the refund confirmation closeout.",
            missing_sop_steps=["confirm_refund_method_and_timeline"],
            evidence_quotes=["I checked your order and policy window."],
            confidence_score=0.95,
        )


class _FakeTopicChain:
    def __init__(self, topic):
        self.topic = topic
        self.calls = 0

    async def ainvoke(self, _payload):
        self.calls += 1
        return TopicClassification(topic=self.topic)


class _FailingProcessChain:
    async def ainvoke(self, _payload):
        raise Exception("Error code: 429 - rate_limit_exceeded")


@pytest.mark.asyncio
async def test_analyze_emotion_shift_skips_llm_when_no_conversation():
    # Friction analysis needs a real, speaker-labelled conversation. With no
    # conversation supplied the detector must short-circuit (insufficient
    # evidence) rather than invoking the LLM.
    with patch("app.llm_trigger.service.build_emotion_shift_chain") as mock_builder:
        result = await analyze_emotion_shift(
            agent_context="Agent context",
            customer_text="Thank you for your help, that was great.",
            acoustic_emotion="happy",
            conversation_text="",
        )

    assert isinstance(result, EmotionShiftAnalysis)
    assert result.is_dissonance_detected is False
    assert result.dissonance_type == "None"
    assert result.insufficient_evidence is True
    mock_builder.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_emotion_shift_runs_llm_for_agent_friction_on_calm_customer():
    # Regression guard for the dead-empathy bug: agent friction must be analyzed
    # even when the customer's acoustic emotion is calm/positive — the old gate
    # only ran the LLM on cross-modal/negative-acoustic customers, pinning
    # empathy at a constant.
    class _FakeEmotionChain:
        async def ainvoke(self, _payload):
            return EmotionShiftAnalysis(
                is_dissonance_detected=True,
                dissonance_type="dismissive_tone",
                root_cause="Agent used blaming language toward the customer.",
                counterfactual_correction="If the agent had apologized instead of blaming, tone would improve.",
                evidence_quotes=["If you had listened the first time we would not be here."],
                confidence_score=0.9,
            )

    conversation = (
        "agent: If you had listened the first time we would not be here.\n"
        "customer: I am just trying to understand my bill.\n"
        "agent: I already explained this, there is nothing more to do."
    )
    with patch("app.llm_trigger.service.build_emotion_shift_chain", return_value=_FakeEmotionChain()) as mock_builder:
        result = await analyze_emotion_shift(
            agent_context="Agent context",
            customer_text="I am just trying to understand my bill.",
            acoustic_emotion="neutral",
            conversation_text=conversation,
        )

    mock_builder.assert_called_once()
    assert result.is_dissonance_detected is True
    assert result.dissonance_type == "dismissive_tone"


@pytest.mark.asyncio
async def test_analyze_emotion_shift_downgrades_ungrounded_friction():
    # The model claims interruption but its only evidence is a CUSTOMER line that
    # never appears in an agent turn -> must be downgraded to "none" so a
    # well-handled call keeps full empathy.
    class _FakeEmotionChain:
        async def ainvoke(self, _payload):
            return EmotionShiftAnalysis(
                is_dissonance_detected=True,
                dissonance_type="interruption",
                root_cause="Claimed interruption.",
                counterfactual_correction="If the agent had paused, things improve.",
                evidence_quotes=["I am really upset about this whole situation"],
                confidence_score=0.9,
            )

    conversation = (
        "agent: Thank you for calling, I can certainly help you with that today.\n"
        "customer: I am really upset about this whole situation.\n"
        "agent: I understand, let me pull up your account and sort this out."
    )
    with patch("app.llm_trigger.service.build_emotion_shift_chain", return_value=_FakeEmotionChain()):
        result = await analyze_emotion_shift(
            agent_context="Agent context",
            customer_text="I am really upset about this whole situation.",
            acoustic_emotion="frustrated",
            conversation_text=conversation,
        )

    assert result.dissonance_type == "none"
    assert result.is_dissonance_detected is False


def test_quote_anchored_in_policy_matches_verbatim_and_overlap():
    policy = "Refunds are allowed only within 30 days of purchase. Agents must verify identity first."
    assert _quote_anchored_in_policy("Refunds are allowed only within 30 days", policy) is True
    assert _quote_anchored_in_policy("Agents must verify the customer identity first", policy) is True
    assert _quote_anchored_in_policy("Managers approve all wire transfers above the cap", policy) is False


@pytest.mark.asyncio
async def test_nli_contradiction_downgraded_when_not_policy_anchored():
    # Model claims Contradiction but its policy quote is NOT in the policy text.
    class _FakeNLIChain:
        async def ainvoke(self, _payload):
            return NLIEvaluation(
                nli_category="Contradiction",
                severity="major",
                justification="Alleged violation.",
                evidence_quotes=["Managers must approve any credit over five thousand dollars"],
                confidence_score=0.9,
                policy_alignment_score=0.1,
            )

    with patch("app.llm_trigger.service.build_nli_policy_chain", return_value=_FakeNLIChain()):
        result = await run_single_claim_nli_policy_check(
            agent_statement="I issued a $50 goodwill credit to your account.",
            ground_truth_policy="Frontline agents may apply goodwill credits up to $200 without approval.",
        )
    assert result.nli_category == "Benign Deviation"
    assert result.severity == "none"


@pytest.mark.asyncio
async def test_nli_contradiction_kept_when_policy_anchored():
    class _FakeNLIChain:
        async def ainvoke(self, _payload):
            return NLIEvaluation(
                nli_category="Contradiction",
                severity="critical",
                justification="Insufficient verification.",
                evidence_quotes=["Agents must complete 3-of-5 identity verification before any financial adjustment"],
                confidence_score=0.9,
                policy_alignment_score=0.1,
            )

    with patch("app.llm_trigger.service.build_nli_policy_chain", return_value=_FakeNLIChain()):
        result = await run_single_claim_nli_policy_check(
            agent_statement="I verified your account number and PIN, then adjusted the charge.",
            ground_truth_policy="Agents must complete 3-of-5 identity verification before any financial adjustment.",
        )
    assert result.nli_category == "Contradiction"
    assert result.severity == "critical"




def test_topic_classification_normalizes_to_catalog_or_unknown():
    assert TopicClassification(topic="Fraud-Dispute").topic == "fraud_dispute"
    assert TopicClassification(topic="weather chat").topic == UNKNOWN_TOPIC


def test_resolution_graphs_single_source_has_all_topics():
    from app.llm_trigger import service
    from app.llm_trigger.prompt_constants import PROCESS_ADHERENCE_SYSTEM_CORE, TOPIC_CLASSIFICATION_SYSTEM_CORE

    assert service.RESOLUTION_GRAPHS is RESOLUTION_GRAPHS
    assert len(RESOLUTION_GRAPHS) == 11
    for topic in ("account_signers", "aml_review", "retention", "wire_transfer"):
        assert f"Topic `{topic}`" in PROCESS_ADHERENCE_SYSTEM_CORE
        assert f"Topic `{topic}`" in TOPIC_CLASSIFICATION_SYSTEM_CORE


@pytest.mark.asyncio
async def test_classify_topic_uses_topic_chain():
    chain = _FakeTopicChain("wire_transfer")
    with patch("app.llm_trigger.service.build_topic_classification_chain", return_value=chain):
        assert await classify_topic("customer: I need to send a wire.") == "wire_transfer"
    assert chain.calls == 1


def test_detect_topic_from_sop_chunk_reference_prefers_matched_document():
    chunks = [
        RetrievedChunk(
            text="[01-refund-request-processing.pdf]\nStep 1 - Open the Call & Verify Identity",
            metadata={"source_file": "01-refund-request-processing.pdf"},
            source="manual",
        )
    ]

    topic = _detect_topic_from_sop_chunks(chunks)
    assert topic == "refund_request"


def test_policy_reference_preserves_doc_type_and_policy_ref_metadata():
    chunk = RetrievedChunk(
        text="Step 4: Confirm refund timeline.",
        metadata={
            "doc_type": "sop",
            "policy_ref": ["CS-RULE-003"],
            "source_file": "refund-sop.md",
        },
        source="qdrant",
        collection="vocalmind_sop_parents",
    )

    reference = _build_policy_reference_from_chunk(
        chunk,
        source_kind="sop",
        fallback_text="",
        fallback_reference="Retrieved SOP",
    )

    assert reference is not None
    assert reference.doc_type == "sop"
    assert reference.policy_ref == ["CS-RULE-003"]


@pytest.mark.asyncio
async def test_evaluate_process_adherence_uses_llm_steps_and_given_topic():
    transcript = (
        "customer: I need a refund.\n"
        "agent: I can help with that.\n"
        "agent: I checked your order and policy window."
    )

    with (
        patch("app.llm_trigger.service.build_process_adherence_chain", return_value=_FakeProcessChain()),
        patch("app.llm_trigger.service.build_topic_classification_chain") as topic_builder,
    ):
        result = await evaluate_process_adherence(
            transcript_text=transcript,
            retrieved_sop_from_pinecone="",
            org_filter=None,
            retrieved_sop_chunks=[],
            topic="refund_request",
        )

    topic_builder.assert_not_called()
    assert result.detected_topic == "refund_request"
    assert result.is_resolved is True
    assert result.efficiency_score == 8
    assert result.missing_sop_steps == ["Confirm refund method and timeline"]
    assert result.evidence_quotes == ["I checked your order and policy window."]
    assert result.citations


@pytest.mark.asyncio
async def test_evaluate_process_adherence_uses_sop_file_hint_when_classifier_abstains():
    chunks = [
        RetrievedChunk(
            text="[01-refund-request-processing.pdf]\nStep 1 - Open the Call & Verify Identity\nStep 7 - Apply Credit & Communicate Timeline",
            metadata={"source_file": "01-refund-request-processing.pdf"},
            source="manual",
        )
    ]

    with (
        patch("app.llm_trigger.service.build_process_adherence_chain", return_value=_FakeProcessChain()),
        patch("app.llm_trigger.service.build_topic_classification_chain", return_value=_FakeTopicChain(UNKNOWN_TOPIC)),
    ):
        result = await evaluate_process_adherence(
            transcript_text="customer: I want a refund please.\nagent: I can issue the refund right away.",
            retrieved_sop_from_pinecone="",
            org_filter="nexalink",
            retrieved_sop_chunks=chunks,
        )

    assert result.detected_topic == "refund_request"


@pytest.mark.asyncio
async def test_evaluate_process_adherence_classifier_topic_wins_over_file_hint():
    chunks = [
        RetrievedChunk(
            text="[01-refund-request-processing.pdf]\nStep 1 - Open the Call & Verify Identity",
            metadata={"source_file": "01-refund-request-processing.pdf"},
            source="manual",
        )
    ]

    with (
        patch("app.llm_trigger.service.build_process_adherence_chain", return_value=_FakeProcessChain()),
        patch("app.llm_trigger.service.build_topic_classification_chain", return_value=_FakeTopicChain("billing_issue")),
    ):
        result = await evaluate_process_adherence(
            transcript_text="customer: My bill has a double charge.\nagent: Let me check the billing error.",
            retrieved_sop_from_pinecone="",
            org_filter="nexalink",
            retrieved_sop_chunks=chunks,
        )

    assert result.detected_topic == "billing_issue"


def test_build_emotion_transition_attributions_tracks_each_speaker_change():
    utterances = [
        SimpleNamespace(
            sequence_index=0,
            speaker_role=SimpleNamespace(value="customer"),
            text="I am very upset about this.",
            emotion="frustrated",
            emotion_confidence=0.82,
            start_time_seconds=0.0,
            end_time_seconds=2.0,
        ),
        SimpleNamespace(
            sequence_index=1,
            speaker_role=SimpleNamespace(value="customer"),
            text="Thank you, that helps a lot.",
            emotion="happy",
            emotion_confidence=0.88,
            start_time_seconds=18.0,
            end_time_seconds=21.0,
        ),
        SimpleNamespace(
            sequence_index=2,
            speaker_role=SimpleNamespace(value="agent"),
            text="Let me explain the next step.",
            emotion="frustrated",
            emotion_confidence=0.75,
            start_time_seconds=22.0,
            end_time_seconds=24.0,
        ),
        SimpleNamespace(
            sequence_index=3,
            speaker_role=SimpleNamespace(value="agent"),
            text="Great, we have fully resolved it.",
            emotion="happy",
            emotion_confidence=0.85,
            start_time_seconds=30.0,
            end_time_seconds=33.0,
        ),
    ]

    attributions = _build_emotion_transition_attributions(utterances)

    assert len(attributions) == 2
    assert attributions[0].family == "emotion"
    assert attributions[0].trigger_type == "Emotion Polarity Shift"
    assert "customer" in attributions[0].title.lower()
    assert "agent" in attributions[1].title.lower()


@pytest.mark.asyncio
async def test_process_adherence_llm_failure_raises():
    with (
        patch("app.llm_trigger.service.build_process_adherence_chain", return_value=_FailingProcessChain()),
        pytest.raises(LLMUnavailableError, match="process_adherence"),
    ):
        await evaluate_process_adherence(
            transcript_text="customer: I need a refund.\nagent: I can help and check your eligibility now.",
            retrieved_sop_from_pinecone="",
            retrieved_sop_chunks=[],
            topic="refund_request",
        )


@pytest.mark.asyncio
async def test_emotion_and_nli_llm_failures_raise():
    conversation = "agent: Hello, how can I help you today?\ncustomer: My card was charged twice this month."
    with (
        patch("app.llm_trigger.service.build_emotion_shift_chain", return_value=_FailingProcessChain()),
        pytest.raises(LLMUnavailableError),
    ):
        await analyze_emotion_shift("ctx", "My card was charged twice.", "angry", conversation_text=conversation)

    with (
        patch("app.llm_trigger.service.build_nli_policy_chain", return_value=_FailingProcessChain()),
        pytest.raises(LLMUnavailableError),
    ):
        await run_single_claim_nli_policy_check("I refunded you.", "Refunds within 30 days.")


@pytest.mark.asyncio
async def test_topic_classification_failure_raises():
    with (
        patch("app.llm_trigger.service.build_topic_classification_chain", return_value=_FailingProcessChain()),
        pytest.raises(LLMUnavailableError, match="topic_classification"),
    ):
        await classify_topic("customer: hello")


@patch("app.llm_trigger.service.fuse_emotion_signals", return_value=SimpleNamespace(emotion="frustrated"))
def test_derive_llm_inputs_uses_full_call_customer_and_agent_turns(_mock_fuse):
    utterances = [
        SimpleNamespace(speaker_role=SimpleNamespace(value="customer"), text="I called yesterday.", emotion="neutral", emotion_confidence=0.3),
        SimpleNamespace(speaker_role=SimpleNamespace(value="agent"), text="I can help with that.", emotion=None, emotion_confidence=None),
        SimpleNamespace(speaker_role=SimpleNamespace(value="customer"), text="I am still frustrated because this is unresolved.", emotion="frustrated", emotion_confidence=0.82),
        SimpleNamespace(speaker_role=SimpleNamespace(value="agent"), text="I will process the refund right now.", emotion=None, emotion_confidence=None),
    ]

    agent_context, customer_text, acoustic_emotion, fused_emotion, agent_statement = _derive_llm_inputs(
        utterances=utterances,
        transcript_text="fallback transcript",
        agent_name="Sara",
    )

    assert "I called yesterday." in customer_text
    assert "still frustrated" in customer_text
    assert "I can help with that." in agent_statement
    assert "process the refund" in agent_statement
    assert acoustic_emotion == "frustrated"
    assert fused_emotion
    assert "full-call behavior" in agent_context


@patch("app.llm_trigger.service.fuse_emotion_signals", return_value=SimpleNamespace(emotion="frustrated"))
def test_derive_llm_inputs_uses_dominant_customer_emotion_not_last_turn_only(_mock_fuse):
    utterances = [
        SimpleNamespace(speaker_role=SimpleNamespace(value="customer"), text="This issue is still unresolved and very frustrating.", emotion="frustrated", emotion_confidence=0.94),
        SimpleNamespace(speaker_role=SimpleNamespace(value="customer"), text="I keep waiting and this is unacceptable.", emotion="angry", emotion_confidence=0.86),
        SimpleNamespace(speaker_role=SimpleNamespace(value="agent"), text="I understand your concern and will check now.", emotion=None, emotion_confidence=None),
        SimpleNamespace(speaker_role=SimpleNamespace(value="customer"), text="Thanks for checking that.", emotion="happy", emotion_confidence=0.31),
    ]

    _agent_context, _customer_text, acoustic_emotion, _fused_emotion, _agent_statement = _derive_llm_inputs(
        utterances=utterances,
        transcript_text="fallback transcript",
        agent_name="Sara",
    )

    assert acoustic_emotion in {"frustrated", "angry"}


def test_build_rolling_windows_and_bundle_for_long_transcript():
    utterances = [
        SimpleNamespace(
            speaker_role=SimpleNamespace(value="customer" if idx % 2 == 0 else "agent"),
            text=f"turn {idx} text",
            start_time_seconds=float(idx * 5),
            end_time_seconds=float((idx * 5) + 4),
        )
        for idx in range(10)
    ]

    windows = _build_rolling_windows(utterances, window_turns=4, stride=2)

    assert len(windows) == 4
    assert windows[0].start_index == 0
    assert windows[1].start_index == 2

    bundle = _render_window_bundle(windows)
    assert "[W0]" in bundle
    assert "turns 0-3" in bundle


def test_get_model_for_stage_uses_stage_override_first(monkeypatch):
    monkeypatch.setattr("app.llm_trigger.chains.settings.LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_MODEL_EMOTION_SHIFT", "kimi-k2.5:cloud")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_CLOUD_HEAVY_MODEL", "heavy-fallback")
    assert get_model_for_stage("emotion_shift") == "kimi-k2.5:cloud"


def test_get_model_for_stage_ignores_ollama_overrides_on_groq(monkeypatch):
    monkeypatch.setattr("app.llm_trigger.chains.settings.LLM_PROVIDER", "groq")
    monkeypatch.setattr("app.llm_trigger.chains.settings.LLM_MODEL", "groq-model")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_MODEL_EMOTION_SHIFT", "kimi-k2.5:cloud")
    assert get_model_for_stage("emotion_shift") == "groq-model"


def test_legacy_stage_model_env_names_fill_new_fields(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("OLLAMA_MODEL_NLI_POLICY", raising=False)
    monkeypatch.setenv("OLLAMA_NLI_MODEL", "legacy-nli")
    assert Settings(_env_file=None).OLLAMA_MODEL_NLI_POLICY == "legacy-nli"


def test_get_model_for_stage_uses_fast_and_heavy_fallback_classes(monkeypatch):
    monkeypatch.setattr("app.llm_trigger.chains.settings.LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_CLOUD_FAST_MODEL", "fast-fallback")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_CLOUD_HEAVY_MODEL", "heavy-fallback")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_MODEL_RAG_JUDGE", "")
    monkeypatch.setattr("app.llm_trigger.chains.settings.OLLAMA_MODEL_TEXT_TO_SQL", "")
    assert get_model_for_stage("rag_judge") == "fast-fallback"
    assert get_model_for_stage("text_to_sql") == "heavy-fallback"


def test_get_model_for_stage_rejects_unknown_stage():
    with pytest.raises(ValueError, match="Unknown LLM stage"):
        get_model_for_stage("nonexistent_stage")


def test_recognized_stage_names_includes_declared_stages():
    assert recognized_stage_names() == (
        "emotion_shift",
        "fast_classification",
        "nli_policy",
        "process_adherence",
        "rag_judge",
        "rag_synthesis",
        "text_to_sql",
    )


def test_stage_name_contract_matches_rag_implementation():
    from rag.config import recognized_stage_names as rag_recognized_stage_names

    assert recognized_stage_names() == rag_recognized_stage_names()
