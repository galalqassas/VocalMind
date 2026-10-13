"""Smoke test that LangChain prompt templates build without f-string errors."""
from app.llm_trigger.prompts import (
    build_emotion_shift_prompt,
    build_nli_policy_prompt,
    build_process_adherence_prompt,
    build_topic_classification_prompt,
)


def test_prompt_templates_build():
    for builder in (build_emotion_shift_prompt, build_process_adherence_prompt, build_nli_policy_prompt, build_topic_classification_prompt):
        tmpl = builder()
        assert tmpl.input_variables
