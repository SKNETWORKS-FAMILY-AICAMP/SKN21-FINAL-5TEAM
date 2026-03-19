from dataclasses import dataclass
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langchain_core.messages import BaseMessage, AIMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_openai import ChatOpenAI
from pydantic import Field, SecretStr, PrivateAttr
from typing import Any, Dict, List, Literal, Optional, Type, Union
from langchain_ollama import ChatOllama

from chatbot.src.core.config import settings


@dataclass(frozen=True)
class LLMCapabilities:
    supports_structured_output: bool
    planner_output_mode: Literal["strict-schema", "strict-label-text"]


@dataclass(frozen=True)
class LLMRuntimePolicy:
    provider: Literal["openai", "vllm", "local", "ollama"]
    model: str
    supports_structured_output: bool
    planner_output_mode: Literal["strict-schema", "strict-label-text"]
    planner_prompt_variant: Literal["strict-schema", "strict-label-text"]


def normalize_provider(provider: str | None) -> Literal["openai", "vllm", "local", "ollama"]:
    normalized = (provider or "").strip().lower()
    if normalized in {"", "openai"}:
        return "openai"
    if normalized == "vllm":
        return "vllm"
    if normalized in {"local", "huggingface"}:
        return "local"
    if normalized == "ollama":
        return "ollama"
    return "openai"


def get_llm_capabilities(provider: str) -> LLMCapabilities:
    normalized = normalize_provider(provider)
    if normalized in {"openai", "vllm"}:
        return LLMCapabilities(
            supports_structured_output=True,
            planner_output_mode="strict-schema",
        )
    if normalized in {"local", "ollama"}:
        return LLMCapabilities(
            supports_structured_output=False,
            planner_output_mode="strict-label-text",
        )
    return LLMCapabilities(
        supports_structured_output=False,
        planner_output_mode="strict-label-text",
    )


def _default_model_for_provider(provider: Literal["openai", "vllm", "local", "ollama"]) -> str:
    if provider == "openai":
        return settings.OPENAI_MODEL
    if provider == "vllm":
        return settings.VLLM_MODEL
    if provider == "local":
        return settings.HF_MODEL_ID
    if provider == "ollama":
        return settings.HF_MODEL_ID
    return settings.OPENAI_MODEL


def resolve_llm_runtime_policy(
    provider: str | None = None,
    model: str | None = None,
) -> LLMRuntimePolicy:
    resolved_provider = normalize_provider(provider or settings.LLM_PROVIDER)
    resolved_model = (model or "").strip() or _default_model_for_provider(resolved_provider)
    capabilities = get_llm_capabilities(resolved_provider)
    return LLMRuntimePolicy(
        provider=resolved_provider,
        model=resolved_model,
        supports_structured_output=capabilities.supports_structured_output,
        planner_output_mode=capabilities.planner_output_mode,
        planner_prompt_variant=capabilities.planner_output_mode,
    )

# ── Local HF LLM Wrapper ───────────────────────────────────

class LocalHFLLM(BaseChatModel):
    """Transformers 기반 로컬 LLM (MPS 지원)."""
    model_id: str
    temperature: float = 0.0
    device: str = Field(default="mps" if torch.backends.mps.is_available() else "cpu")
    
    _pipeline: Any = PrivateAttr(default=None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # GGUF 파일 지정 처리 (예: repo/id:file.gguf)
        if ":" in self.model_id:
            repo_id, gguf_file = self.model_id.split(":", 1)
        else:
            repo_id, gguf_file = self.model_id, None

        msg = f"  [Local LLM] 모델 로드 중: {repo_id}"
        if gguf_file:
            msg += f" (GGUF: {gguf_file})"
        print(f"{msg} (기기: {self.device})")

        tokenizer = AutoTokenizer.from_pretrained(repo_id)
        
        load_kwargs = {
            "torch_dtype": torch.float16 if self.device == "mps" else torch.float32,
            "device_map": self.device,
        }
        
        if gguf_file:
            # transformers 4.41+ GGUF 지원 활용
            model = AutoModelForCausalLM.from_pretrained(
                repo_id,
                gguf_file=gguf_file,
                **load_kwargs
            )
        else:
            model = AutoModelForCausalLM.from_pretrained(
                repo_id,
                **load_kwargs
            )

        self._pipeline = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            max_new_tokens=256,
            temperature=self.temperature if self.temperature > 0 else 0.1,
            do_sample=self.temperature > 0,
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # 간단한 프롬프트 구성 (ChatML 스타일 권장)
        prompt = ""
        for m in messages:
            if m.type == "system":
                prompt += f"<|im_start|>system\n{m.content}<|im_end|>\n"
            elif m.type == "human":
                prompt += f"<|im_start|>user\n{m.content}<|im_end|>\n"
            elif m.type == "ai":
                prompt += f"<|im_start|>assistant\n{m.content}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"

        out = self._pipeline(prompt)
        generated_text = out[0]["generated_text"][len(prompt):].split("<|im_end|>")[0].strip()
        
        message = AIMessage(content=generated_text)
        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "local_hf_llm"

    def with_structured_output(self, schema: Union[dict, Type], **kwargs: Any) -> Any:
        """
        로컬 모델은 복잡한 function calling이 어려우므로, 
        본체 그대로 반환하여 raw text parsing fallback을 유도합니다.
        """
        return self

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
def make_local_llm(model: str, temperature: float = 0) -> LocalHFLLM:
    return LocalHFLLM(model_id=model, temperature=temperature)


# 로컬 모델 재사용을 위한 전역 캐싱
_LLM_CACHE: Dict[str, Any] = {}

def make_chat_llm(
    provider: str = "openai",
    model: str = "gpt-4o",
    temperature: float = 0,
) -> BaseChatModel:
    """Chat LLM 인스턴스를 생성하는 팩토리 함수."""
    
    # 캐시 키 생성
    cache_key = f"{provider}:{model}:{temperature}"
    
    # 로컬 모델의 경우 캐시에서 먼저 확인
    if provider == "local" and cache_key in _LLM_CACHE:
        return _LLM_CACHE[cache_key]

    if provider == "openai":
        llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=SecretStr(settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
        )
    elif provider == "ollama":
        llm = ChatOllama(
            model=model,
            temperature=temperature,
        )
    elif provider == "vllm":
        llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=SecretStr(settings.VLLM_API_KEY or "EMPTY"),
            base_url=settings.VLLM_BASE_URL or "http://localhost:8000/v1",
        )
    elif provider == "local":
        llm = make_local_llm(model=model, temperature=temperature)
        _LLM_CACHE[cache_key] = llm
    else:
        raise ValueError(f"지원하지 않는 LLM 제공자입니다: {provider}")
        
    return llm
