from langchain_core.prompts import ChatPromptTemplate

from app.llm_trigger.prompt_constants import (
    EMOTION_SHIFT_FEW_SHOT,
    EMOTION_SHIFT_SYSTEM_CORE,
    INJECTION_GUARD,
    NLI_FEW_SHOT,
    NLI_POLICY_SYSTEM_CORE,
    PROCESS_ADHERENCE_SYSTEM_CORE,
    TOPIC_CLASSIFICATION_SYSTEM_CORE,
)

__all__ = [
    "EMOTION_SHIFT_FEW_SHOT",
    "NLI_FEW_SHOT",
    "build_emotion_shift_prompt",
    "build_process_adherence_prompt",
    "build_nli_policy_prompt",
    "build_topic_classification_prompt",
]


def build_emotion_shift_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                EMOTION_SHIFT_SYSTEM_CORE + "\n{format_instructions}\n" + INJECTION_GUARD,
            ),
            (
                "human",
                "{few_shot}\n\n"
                "Detected emotion (pipeline): {detected_emotion}\n"
                "Agent context: {agent_context}\n"
                "Customer text: {customer_text}\n"
                "Acoustic emotion: {acoustic_emotion}\n\n"
                "Task:\n"
                "1) Determine if there is emotional dissonance between acoustic and text (set is_dissonance_detected).\n"
                "2) Diagnose the primary issue into dissonance_type: interruption, dismissive_tone, "
                "missing_acknowledgment, or none.\n"
                "3) Explain the transcript-grounded root_cause of the friction.\n"
                "4) Provide an actionable counterfactual_correction starting with 'If the agent had...'.\n"
                "5) Extract exact evidence_quotes from the transcript to support the analysis.\n"
                "6) Return ONLY the JSON object.",
            ),
        ]
    )


def build_process_adherence_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                PROCESS_ADHERENCE_SYSTEM_CORE + "\n{format_instructions}\n" + INJECTION_GUARD,
            ),
            (
                "human",
                "{few_shot}\n\n"
                "Topic hint: {topic_hint}\n\n"
                "Transcript:\n{transcript_text}\n\n"
                "Retrieved SOP:\n{retrieved_sop}\n\n"
                "Expected resolution graph steps:\n{expected_resolution_graph}\n\n"
                "Task:\n"
                "- Set detected_topic to the core issue from the dialogue.\n"
                "- Set is_resolved to true if the customer issue appears solved.\n"
                "- Rate efficiency_score 1-10 based on how well the agent adhered to the SOP steps.\n"
                "- Provide justification for the score.\n"
                "- Set missing_sop_steps to an array of step_key strings (snake_case) from the expected steps that are absent or weak.\n"
                "- Extract exact evidence_quotes from the transcript.\n"
                "- Return ONLY the JSON object.",
            ),
        ]
    )


def build_nli_policy_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            (
                "system",
                NLI_POLICY_SYSTEM_CORE + "\n{format_instructions}\n" + INJECTION_GUARD,
            ),
            (
                "human",
                "{few_shot}\n\n"
                "Ground truth policy:\n{ground_truth_policy}\n\n"
                "Agent statement:\n{agent_statement}\n\n"
                "Task:\n"
                "- Set nli_category to exactly one of the allowed categories.\n"
                "- Provide a short justification for the classification.\n"
                "- Extract exact evidence_quotes from the policy/statement.\n"
                "- Set confidence_score to a float between 0.0 and 1.0 representing your confidence in the classification.\n"
                "- Return ONLY the JSON object.",
            ),
        ]
    )


def build_topic_classification_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", TOPIC_CLASSIFICATION_SYSTEM_CORE + "\n{format_instructions}\n" + INJECTION_GUARD),
            ("human", "Transcript:\n{transcript_text}\n\nReturn ONLY the JSON object."),
        ]
    )
