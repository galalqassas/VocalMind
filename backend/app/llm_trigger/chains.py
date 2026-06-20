from __future__ import annotations

import asyncio
import logging
import random
import threading

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.llm_trigger.prompt_constants import PROCESS_ADHERENCE_FEW_SHOT
from app.llm_trigger.prompts import (
    EMOTION_SHIFT_FEW_SHOT,
    NLI_FEW_SHOT,
    build_emotion_shift_prompt,
    build_nli_policy_prompt,
    build_process_adherence_prompt,
)
from app.llm_trigger.schemas import EmotionShiftAnalysis, NLIEvaluation, ProcessAdherenceReport


logger = logging.getLogger(__name__)

_lock = threading.Lock()
_shared_model: BaseChatModel | None = None

_HEAVY_STAGE = "heavy"
_FAST_STAGE = "fast"
# NOTE: fast_classification is benchmarked and configurable, but currently has
# no production call site wired in backend/service runtime flows.
_STAGE_MODEL_CLASS: dict[str, str] = {
    "emotion_shift": _HEAVY_STAGE,
    "process_adherence": _HEAVY_STAGE,
    "text_to_sql": _HEAVY_STAGE,
    "nli_policy": _FAST_STAGE,
    "rag_judge": _FAST_STAGE,
    "fast_classification": _FAST_STAGE,
    "rag_synthesis": _FAST_STAGE,
}


def build_llm(fast: bool = False, stage: str | None = None) -> BaseChatModel:
    """
    Returns a LangChain chat model.
    Routing is controlled by settings.LLM_PROVIDER:
      'groq'         → ChatGroq (current production)
      'ollama_cloud' → ChatOpenAI pointed at Ollama Cloud OpenAI-compatible endpoint
    The 'fast' flag selects OLLAMA_CLOUD_FAST_MODEL vs per-stage / heavy models.
    """
    if settings.LLM_PROVIDER == "ollama_cloud":
        if not settings.OLLAMA_CLOUD_API_KEY:
            raise ValueError(
                "OLLAMA_CLOUD_API_KEY is not set. "
                "Set it in backend/.env or set LLM_PROVIDER=groq to use Groq."
            )
        if fast:
            model = settings.OLLAMA_CLOUD_FAST_MODEL
            model_label = "OLLAMA_CLOUD_FAST_MODEL"
        elif stage:
            model = get_model_for_stage(stage)
            model_label = f"stage:{stage}"
        else:
            model = settings.OLLAMA_CLOUD_HEAVY_MODEL
            model_label = "OLLAMA_CLOUD_HEAVY_MODEL"
        if not model:
            raise ValueError(
                f"{model_label} is not set. Fill it from benchmark results."
            )
        return ChatOpenAI(
            model=model,
            base_url=settings.OLLAMA_CLOUD_BASE_URL,
            api_key=settings.OLLAMA_CLOUD_API_KEY,
            temperature=0,
            streaming=True,
            max_tokens=settings.LLM_MAX_TOKENS,
            request_timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        )
    from langchain_groq import ChatGroq

    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.LLM_MODEL,
        temperature=settings.LLM_TEMPERATURE,
        max_tokens=settings.LLM_MAX_TOKENS,
        request_timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
    )


def get_model_for_stage(stage: str) -> str:
    """Resolve Ollama Cloud model for a stage with class-based fallback."""
    key = stage.lower().replace("-", "_")
    if key == "nli":
        key = "nli_policy"
    if key not in _STAGE_MODEL_CLASS:
        allowed = ", ".join(sorted(_STAGE_MODEL_CLASS))
        raise ValueError(f"Unknown LLM stage '{stage}'. Allowed stages: {allowed}")

    new_overrides = {
        "emotion_shift": settings.OLLAMA_MODEL_EMOTION_SHIFT,
        "process_adherence": settings.OLLAMA_MODEL_PROCESS_ADHERENCE,
        "nli_policy": settings.OLLAMA_MODEL_NLI_POLICY,
        "rag_judge": settings.OLLAMA_MODEL_RAG_JUDGE,
        "text_to_sql": settings.OLLAMA_MODEL_TEXT_TO_SQL,
        "fast_classification": settings.OLLAMA_MODEL_FAST_CLASSIFICATION,
        "rag_synthesis": settings.OLLAMA_MODEL_RAG_SYNTHESIS,
    }
    legacy_overrides = {
        "emotion_shift": settings.OLLAMA_EMOTION_SHIFT_MODEL,
        "process_adherence": settings.OLLAMA_PROCESS_ADHERENCE_MODEL,
        "nli_policy": settings.OLLAMA_NLI_MODEL,
    }

    stage_override = (new_overrides.get(key) or "").strip()
    if stage_override:
        return stage_override

    legacy_override = (legacy_overrides.get(key) or "").strip()
    if legacy_override:
        return legacy_override

    stage_class = _STAGE_MODEL_CLASS[key]
    if settings.LLM_PROVIDER == "ollama_cloud":
        if stage_class == _FAST_STAGE:
            return settings.OLLAMA_CLOUD_FAST_MODEL
        return settings.OLLAMA_CLOUD_HEAVY_MODEL
    return settings.LLM_MODEL


