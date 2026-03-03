"""LLM Provider 팩토리 및 Hugging Face 로컬 모델 지원.

Provider별 ChatModel 생성, HF 모델 로딩/캐싱/추론 로직을
nodes_v2.py에서 분리하여 단일 책임으로 관리합니다.
"""

import threading
from typing import Any, Dict, List, Optional

import torch
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from transformers import AutoModelForCausalLM, AutoTokenizer

from ecommerce.chatbot.src.core.config import settings

# ── Constants ──────────────────────────────────────────────

DEFAULT_PROVIDER = "openai"
SUPPORTED_PROVIDERS = {"openai", "huggingface", "vllm"}

MAX_HISTORY_TOKENS = 3000
KEEP_RECENT_TURNS = 3
SUMMARY_MODEL = "gpt-5-mini"

# ── HF model cache ────────────────────────────────────────

_HF_MODEL_CACHE: Dict[str, Dict[str, Any]] = {}
_HF_MODEL_LOCK = threading.Lock()


# ── Provider/Model resolution ─────────────────────────────


def resolve_provider(provider: Optional[str]) -> str:
    normalized = (provider or "").strip().lower()
    if normalized in SUPPORTED_PROVIDERS:
        return normalized
    fallback = (settings.LLM_PROVIDER or DEFAULT_PROVIDER).strip().lower()
    return fallback if fallback in SUPPORTED_PROVIDERS else DEFAULT_PROVIDER


def resolve_llm_config(
    state: Optional[Dict[str, Any]], preferred_model: Optional[str] = None
) -> tuple[str, str]:
    provider_from_state = state.get("llm_provider") if isinstance(state, dict) else None
    provider = resolve_provider(provider_from_state)

    model_from_state = state.get("llm_model") if isinstance(state, dict) else None
    model = (preferred_model or model_from_state or "").strip()
    if model:
        return provider, model

    if provider == "huggingface":
        return provider, settings.HF_MODEL_ID
    if provider == "vllm":
        return provider, settings.VLLM_MODEL
    return provider, settings.OPENAI_MODEL


# ── LLM factory ───────────────────────────────────────────


def make_openai_llm(model: str, temperature: float = 0) -> ChatOpenAI:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required when provider is 'openai'.")
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=SecretStr(settings.OPENAI_API_KEY),
    )


def make_vllm_llm(model: str, temperature: float = 0) -> ChatOpenAI:
    base_url = (settings.VLLM_BASE_URL or "").strip()
    if not base_url:
        raise ValueError("VLLM_BASE_URL is required when provider is 'vllm'.")
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=SecretStr(settings.VLLM_API_KEY or "EMPTY"),
        base_url=base_url,
    )


def make_chat_llm(provider: str, model: str, temperature: float = 0) -> ChatOpenAI:
    if provider == "openai":
        return make_openai_llm(model=model, temperature=temperature)
    if provider == "vllm":
        return make_vllm_llm(model=model, temperature=temperature)
    raise ValueError(f"Unsupported chat llm provider for ChatOpenAI path: {provider}")


# ── Hugging Face local model ──────────────────────────────


def _load_hf_model(model_id: str) -> Dict[str, Any]:
    with _HF_MODEL_LOCK:
        cached = _HF_MODEL_CACHE.get(model_id)
        if cached:
            return cached

        quant_mode = (
            (getattr(settings, "HF_QUANTIZATION", "auto") or "auto").strip().lower()
        )

        if torch.cuda.is_available():
            device = "cuda"
            dtype = torch.float16
        elif torch.backends.mps.is_available():
            device = "mps"
            dtype = torch.float16
        else:
            device = "cpu"
            dtype = torch.float32

        tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)

        model_obj: Any = None
        quant_applied = "none"

        if device == "cuda" and quant_mode in {"auto", "bnb-4bit", "bnb-8bit"}:
            try:
                from transformers import BitsAndBytesConfig

                if quant_mode in {"auto", "bnb-4bit"}:
                    bnb_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_quant_type="nf4",
                    )
                    quant_applied = "bnb-4bit"
                else:
                    bnb_config = BitsAndBytesConfig(load_in_8bit=True)
                    quant_applied = "bnb-8bit"

                model_obj = AutoModelForCausalLM.from_pretrained(
                    model_id,
                    trust_remote_code=True,
                    quantization_config=bnb_config,
                    device_map="auto",
                )
            except Exception as e:
                print(
                    f"[LLM] bitsandbytes quantization disabled ({e}); fallback to {dtype}."
                )
                model_obj = None

        if device != "cuda" and quant_mode != "none":
            print(
                f"[LLM] Quantization request '{quant_mode}' ignored on {device}. "
                "Priority policy: CUDA > MPS > CPU (no CPU quantization)."
            )

        if model_obj is None:
            model_obj = AutoModelForCausalLM.from_pretrained(
                model_id,
                dtype=dtype,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            quant_applied = "none"

        if quant_applied not in {"bnb-4bit", "bnb-8bit"}:
            model_obj = model_obj.to(device)

        model_obj.eval()

        loaded = {
            "tokenizer": tokenizer,
            "model": model_obj,
            "device": device,
            "quantization": quant_applied,
        }
        _HF_MODEL_CACHE[model_id] = loaded
        print(
            f"[LLM] Loaded Hugging Face model locally: {model_id} on {device} (quant={quant_applied})"
        )
        return loaded


def hf_invoke(messages: List, model_id: str, temperature: float = 0) -> AIMessage:
    loaded = _load_hf_model(model_id)
    tokenizer = loaded["tokenizer"]
    model = loaded["model"]
    device = loaded["device"]

    chat_messages: List[Dict[str, str]] = []
    for msg in messages:
        content = getattr(msg, "content", "")
        if not isinstance(content, str):
            continue
        if isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, HumanMessage):
            role = "user"
        else:
            role = "assistant"
        chat_messages.append({"role": role, "content": content})

    if hasattr(tokenizer, "apply_chat_template"):
        prompt = tokenizer.apply_chat_template(
            chat_messages, tokenize=False, add_generation_prompt=True
        )
    else:
        prompt = (
            "\n".join(f"{m['role']}: {m['content']}" for m in chat_messages)
            + "\nassistant:"
        )

    inputs = tokenizer(prompt, return_tensors="pt")
    input_ids = inputs["input_ids"].to(device)
    attention_mask = inputs.get("attention_mask")
    if attention_mask is not None:
        attention_mask = attention_mask.to(device)

    do_sample = temperature > 0
    generation_kwargs = {
        "input_ids": input_ids,
        "max_new_tokens": 512,
        "do_sample": do_sample,
    }
    if attention_mask is not None:
        generation_kwargs["attention_mask"] = attention_mask
    if do_sample:
        generation_kwargs["temperature"] = max(0.1, temperature)
        generation_kwargs["top_p"] = 0.9

    with torch.no_grad():
        output_ids = model.generate(**generation_kwargs)

    generated = output_ids[0][input_ids.shape[-1] :]
    content = tokenizer.decode(generated, skip_special_tokens=True).strip()
    return AIMessage(content=content)


