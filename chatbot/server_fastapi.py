from __future__ import annotations

import importlib
import os
import sys
import traceback
import types
from typing import Any, Dict, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
from chatbot.src.adapters.base import AdapterError  # noqa: E402
from chatbot.src.adapters import setup as adapter_setup  # noqa: E402
from chatbot.src.graph.llm_providers import resolve_llm_runtime_policy  # noqa: E402
from chatbot.src.graph.workflow import graph_app  # noqa: E402
from chatbot.src.api.v1.endpoints.chat import build_widget_bundle_response, router as chat_router  # noqa: E402
from chatbot.src.api.v1.endpoints.onboarding_runs import router as onboarding_runs_router  # noqa: E402
from chatbot.src.onboarding.redis_runtime import build_onboarding_event_store, close_onboarding_event_store  # noqa: E402
from chatbot.src.graph.nodes.guardrail import load_guardrail_model  # noqa: E402
from chatbot.src.tools.retrieval_tools import ensure_retrieval_models  # noqa: E402
from chatbot.src.data_preprocessing.bge_m3_embedding import preload_model as preload_bge_m3  # noqa: E402
from chatbot.src.infrastructure.kobart_summarizer import preload_model as preload_kobart  # noqa: E402
from chatbot.src.tools.image_search_tools import preload_clip_resources  # noqa: E402
from ecommerce.backend.app.uploads import CHATBOT_UPLOAD_DIR  # noqa: E402


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = None
    previous_state: Dict[str, Any] | None = None
    provider: Literal["openai", "vllm", "local", "huggingface", "ollama"] | None = None
    model: str | None = None
    site_id: str | None = Field(None, description="Adapter site ID (site-a|site-b|site-c)")
    access_token: str | None = Field(None, description="Bridge token or session token")
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

    runtime_policy = resolve_llm_runtime_policy(
        provider=req.provider or previous_state.get("llm_provider"),
        model=req.model or previous_state.get("llm_model"),
    )
    provider = runtime_policy.provider
    model = runtime_policy.model

    conversation_id = req.conversation_id or previous_state.get("conversation_id") or str(uuid4())
    try:
        resolved_adapter = adapter_setup.resolve_site_adapter(
            req.site_id or previous_state.get("user_info", {}).get("site_id")
        )
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc

    user_info: dict[str, Any] = dict(previous_state.get("user_info") or {})
    user_info["id"] = req.user_id
    user_info["name"] = req.user_name
    if req.user_email is not None:
        user_info["email"] = req.user_email
    user_info["site_id"] = resolved_adapter.site_id
    access_token = req.access_token or previous_state.get("user_info", {}).get("access_token")
    if access_token is not None:
        user_info["access_token"] = access_token

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

app.mount(
    "/chatbot_uploads",
    StaticFiles(directory=str(CHATBOT_UPLOAD_DIR)),
    name="chatbot_uploads",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix=f"{settings.API_V1_STR}/chat")
app.include_router(onboarding_runs_router, prefix=settings.API_V1_STR)


@app.on_event("startup")
async def _startup_onboarding_event_store() -> None:
    app.state.onboarding_event_store = build_onboarding_event_store(
        redis_url=settings.ONBOARDING_REDIS_URL,
    )
    if _env_flag("CHATBOT_SKIP_MODEL_PRELOAD"):
        print("Skipping chatbot model preload because CHATBOT_SKIP_MODEL_PRELOAD is enabled.")
        return
    # 가드레일 모델을 서버 시작 시 1회 로드합니다.
    try:
        load_guardrail_model()
        print("✅ Guardrail 모델 로딩 완료")
    except Exception as e:
        print(f"❌ Guardrail 모델 로딩 실패: {e}")

    try:
        ensure_retrieval_models()
        print("✅ 챗봇 리트리버 모델 로딩 완료")
    except Exception as e:
        print(f"❌ 챗봇 리트리버 모델 로딩 실패: {e}")

    try:
        preload_bge_m3()
        print("✅ BGE-M3 임베딩 모델 로딩 완료")
    except Exception as e:
        print(f"❌ BGE-M3 임베딩 모델 로딩 실패: {e}")

    try:
        preload_kobart()
        print("✅ KoBART 모델 로딩 완료")
    except Exception as e:
        print(f"❌ KoBART 모델 로딩 실패: {e}")

    try:
        preload_clip_resources()
        print("✅ CLIP 검색 모델 로딩 완료")
    except Exception as e:
        print(f"❌ CLIP 검색 모델 로딩 실패: {e}")


@app.on_event("shutdown")
async def _shutdown_onboarding_event_store() -> None:
    close_onboarding_event_store(getattr(app.state, "onboarding_event_store", None))


@app.get("/health")
def healthcheck() -> dict[str, Any]:
    return {
        "ok": True,
        "provider_default": settings.LLM_PROVIDER,
        "openai_model_default": settings.OPENAI_MODEL,
        "vllm_model_default": settings.VLLM_MODEL,
    }


@app.get("/widget.js")
def shared_widget_bundle():
    return build_widget_bundle_response()


@app.post("/api/chat", response_model=ChatResponse)
def chat(http_request: Request, req: ChatRequest) -> ChatResponse:
    try:
        if req.access_token is None:
            req.access_token = (
                http_request.cookies.get("access_token")
                or http_request.cookies.get("session_token")
            )
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