def recognized_stage_names() -> tuple[str, ...]:
    """Expose recognized stage names for cross-service sync tests."""
    return tuple(sorted(_STAGE_MODEL_CLASS))


def _resolve_chain_model(stage: str, model: BaseChatModel | None) -> BaseChatModel:
    if model is not None:
        return model
    if settings.LLM_PROVIDER == "ollama_cloud":
        return build_llm(fast=False, stage=stage)
    return _get_shared_model()


def _get_shared_model() -> BaseChatModel:
    global _shared_model
    if _shared_model is not None:
        return _shared_model
    with _lock:
        if _shared_model is not None:
            return _shared_model
        _shared_model = build_llm(fast=False)
        return _shared_model


def _with_json_object_mode(model: BaseChatModel) -> BaseChatModel:
    """Bind OpenAI-compatible JSON object mode (Ollama Cloud / ChatOpenAI)."""
    bind = getattr(model, "bind", None)
    if bind is None:
        return model
    return bind(response_format={"type": "json_object"})


async def _invoke_chain_with_retry(chain, inputs: dict, max_retries: int = 3) -> object:
    base_delay = 0.5
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await chain.ainvoke(inputs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            is_rate_limit = "rate" in msg or "429" in msg or "throttl" in msg
            is_transient = is_rate_limit or "timeout" in msg or "connection" in msg or "unavailable" in msg
            if not is_transient or attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt) + random.uniform(0, 0.3)
            logger.warning(
                "LLM chain attempt %d/%d failed (transient), retrying in %.1fs: %s",
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


def build_emotion_shift_chain(model: BaseChatModel | None = None):
    parser = PydanticOutputParser(pydantic_object=EmotionShiftAnalysis)
    prompt = build_emotion_shift_prompt().partial(
        format_instructions=parser.get_format_instructions(),
        few_shot=EMOTION_SHIFT_FEW_SHOT,
    )
    llm = _with_json_object_mode(_resolve_chain_model("emotion_shift", model))
    chain = prompt | llm | parser
    return chain


def build_process_adherence_chain(model: BaseChatModel | None = None):
    parser = PydanticOutputParser(pydantic_object=ProcessAdherenceReport)
    prompt = build_process_adherence_prompt().partial(
        format_instructions=parser.get_format_instructions(),
        few_shot=PROCESS_ADHERENCE_FEW_SHOT,
    )
    llm = _with_json_object_mode(_resolve_chain_model("process_adherence", model))
    chain = prompt | llm | parser
    return chain


def build_nli_policy_chain(model: BaseChatModel | None = None):
    parser = PydanticOutputParser(pydantic_object=NLIEvaluation)
    prompt = build_nli_policy_prompt().partial(
        format_instructions=parser.get_format_instructions(),
        few_shot=NLI_FEW_SHOT,
    )
    llm = _with_json_object_mode(_resolve_chain_model("nli_policy", model))
    chain = prompt | llm | parser
    return chain


async def is_gibberish(text: str) -> bool:
    """
    Returns True if the transcript is gibberish, noise, or contains
    no meaningful spoken content. Uses ministral-3:8b via fast_classification stage.
    Empty text always returns True immediately (no LLM call needed).
    """
    if not text or not text.strip():
        return True

    llm = build_llm(stage="fast_classification")
    prompt = (
        "You are a transcript quality checker. "
        "Respond with exactly one word: VALID or GIBBERISH.\n\n"
        "VALID means: real human speech, even if noisy or imperfect.\n"
        "GIBBERISH means: random characters, pure noise, blank, repeated filler "
        "with no real words, or clearly failed ASR output.\n\n"
        f"Transcript:\n{text[:2000]}\n\nAnswer:"
    )
    try:
        result = await llm.ainvoke(prompt)
        answer = (result.content if hasattr(result, "content") else str(result)).strip().upper()
        return "GIBBERISH" in answer
    except Exception:
        logger.warning("is_gibberish() LLM call failed; treating as VALID")
        return False