# ── Context compaction helpers ─────────────────────────────


def estimate_tokens(messages: List) -> int:
    """메시지 토큰 수 대략 추정 (1토큰 ≈ 4자)"""
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    return total_chars // 4


def group_messages_into_turns(messages: List) -> List[List]:
    """메시지를 user+assistant 기준 턴으로 그룹화"""
    turns: List[List] = []
    current_turn: List = []

    for msg in messages:
        if isinstance(msg, HumanMessage):
            if current_turn:
                turns.append(current_turn)
            current_turn = [msg]
        else:
            if not current_turn:
                current_turn = [msg]
            else:
                current_turn.append(msg)

    if current_turn:
        turns.append(current_turn)

    return turns


def clear_old_turns(messages: List, keep_recent_turns: int) -> List:
    """최근 N턴 제외 메시지를 [cleared]로 치환"""
    from langchain_core.messages import ToolMessage

    turns = group_messages_into_turns(messages)
    if len(turns) <= keep_recent_turns:
        return messages

    old_turns = turns[:-keep_recent_turns]
    recent_turns = turns[-keep_recent_turns:]

    cleared_messages: List = []
    for turn in old_turns:
        for msg in turn:
            if isinstance(msg, HumanMessage):
                cleared_messages.append(HumanMessage(content="[cleared]"))
            elif isinstance(msg, AIMessage):
                cleared_messages.append(AIMessage(content="[cleared]"))
            elif isinstance(msg, ToolMessage):
                cleared_messages.append(
                    ToolMessage(content="[cleared]", tool_call_id=msg.tool_call_id)
                )

    recent_messages = [msg for turn in recent_turns for msg in turn]
    return cleared_messages + recent_messages


def summarize_messages(messages: List, provider: str, model_name: str) -> str | None:
    """전체 대화를 다음 턴용으로 요약"""
    from ecommerce.chatbot.src.prompts.agent_prompts import (
        get_context_summary_system_prompt,
    )

    if not messages:
        return None

    transcript = "\n".join(
        f"{type(m).__name__}: {str(getattr(m, 'content', ''))[:300]}" for m in messages
    )
    context_summary_system_prompt = get_context_summary_system_prompt(
        provider=provider, model_name=model_name
    )

    try:
        if provider in {"openai", "vllm"}:
            summary_llm = make_chat_llm(
                provider=provider, model=model_name or SUMMARY_MODEL, temperature=0
            )
            response = summary_llm.with_config({"run_name": "summary_llm"}).invoke(
                [
                    SystemMessage(content=context_summary_system_prompt),
                    HumanMessage(content=transcript[:12000]),
                ]
            )
            return response.content if isinstance(response.content, str) else None

        response = hf_invoke(
            [
                SystemMessage(content=context_summary_system_prompt),
                HumanMessage(content=transcript[:12000]),
            ],
            model_name,
            temperature=0,
        )
        return response.content if isinstance(response.content, str) else None
    except Exception as e:
        print(f"[Compaction] Summary failed: {e}")
        return None


def compress_messages_for_context(
    messages: List, provider: str, model_name: str
) -> List:
    """토큰 초과 시: 전체 요약 + 최근 3턴 제외 cleared"""
    token_count = estimate_tokens(messages)
    if token_count <= MAX_HISTORY_TOKENS:
        return messages

    print(f"[Compaction] token={token_count} > {MAX_HISTORY_TOKENS}, compacting...")
    summary = summarize_messages(messages, provider, model_name)
    cleared = clear_old_turns(messages, KEEP_RECENT_TURNS)

    if summary:
        return [HumanMessage(content=f"[conversation_summary]\n{summary}")] + cleared
    return cleared
