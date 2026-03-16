"""
model_caller.py

프로젝트 내부 LangGraph 챗봇(graph_app)을 직접 호출하여 응답을 반환합니다.
"""

import sys
import json
import uuid
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

# ── 프로젝트 루트 탐색 및 경로 설정 ─────────────────────────────────────────
_BENCH_ROOT = Path(__file__).resolve().parent.parent


def _find_project_root(start: Path, marker: str = ".env") -> Path:
    for parent in [start] + list(start.parents):
        if (parent / marker).exists():
            return parent
    return start.parents[4]


_PROJECT_ROOT = _find_project_root(_BENCH_ROOT)
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

from langchain_core.messages import HumanMessage, AIMessage  # noqa: E402
from chatbot.src.graph.workflow import graph_app  # noqa: E402

# ── 평가용 기본 사용자 정보 (prompt_variables로 덮어씀) ──────────────────────
_DEFAULT_EVAL_USER: Dict[str, Any] = {
    "id": 1,
    "name": "평가용 사용자",
    "email": "test@example.com",
    "site_id": "site_a",
}


def _build_user_info(prompt_variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """prompt_variables에서 user_id, user_email을 추출해 user_info를 구성합니다."""
    if not prompt_variables:
        return dict(_DEFAULT_EVAL_USER)
    user_id = prompt_variables.get("user_id", _DEFAULT_EVAL_USER["id"])
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        user_id = _DEFAULT_EVAL_USER["id"]
    email = prompt_variables.get("user_email", _DEFAULT_EVAL_USER["email"])
    return {**_DEFAULT_EVAL_USER, "id": user_id, "email": email}


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


class ModelCaller:
    """LangGraph graph_app을 통해 챗봇 모델을 호출합니다."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        temperature: float = 0.0,
        base_url: Optional[str] = None,
        system_prompt_path: Optional[str] = None,
        prompt_variables: Optional[Dict[str, str]] = None,
    ):
        self.model = model
        self.temperature = temperature
        # api_key, base_url, system_prompt_path, prompt_variables는 하위 호환을 위해 받지만 미사용

    def call(self, query: List[Dict], tools: List[Dict], prompt_variables: Optional[Dict[str, str]] = None) -> Dict:
        """
        graph_app을 호출하고 응답을 데이터셋 ground_truth 포맷으로 반환합니다.

        반환 포맷:
          - 텍스트 응답: {"role": "assistant", "content": "..."}
          - 툴 호출:     {"role": "assistant", "content": None,
                          "tool_calls": [{"name": "...", "arguments": "..."}]}
        """
        # query를 LangChain 메시지로 변환 (system 메시지는 건너뜀)
        messages: List = []
        for msg in query:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                # tool_calls가 있는 assistant 메시지는 AIMessage에 tool_calls 추가
                tool_calls_raw = msg.get("tool_calls")
                if tool_calls_raw:
                    # LangChain AIMessage.tool_calls 형식으로 변환
                    lc_tool_calls = []
                    for tc in tool_calls_raw:
                        name = tc.get("name", "")
                        args_raw = tc.get("arguments", "{}")
                        try:
                            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                        except Exception:
                            args = {}
                        lc_tool_calls.append({
                            "name": name,
                            "args": args,
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "type": "tool_call",
                        })
                    messages.append(AIMessage(content=content, tool_calls=lc_tool_calls))
                else:
                    messages.append(AIMessage(content=content))

        if not messages:
            return {"role": "assistant", "content": None}

        conv_id = f"eval_{uuid.uuid4().hex[:12]}"
        state = {
            "messages": messages,
            "pending_tasks": [],
            "completed_tasks": [],
            "current_active_task": None,
            "order_context": {},
            "search_context": {},
            "ui_action_required": None,
            "agent_results": {},
            "guardrail_passed": True,
            "user_info": _build_user_info(prompt_variables),
            "llm_provider": "openai",
            "llm_model": self.model,
            "conversation_id": conv_id,
            "turn_id": f"turn_{uuid.uuid4().hex[:12]}",
            "conversation_summary": None,
        }

        try:
            result = _run_async(
                graph_app.ainvoke(
                    state,
                    config={"configurable": {"thread_id": conv_id}},
                )
            )
        except Exception as e:
            logging.error(f"graph_app 호출 실패: {e}")
            raise

        result_messages = result.get("messages", [])

        # tool_calls가 있는 첫 번째 AIMessage를 반환 (call 턴 평가용)
        for msg in result_messages:
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                tool_calls = [
                    {
                        "name": tc["name"],
                        "arguments": json.dumps(tc.get("args", {}), ensure_ascii=False),
                    }
                    for tc in msg.tool_calls
                ]
                return {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": tool_calls,
                }

        # tool_calls 없음 — 마지막 AIMessage 텍스트 반환 (completion 턴)
        for msg in reversed(result_messages):
            if isinstance(msg, AIMessage):
                return {"role": "assistant", "content": msg.content}

        return {"role": "assistant", "content": None}
