"""LLM Provider 팩토리.

현재 그래프 노드에서 실제로 사용하는 ChatOpenAI 경로(openai / vllm)만 유지합니다.
"""

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ecommerce.chatbot.src.core.config import settings

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
