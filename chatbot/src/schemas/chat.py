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
    provider: Literal["openai", "huggingface", "local", "vllm", "ollama"] | None = Field(
        None, description="LLM provider (openai|huggingface|local|vllm|ollama)"
    )
    model: str | None = Field(None, description="Model name or model id")
    access_token: str | None = Field(
        None, description="Bridge token or session token for the shared chat server"
    )
    # 어느 사이트(어댑터)로부터 호출되었는지 식별 (예: "site-a", "site-b", "site-c")
    site_id: str | None = Field(None, description="Adapter site ID (site-a|site-b|site-c)")
    capability_profile: str | None = Field(
        None,
        description="Capability profile for runtime routing (for example order_cs_only|full)",
    )
    enabled_retrieval_corpora: list[str] | None = Field(
        None,
        description="Enabled retrieval corpora for runtime gating (faq|policy|discovery_image)",
    )
    widget_features: Dict[str, Any] | None = Field(
        None,
        description="Explicit widget feature flags such as image_upload",
    )
    model_config = ConfigDict(extra="ignore")

    @field_validator("message")
    @classmethod
    def _validate_message(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class FeedbackRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, description="Conversation identifier")
    feedback_label: Literal["good", "bad"] = Field(
        ...,
        description="Session-level feedback label (good|bad)",
    )
    model_config = ConfigDict(extra="ignore")

    @field_validator("conversation_id")
    @classmethod
    def _validate_conversation_id(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("conversation_id must not be empty")
        return value
