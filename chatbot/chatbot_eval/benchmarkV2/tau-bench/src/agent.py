"""
agent.py

이커머스 챗봇 에이전트 래퍼 모듈.
프로젝트 내부 LangGraph 챗봇(graph_app)을 직접 호출하여 응답을 생성합니다.
콜백 핸들러를 통해 도구 호출을 실시간 감지합니다.
"""

import sys
import json
import uuid
import asyncio
from pathlib import Path
from typing import Any

from .environment import TaskEnvironment

# ── 프로젝트 루트 탐색 및 경로 설정 ─────────────────────────────────────────
BENCH_DIR = Path(__file__).resolve().parent.parent


def _find_project_root(start: Path, marker: str = ".env") -> Path:
    for parent in [start] + list(start.parents):
        if (parent / marker).exists():
            return parent
    return start.parents[4]


_PROJECT_ROOT = _find_project_root(BENCH_DIR)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage  # noqa: E402
from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from chatbot.src.graph.workflow import graph_app  # noqa: E402
from ecommerce.backend.app.database import SessionLocal  # noqa: E402
from ecommerce.backend.app.router.users.crud import get_user_by_id  # noqa: E402

# ── 벤치마크 environment.py가 인식하는 도구 이름 목록 ─────────────────────
_TRACKED_TOOLS = frozenset({
    "cancel", "refund", "exchange", "shipping",
    "search_by_text_clip", "recommend_clothes",
    "create_review",
    "open_used_sale_form", "register_used_sale",
    "open_address_search", "order_list",
})


class _ToolCallTracker(BaseCallbackHandler):
    """
    LangChain 콜백 핸들러로 도구 호출을 실시간 추적합니다.
    _get_persistable_messages()가 메시지에서 tool_calls를 제거해도
    콜백은 도구 실행 시점에 직접 기록하므로 누락되지 않습니다.
    """

    def __init__(self):
        super().__init__()
        self.tool_calls: list[dict[str, Any]] = []
        self._pending: dict = {}  # run_id → {"name": ..., "args": ...}

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        tool_name = serialized.get("name", "")
        if tool_name not in _TRACKED_TOOLS:
            return
        inputs = kwargs.get("inputs", {})
        if not isinstance(inputs, dict):
            try:
                inputs = json.loads(input_str) if input_str else {}
            except (json.JSONDecodeError, TypeError):
                inputs = {}
        self._pending[run_id] = {"name": tool_name, "args": inputs}

    def on_tool_end(self, output, *, run_id, **kwargs):
        info = self._pending.pop(run_id, None)
        if info:
            self.tool_calls.append(info)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._pending.pop(run_id, None)


def _extract_user_info(env: TaskEnvironment) -> dict[str, Any]:
    """JSONL의 user_id로 DB에서 실제 사용자 정보를 조회해 user_info를 구성합니다."""
    db = SessionLocal()
    try:
        user = get_user_by_id(db, env.user_id)
        if user:
            return {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "site_id": "site_a",
            }
    except Exception:
        pass
    finally:
        db.close()
    # DB 조회 실패 시 env 값으로 폴백
    return {
        "id": env.user_id,
        "name": "평가용 사용자",
        "email": env.user_email,
        "site_id": "site_a",
    }


