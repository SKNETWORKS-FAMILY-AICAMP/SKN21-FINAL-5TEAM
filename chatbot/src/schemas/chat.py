from typing import Any, Dict, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewDraftRequest(BaseModel):
    product_name: str = Field(..., min_length=1, description="Product name")
    satisfaction: Literal["좋음", "보통", "아쉬움"] = Field(
        ..., description="Satisfaction level (좋음|보통|아쉬움)"
    )
    keywords: list[str] = Field(
        default_factory=list, description="Keywords to include"
    )

    @field_validator("product_name")
    @classmethod
    def _validate_product_name(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("product_name must not be empty")
        return value

    @field_validator("keywords")
    @classmethod
    def _normalize_keywords(cls, v: list[str]) -> list[str]:
        return [kw.strip() for kw in v if isinstance(kw, str) and kw.strip()]


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User's query")
    # 이전 대화 상태 (메시지 이력 포함)
    previous_state: Dict[str, Any] | None = Field(
        None, description="Full conversation state for stateless processing"
    )
    resume_payload: Dict[str, Any] | None = Field(
        None, description="Structured payload used to resume an interrupted graph step"
    )
    provider: Literal["openai", "huggingface", "vllm"] | None = Field(
        None, description="LLM provider (openai|huggingface|vllm)"
    )
    model: str | None = Field(None, description="Model name or model id")
    model_config = ConfigDict(extra="ignore")

    @field_validator("message")
    @classmethod
    def _validate_message(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value
