from __future__ import annotations

import importlib
import os
import sys
import traceback
import types
from typing import Any, Dict, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, messages_from_dict, messages_to_dict
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _bootstrap_legacy_import_alias() -> None:
    """
    레거시 경로(`chatbot.src...`)를 현재 경로(`chatbot.src...`)로 매핑.
    기존 노드/툴 파일의 import를 변경하지 않고 서버 실행 가능하게 한다.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    chatbot_src = importlib.import_module("chatbot.src")

    # ecommerce 네임스페이스 보장
    try:
        ecommerce_pkg = importlib.import_module("ecommerce")
    except ModuleNotFoundError:
        ecommerce_pkg = types.ModuleType("ecommerce")
        ecommerce_pkg.__path__ = [os.path.join(repo_root, "ecommerce")]
        sys.modules["ecommerce"] = ecommerce_pkg

    # chatbot 네임스페이스 보장
    chatbot_ns = sys.modules.get("chatbot")
    if chatbot_ns is None:
        chatbot_ns = types.ModuleType("chatbot")
        chatbot_ns.__path__ = [os.path.join(repo_root, "chatbot")]
        sys.modules["chatbot"] = chatbot_ns

    setattr(ecommerce_pkg, "chatbot", chatbot_ns)
    setattr(chatbot_ns, "src", chatbot_src)
    sys.modules["chatbot.src"] = chatbot_src


_bootstrap_legacy_import_alias()

from chatbot.src.core.config import settings  # noqa: E402
from chatbot.src.graph.workflow import graph_app  # noqa: E402


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = None
    previous_state: Dict[str, Any] | None = None
    provider: Literal["openai", "vllm"] | None = None
    model: str | None = None
    user_id: int = 1
    user_name: str = "테스트 사용자"
    user_email: str | None = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("message")
    @classmethod
    def _validate_message(cls, v: str) -> str:
        value = v.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str
    completed_tasks: list[str]
    ui_action_required: str | None
    awaiting_interrupt: bool
    interrupts: list[dict[str, Any]]
    state: dict[str, Any]


def _deserialize_messages(serialized: Any) -> list[BaseMessage]:
    if not isinstance(serialized, list):
        return []

    # LangChain 표준 직렬화 포맷
    try:
        if serialized and isinstance(serialized[0], dict) and {"type", "data"}.issubset(serialized[0]):
            return messages_from_dict(serialized)
    except Exception:
        pass

    # legacy 포맷 하위 호환
    messages: list[BaseMessage] = []
    for item in serialized:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", ""))
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages


def _serialize_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    return messages_to_dict(messages)


def _extract_interrupts(final_state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = final_state.get("__interrupt__")
    if raw is None:
        return []

    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]

    payloads: list[dict[str, Any]] = []
    for item in raw:
        value = getattr(item, "value", None)
        if value is None and isinstance(item, dict):
            value = item.get("value")

        if isinstance(value, dict):
            payloads.append(value)
        elif value is not None:
            payloads.append({"message": str(value)})

    return payloads


def _last_ai_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def _build_graph_input(req: ChatRequest) -> tuple[dict[str, Any], str]:
    previous_state = req.previous_state or {}
    previous_messages = _deserialize_messages(previous_state.get("messages", []))

    provider = (req.provider or previous_state.get("llm_provider") or settings.LLM_PROVIDER or "openai").lower()
    if provider not in {"openai", "vllm"}:
        raise HTTPException(status_code=400, detail="provider는 openai 또는 vllm만 지원합니다.")

    if req.model:
        model = req.model
    else:
        if provider == "openai":
            model = previous_state.get("llm_model") or settings.OPENAI_MODEL
        else:
            model = previous_state.get("llm_model") or settings.VLLM_MODEL

    conversation_id = req.conversation_id or previous_state.get("conversation_id") or str(uuid4())

    user_info: dict[str, Any] = dict(previous_state.get("user_info") or {})
    user_info["id"] = req.user_id
    user_info["name"] = req.user_name
    if req.user_email is not None:
        user_info["email"] = req.user_email

    state: dict[str, Any] = {
        "messages": [*previous_messages, HumanMessage(content=req.message)],
        "pending_tasks": [],
        "completed_tasks": [],
        "current_active_task": None,
        "order_context": dict(previous_state.get("order_context") or {}),
        "search_context": dict(previous_state.get("search_context") or {}),
        "ui_action_required": None,
        "user_info": user_info,
        "llm_provider": provider,
        "llm_model": model,
        "agent_results": {},
        "guardrail_passed": True,
        "conversation_id": conversation_id,
        "turn_id": str(uuid4()),
        "conversation_summary": previous_state.get("conversation_summary"),
    }

    return state, conversation_id


def _build_persistent_state(final_state: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    persistent = {
        "messages": _serialize_messages(final_state.get("messages", [])),
        "order_context": final_state.get("order_context", {}),
        "search_context": final_state.get("search_context", {}),
        "user_info": final_state.get("user_info", {}),
        "llm_provider": final_state.get("llm_provider", "openai"),
        "llm_model": final_state.get("llm_model", ""),
        "conversation_summary": final_state.get("conversation_summary"),
        "conversation_id": conversation_id,
    }
    return persistent


app = FastAPI(
    title="Chatbot Standalone API",
    version="1.0.0",
    description="SaaS Adapter/Tool 연동 테스트를 위한 챗봇 단독 서버",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict[str, Any]:
    return {
        "ok": True,
        "provider_default": settings.LLM_PROVIDER,
        "openai_model_default": settings.OPENAI_MODEL,
        "vllm_model_default": settings.VLLM_MODEL,
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        state, conversation_id = _build_graph_input(req)

        final_state = graph_app.invoke(
            state,
            config={"configurable": {"thread_id": conversation_id}},
        )

        messages = final_state.get("messages", [])
        answer = _last_ai_text(messages) or "요청을 처리했지만 응답 메시지를 생성하지 못했습니다."

        interrupts = _extract_interrupts(final_state)
        completed_tasks = list(final_state.get("completed_tasks", []))
        ui_action_required = final_state.get("ui_action_required")

        return ChatResponse(
            answer=answer,
            conversation_id=conversation_id,
            completed_tasks=completed_tasks,
            ui_action_required=ui_action_required,
            awaiting_interrupt=bool(interrupts),
            interrupts=interrupts,
            state=_build_persistent_state(final_state, conversation_id),
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"chat 처리 중 오류: {e}") from e