def _run_async(coro):
    """동기 컨텍스트에서 코루틴을 실행합니다."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class ChatbotAgent:
    """
    이커머스 챗봇 에이전트.
    LangGraph graph_app을 직접 호출하여 사용자 발화에 응답합니다.
    """

    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini", temperature: float = 0.0):
        self.model = model
        self.llm_provider = "openai"
        self.temperature = temperature
        self.conversation_id: str = f"eval_{uuid.uuid4().hex[:12]}"
        self.history: list = []  # LangChain BaseMessage 리스트
        self._is_first_turn: bool = True

    def reset(self) -> None:
        """에이전트 대화 이력과 세션을 초기화합니다."""
        self.history = []
        self.conversation_id = f"eval_{uuid.uuid4().hex[:12]}"
        self._is_first_turn = True

    def respond(self, user_message: str, env: TaskEnvironment) -> str:
        """
        사용자 메시지에 대한 챗봇 응답을 생성합니다.
        graph_app을 통해 처리하고, 콜백 기반으로 tool_calls를 환경에 적용합니다.

        Parameters:
            user_message: 사용자 발화
            env: 현재 태스크 환경

        Returns:
            챗봇의 최종 텍스트 응답
        """
        new_msg = HumanMessage(content=user_message)
        self.history.append(new_msg)

        # 매 턴 공통: 리셋이 필요한 필드만 전달
        state: dict[str, Any] = {
            "messages": [new_msg],  # add_messages reducer가 체크포인트에 누적
            "pending_tasks": [],
            "completed_tasks": [],
            "current_active_task": None,
            "agent_results": {},
            "ui_action_required": None,
            "guardrail_passed": True,
            "user_info": _extract_user_info(env),
            "llm_provider": self.llm_provider,
            "llm_model": self.model,
            "conversation_id": self.conversation_id,
            "turn_id": f"turn_{uuid.uuid4().hex[:12]}",
        }

        # 첫 턴: 멀티턴 컨텍스트 필드 초기화 (체크포인트 없으므로 명시 필요)
        # 이후 턴: 이 필드들을 생략하여 InMemorySaver 체크포인트 값을 유지
        if self._is_first_turn:
            state["order_context"] = {}
            state["search_context"] = {}
            state["conversation_summary"] = None
            self._is_first_turn = False

        # ── 콜백 기반 도구 호출 추적 ──────────────────────────────────
        tracker = _ToolCallTracker()

        try:
            result = _run_async(
                graph_app.ainvoke(
                    state,
                    config={
                        "configurable": {"thread_id": self.conversation_id},
                        "callbacks": [tracker],
                    },
                )
            )
        except Exception as e:
            return f"오류가 발생했습니다: {e}"

        result_messages = result.get("messages", [])

        # ── 도구 호출 감지 (평가 지표용 상태 추적) ──────────────────────

        # 1. 콜백 기반 감지 (메인)
        #    on_tool_start/on_tool_end 이벤트로 도구 호출을 직접 감지합니다.
        #    _get_persistable_messages()가 메시지에서 tool_calls를 제거해도
        #    콜백은 실행 시점에 기록하므로 누락되지 않습니다.
        for tc in tracker.tool_calls:
            tool_name = tc["name"]
            if tool_name not in env.called_tools:
                env.apply_tool_call(tool_name, tc.get("args", {}))

        # 2. order_context.last_tool 백업 감지
        #    order_list 등 @tool 데코레이터 없이 직접 호출되는 도구와
        #    콜백이 누락된 경우를 보완합니다.
        order_context = result.get("order_context", {})
        last_tool = order_context.get("last_tool")
        if last_tool and last_tool not in env.called_tools:
            tool_args = {
                "order_id": order_context.get("target_order_id", ""),
                "user_id": env.user_id,
            }
            env.apply_tool_call(last_tool, tool_args)

        # 3. 메시지 기반 백업 감지: AIMessage.tool_calls / ToolMessage
        #    콜백과 order_context 모두 누락된 경우의 최종 백업입니다.
        for msg in result_messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    try:
                        tool_name = tc["name"]
                        if tool_name in _TRACKED_TOOLS and tool_name not in env.called_tools:
                            env.apply_tool_call(tool_name, tc.get("args", {}))
                    except Exception:
                        pass
            elif isinstance(msg, ToolMessage):
                tool_name = getattr(msg, "name", None)
                if tool_name and tool_name in _TRACKED_TOOLS and tool_name not in env.called_tools:
                    try:
                        env.apply_tool_call(tool_name, {})
                    except Exception:
                        pass

        # 이력 업데이트 (다음 턴을 위해)
        self.history = list(result_messages)

        # 마지막 AIMessage 텍스트 반환
        for msg in reversed(result_messages):
            if isinstance(msg, AIMessage):
                content = getattr(msg, "content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()

        return ""

    def get_trajectory(self) -> list[dict]:
        """현재 대화 이력(trajectory)을 반환합니다."""
        trajectory = []
        for msg in self.history:
            if isinstance(msg, HumanMessage):
                trajectory.append({"role": "user", "content": str(msg.content)})
            elif isinstance(msg, AIMessage):
                trajectory.append({"role": "assistant", "content": str(msg.content or "")})
        return trajectory
