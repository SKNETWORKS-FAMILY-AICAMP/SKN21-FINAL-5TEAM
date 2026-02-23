import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Dict, List, Literal
from uuid import uuid4

from langchain_core.messages import ToolMessage, AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langsmith import traceable
from pydantic import BaseModel, Field, SecretStr

from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.prompts.system_prompts import ECOMMERCE_SYSTEM_PROMPT
from ecommerce.chatbot.src.prompts.agent_prompts import (
    TOOL_USAGE_INSTRUCTIONS,
    CONTEXT_SUMMARY_SYSTEM_PROMPT,
    APPROVAL_CHECK_PROMPT_TEMPLATE,
)

# Import Tools
from ecommerce.chatbot.src.tools.order_tools import (
    get_order_details,
    get_shipping_details,
    get_user_orders,
    update_payment_method,
    change_product_option,
    cancel_order,
    check_refund_eligibility,
    check_exchange_eligibility,
    register_return_request,
    register_exchange_request
)
from ecommerce.chatbot.src.tools.service_tools import (
    get_reviews,
    create_review,
    register_gift_card
)
from ecommerce.chatbot.src.tools.retrieval_tools import search_knowledge_base
from ecommerce.chatbot.src.tools.address_tools import (
    open_address_search,
    save_shipping_address_from_ui,
)

# Define Tool List
TOOLS = [
    get_order_details,
    get_shipping_details,
    get_user_orders,
    update_payment_method,
    change_product_option,
    cancel_order,
    check_refund_eligibility,
    check_exchange_eligibility,
    register_return_request,
    register_exchange_request,
    get_reviews,
    create_review,
    register_gift_card,
    search_knowledge_base,
    open_address_search,
    save_shipping_address_from_ui,
]

# Sensitive Tools requiring Human Approval
SENSITIVE_TOOLS = {
    "cancel_order", 
    "register_return_request", 
    "register_exchange_request", 
    "update_payment_method"
}

ORDER_ID_REQUIRED_TOOLS = {
    "check_refund_eligibility",
    "cancel_order",
    "register_return_request",
    "register_exchange_request",
}

# Initialize ToolNode -> workflow.py로 이동
tool_node = ToolNode(TOOLS)

# Context Compaction Settings
MAX_HISTORY_TOKENS = 3000
KEEP_RECENT_TURNS = 3
SUMMARY_MODEL = "gpt-4o-mini"


class TaskType(str, Enum):
    ORDER_QUERY = "ORDER_QUERY"
    POLICY_CHECK = "POLICY_CHECK"
    FAQ_RETRIEVAL = "FAQ_RETRIEVAL"
    ORDER_ACTION = "ORDER_ACTION"
    GENERAL_CHAT = "GENERAL_CHAT"


class TaskItem(BaseModel):
    task: TaskType
    args: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        extra = "forbid"


class DecompositionResult(BaseModel):
    tasks: List[TaskItem] = Field(default_factory=list)


DECOMPOSER_PROMPT = """
당신은 사용자 요청을 실행 가능한 작업 목록으로 분해하는 Planner입니다.
반드시 JSON 스키마(DecompositionResult)에 맞춰 응답하세요.

작업 타입 정의:
- ORDER_QUERY: 주문/배송/주문내역 조회
- POLICY_CHECK: 환불/반품/교환/결제/배송 정책 확인
- FAQ_RETRIEVAL: 일반 FAQ/정보 검색
- ORDER_ACTION: 취소/환불/교환/결제수단변경 같은 실제 액션
- GENERAL_CHAT: 위에 해당하지 않는 일반 대화

규칙:
1) 복합 요청이면 여러 작업으로 분해하세요.
2) args에는 필요한 최소 파라미터만 넣으세요.
3) order_id가 없는데 환불/취소/교환을 요청하면 ORDER_ACTION으로 넣되 args에 action만 넣어도 됩니다.
4) 반드시 tasks 배열을 반환하세요. 비어 있으면 GENERAL_CHAT 1개를 반환하세요.
5) 하나 이상의 실행 가능한 작업(ORDER_ACTION/ORDER_QUERY/POLICY_CHECK/FAQ_RETRIEVAL)이 있으면 GENERAL_CHAT을 함께 넣지 마세요.
6) [현재 작업 상태]가 refund/exchange 이고 status가 validating 또는 approving이며 target_id가 존재하면,
   사용자의 최신 발화가 이전 절차를 "계속 진행"하려는 맥락인지 우선 판단하세요.
   이 경우 다음 단계는 ORDER_ACTION 하나만 반환하고 args는 action='address_search', order_id=target_id 로 설정하세요.
7) 이전 Assistant가 이미 "반품/교환 진행 여부"를 질문했고 사용자가 진행 의사를 보인 턴이라면,
   환불 가능 여부 재확인(action='refund')으로 되돌아가지 말고 주소 수집 단계(action='address_search')로 진행하세요.
"""


def _get_last_user_message(messages: List) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            return msg.content.strip()
    return ""


def _normalize_task_args(args: Any) -> Dict[str, Any]:
    """Normalize various arg formats to Dict[str, Any]"""
    if args is None:
        return {}
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        return {"query": args}
    return {}


def _extract_order_id_from_text(text: str) -> str | None:
    """
    사용자 입력에서 주문번호(ORD-...)를 간단히 추출합니다.
    정규식 없이 토큰 스캔으로 처리합니다.
    """
    if not text:
        return None

    # 0) JSON payload 우선 처리 (프론트에서 이벤트를 구조화 전송하는 경우)
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            # 단일 선택
            single_keys = ["order_id", "selected_order_id"]
            for key in single_keys:
                value = payload.get(key)
                if isinstance(value, str) and value.upper().startswith("ORD-"):
                    return value.strip()

            # 다중 선택
            selected = payload.get("selected_order_ids")
            if isinstance(selected, list):
                for item in selected:
                    if isinstance(item, str) and item.upper().startswith("ORD-"):
                        return item.strip()
    except Exception:
        pass

    # 공백 기준 기본 토큰화 + 주변 문장부호 제거
    raw_tokens = text.replace("\n", " ").split(" ")
    for token in raw_tokens:
        candidate = token.strip().strip(".,!?()[]{}'\"")
        if candidate.upper().startswith("ORD-") and len(candidate) >= 8:
            # 한국어 조사/특수문자 제거를 위해 ORD- 이후 유효문자만 유지
            # 예: "ORD-20260212-0003를" -> "ORD-20260212-0003"
            cleaned_chars: List[str] = []
            for ch in candidate:
                if ch.isascii() and (ch.isalnum() or ch == "-"):
                    cleaned_chars.append(ch)
                else:
                    break
            cleaned = "".join(cleaned_chars)
            if cleaned.upper().startswith("ORD-") and len(cleaned) >= 8:
                return cleaned
    return None


def _extract_action_from_json_payload(text: str) -> str | None:
    """
    프론트 이벤트 JSON에서 action(cancel/refund/exchange ...)을 추출합니다.
    """
    if not text:
        return None

    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            return None

        action = payload.get("action")
        if isinstance(action, str) and action.strip():
            return action.strip().lower()
    except Exception:
        return None

    return None


def _extract_json_payload(text: str) -> Dict[str, Any] | None:
    """
    사용자 입력이 JSON 문자열인 경우 dict로 반환합니다.
    """
    if not text:
        return None

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None

    return None


def _extract_address_selection_args(payload: Dict[str, Any]) -> Dict[str, Any]:
    """주소 선택 이벤트 payload를 ORDER_ACTION 인자로 평탄화합니다."""
    address_obj = payload.get("address")
    address_data = address_obj if isinstance(address_obj, dict) else {}

    def _pick(*keys: str) -> Any:
        for key in keys:
            if key in address_data and address_data.get(key) is not None:
                return address_data.get(key)
            if key in payload and payload.get(key) is not None:
                return payload.get(key)
        return None

    return {
        "action": "address_selected",
        "road_address": _pick("road_address", "roadAddress"),
        "jibun_address": _pick("jibun_address", "jibunAddress"),
        "post_code": _pick("post_code", "postCode", "zonecode", "zip_code"),
        "detail_address": _pick("detail_address", "detailAddress"),
        "recipient_name": _pick("recipient_name", "recipientName"),
        "phone": _pick("phone", "phone_number"),
        "is_default": bool(_pick("is_default", "isDefault") or False),
    }


def _build_decomposer_context(messages: List, max_items: int = 8) -> str:
    """
    Decomposer에 전달할 최근 대화 컨텍스트를 구성합니다.
    - HumanMessage/AIMessage만 사용
    - [cleared] 메시지는 제외
    - 최근 max_items개만 유지
    """
    lines: List[str] = []

    for msg in messages:
        content = getattr(msg, "content", None)
        if not isinstance(content, str):
            continue
        content = content.strip()
        if not content or content == "[cleared]":
            continue

        if isinstance(msg, HumanMessage):
            lines.append(f"USER: {content[:240]}")
        elif isinstance(msg, AIMessage):
            lines.append(f"ASSISTANT: {content[:240]}")

    if not lines:
        return ""

    return "\n".join(lines[-max_items:])


def _decompose_tasks(user_message: str, messages: List, current_task: Any = None) -> List[Dict[str, Any]]:
    llm = _make_llm(model=settings.OPENAI_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(DecompositionResult, method="function_calling")

    conversation_context = _build_decomposer_context(messages)
    task_context = ""
    if isinstance(current_task, dict) and current_task:
        task_context = json.dumps(current_task, ensure_ascii=False)

    decomposer_input = (
        f"[최근 대화 컨텍스트]\n{conversation_context or '(없음)'}\n\n"
        f"[현재 사용자 입력]\n{user_message[:2000]}\n\n"
        f"[현재 작업 상태]\n{task_context or '(없음)'}\n\n"
        "주의: 현재 사용자 입력이 짧거나 모호하더라도, 직전 대화 문맥과 현재 작업 상태를 우선 반영해 "
        "GENERAL_CHAT으로 과도하게 분류하지 말고 적절한 작업으로 분해하세요."
    )

    # 1차 시도
    parsed = structured_llm.invoke([
        SystemMessage(content=DECOMPOSER_PROMPT),
        HumanMessage(content=decomposer_input),
    ])

    tasks = parsed.tasks if isinstance(parsed, DecompositionResult) else []

    # 2차 재시도 (실패/빈 배열 방어)
    if not tasks:
        retry_msg = (
            "이전 응답이 비어 있었습니다. 반드시 tasks 배열에 최소 1개 이상 넣어 반환하세요.\n"
            f"사용자 요청: {decomposer_input[:4000]}"
        )
        parsed = structured_llm.invoke([
            SystemMessage(content=DECOMPOSER_PROMPT),
            HumanMessage(content=retry_msg),
        ])
        tasks = parsed.tasks if isinstance(parsed, DecompositionResult) else []

    if not tasks:
        return [{"task": TaskType.GENERAL_CHAT.value, "args": {}}]

    normalized: List[Dict[str, Any]] = []
    for item in tasks:
        normalized.append(
            {
                "task": item.task.value,
                "args": _normalize_task_args(item.args),
            }
        )
    return normalized


def _resolve_user_id(state: AgentState) -> int:
    user_info = state.get("user_info", {})
    try:
        return int(user_info.get("id", 1))
    except Exception:
        return 1


def _task_priority(task_name: str) -> int:
    # 의존성이 있는 작업을 앞에 배치
    if task_name == TaskType.ORDER_QUERY.value:
        return 1
    if task_name == TaskType.POLICY_CHECK.value:
        return 2
    if task_name == TaskType.ORDER_ACTION.value:
        return 3
    if task_name == TaskType.FAQ_RETRIEVAL.value:
        return 4
    return 5


def _build_task_summary(task_results: List[Dict[str, Any]]) -> str:
    if not task_results:
        return "요청을 처리했지만 결과를 만들지 못했습니다. 다시 말씀해 주세요."

    lines: List[str] = []
    for idx, item in enumerate(task_results, start=1):
        task_name = item.get("task", "UNKNOWN")
        result = item.get("result")

        if isinstance(result, dict):
            if result.get("error"):
                lines.append(f"{idx}. [{task_name}] 오류: {result['error']}")
                continue
            if result.get("message"):
                lines.append(f"{idx}. [{task_name}] {result['message']}")
                continue
            if result.get("documents"):
                lines.append(f"{idx}. [{task_name}] 관련 정보를 찾았습니다. ({len(result['documents'])}건)")
                continue

        lines.append(f"{idx}. [{task_name}] 처리 완료")

    return "\n".join(lines)


def _execute_single_task(task: Dict[str, Any], state: AgentState) -> Dict[str, Any]:
    task_name = task.get("task", TaskType.GENERAL_CHAT.value)
    args = _normalize_task_args(task.get("args"))
    user_id = _resolve_user_id(state)

    if task_name == TaskType.ORDER_QUERY.value:
        order_id = args.get("order_id")
        if order_id:
            result = get_order_details.invoke({"order_id": order_id, "user_id": user_id})
        else:
            result = get_user_orders.invoke(
                {
                    "user_id": user_id,
                    "requires_selection": bool(args.get("requires_selection", False)),
                    "action_context": args.get("action_context"),
                }
            )
        return {"task": task_name, "result": result}

    if task_name == TaskType.POLICY_CHECK.value:
        query = args.get("query") or args.get("policy") or _get_last_user_message(state.get("messages", []))
        category = args.get("category", "취소/반품/교환")
        result = search_knowledge_base.invoke({"query": query, "category": category})
        return {"task": task_name, "result": result}

    if task_name == TaskType.FAQ_RETRIEVAL.value:
        query = args.get("query") or _get_last_user_message(state.get("messages", []))
        category = args.get("category")
        payload = {"query": query}
        if category:
            payload["category"] = category
        result = search_knowledge_base.invoke(payload)
        return {"task": task_name, "result": result}

    if task_name == TaskType.ORDER_ACTION.value:
        action = str(args.get("action", "")).lower()
        
        # 한글 액션명을 영어로 정규화
        action_map = {
            "취소": "cancel",
            "환불": "refund",
            "반품": "refund",
            "교환": "exchange",
            "배송조회": "shipping",
            "배송": "shipping",
            "결제변경": "payment_update",
            "결제수단변경": "payment_update",
            "주소검색": "address_search",
            "수거지": "address_search",
        }
        action = action_map.get(action, action)
        
        order_id = args.get("order_id")
        reason = args.get("reason", "고객 요청")

        if action in {"cancel", "refund", "exchange"} and not order_id:
            result = get_user_orders.invoke(
                {
                    "user_id": user_id,
                    "requires_selection": True,
                    "action_context": action,
                }
            )
            return {
                "task": task_name,
                "result": result,
                "current_task": {
                    "type": action if action in {"cancel", "refund", "exchange"} else "general",
                    "status": "validating",
                    "target_id": None,
                    "reason": reason,
                    "missing_info": ["order_id"],
                },
            }

        tool_name = None
        tool_args: Dict[str, Any] = {}
        current_task_type = "general"

        if action == "cancel":
            tool_name = "cancel_order"
            tool_args = {
                "order_id": order_id,
                "user_id": user_id,
                "reason": reason,
                "confirmed": True,
            }
            current_task_type = "cancel"
        elif action == "refund":
            tool_name = "check_refund_eligibility"
            tool_args = {
                "order_id": order_id,
                "user_id": user_id,
                "reason": reason,
            }
            current_task_type = "refund"
        elif action == "exchange":
            target_item = args.get("target_item") or args.get("product_name") or args.get("product_id")
            desired_option_text = (
                args.get("desired_option")
                or args.get("desired_color")
                or args.get("desired_size")
                or args.get("site_option")
            )
            has_option_input = (args.get("new_option_id") is not None) or bool(desired_option_text)

            missing_info: List[str] = []
            if not target_item:
                missing_info.append("target_item")
            if not has_option_input:
                missing_info.append("desired_option")

            # 교환은 대상 상품 + 변경 옵션 정보가 있어야 진행
            if missing_info:
                return {
                    "task": task_name,
                    "result": {
                        "message": (
                            "교환 진행을 위해 추가 정보가 필요합니다.\n"
                            "- 교환할 상품(target_item)\n"
                            "- 변경할 옵션(desired_option 또는 new_option_id)\n"
                            "예: {\"event\":\"exchange_detail\",\"order_id\":\"ORD-...\",\"target_item\":\"셔츠\",\"desired_option\":\"블랙 L\"}"
                        )
                    },
                    "current_task": {
                        "type": "exchange",
                        "status": "validating",
                        "target_id": order_id,
                        "reason": reason,
                        "missing_info": missing_info,
                    },
                }

            reason_parts = [reason]
            if target_item:
                reason_parts.append(f"대상상품:{target_item}")
            if desired_option_text:
                reason_parts.append(f"변경옵션:{desired_option_text}")

            tool_name = "check_exchange_eligibility"
            tool_args = {
                "order_id": order_id,
                "user_id": user_id,
                "reason": " / ".join(reason_parts),
                "new_option_id": args.get("new_option_id"),
            }
            current_task_type = "exchange"
        elif action in {"shipping", "shipping_status", "track_shipping"}:
            tool_name = "get_shipping_details"
            tool_args = {"order_id": order_id, "user_id": user_id}
        elif action in {"payment_update", "update_payment_method"}:
            tool_name = "update_payment_method"
            tool_args = {
                "order_id": order_id,
                "user_id": user_id,
                "payment_method": args.get("payment_method", "카드"),
                "card_number": args.get("card_number"),
            }
        elif action in {"address_search", "pickup_address"}:
            tool_name = "open_address_search"
            tool_args = {}
        elif action in {"address_selected", "save_address"}:
            tool_name = "save_shipping_address_from_ui"
            tool_args = {
                "user_id": user_id,
                "road_address": args.get("road_address"),
                "jibun_address": args.get("jibun_address"),
                "post_code": args.get("post_code"),
                "detail_address": args.get("detail_address"),
                "recipient_name": args.get("recipient_name"),
                "phone": args.get("phone"),
                "is_default": bool(args.get("is_default", False)),
            }
            current_task_type = "search"

        if not tool_name:
            return {
                "task": task_name,
                "result": {"error": f"지원하지 않는 ORDER_ACTION 입니다: {action or 'unknown'}"},
            }

        return {
            "task": task_name,
            "requires_tool_call": True,
            "tool_call": {
                "id": f"call_{uuid4().hex[:12]}",
                "name": tool_name,
                "args": tool_args,
                "type": "tool_call",
            },
            "current_task": {
                "type": current_task_type,
                "status": "validating",
                "target_id": order_id,
                "reason": reason,
                "missing_info": None,
            },
        }

    return {"task": TaskType.GENERAL_CHAT.value, "result": {"message": "일반 대화로 처리합니다."}}


@traceable(run_type="chain", name="Input Decomposer Node")
def decomposer_node(state: AgentState):
    """
    사용자 발화를 Task List(Pydantic) 형태로 분해합니다.
    """
    print("---DECOMPOSER NODE---")
    messages = state.get("messages", [])
    user_message = _get_last_user_message(messages)

    if not user_message:
        return {
            "task_list": [{"task": TaskType.GENERAL_CHAT.value, "args": {}}],
            "execution_plan": {"mode": "agent", "reason": "empty_user_message"},
        }

    # 주소 UI 선택 이벤트는 LLM 분해 없이 deterministic 처리
    incoming_payload = _extract_json_payload(user_message)
    if isinstance(incoming_payload, dict) and incoming_payload.get("event") == "address_selected":
        return {
            "question": user_message,
            "execution_plan": {"mode": "sequential", "reason": "address_selected_payload"},
            "task_list": [
                {
                    "task": TaskType.ORDER_ACTION.value,
                    "args": _extract_address_selection_args(incoming_payload),
                }
            ],
        }

    # [State-aware Resume]
    # 이전 턴에서 주문 선택이 필요한 액션(환불/취소/교환)이 pending이면
    # decomposition을 다시 하지 않고 바로 ORDER_ACTION으로 복구합니다.
    current_task = state.get("current_task") or {}
    task_type = current_task.get("type") if isinstance(current_task, dict) else None
    missing_info = current_task.get("missing_info") if isinstance(current_task, dict) else None
    status = current_task.get("status") if isinstance(current_task, dict) else None

    should_resume_order_action = (
        isinstance(current_task, dict)
        and task_type in {"cancel", "refund", "exchange"}
        and isinstance(missing_info, list)
        and len(missing_info) > 0
        and status in {"validating", "approving"}
    )

    if should_resume_order_action:
        payload = _extract_json_payload(user_message) or {}
        payload_action = _extract_action_from_json_payload(user_message)
        selected_order_id = payload.get("order_id") or payload.get("selected_order_id") or _extract_order_id_from_text(user_message)

        resume_args: Dict[str, Any] = {
            "action": payload_action or task_type,
            "reason": current_task.get("reason", "고객 요청"),
        }

        if isinstance(selected_order_id, str) and selected_order_id:
            resume_args["order_id"] = selected_order_id

        # 교환 작업의 추가 슬롯 복구
        if task_type == "exchange":
            target_item = (
                payload.get("target_item")
                or payload.get("product_name")
                or payload.get("product_id")
            )
            if target_item:
                resume_args["target_item"] = target_item

            if payload.get("new_option_id") is not None:
                resume_args["new_option_id"] = payload.get("new_option_id")

            desired_option = (
                payload.get("desired_option")
                or payload.get("desired_color")
                or payload.get("desired_size")
                or payload.get("site_option")
            )
            if desired_option:
                resume_args["desired_option"] = desired_option

        return {
            "question": user_message,
            "execution_plan": {"mode": "sequential", "reason": "resumed_order_action"},
            "task_list": [
                {
                    "task": TaskType.ORDER_ACTION.value,
                    "args": resume_args,
                }
            ],
        }

    try:
        task_list = _decompose_tasks(user_message, messages, current_task if isinstance(current_task, dict) else None)
        return {
            "question": user_message,
            "task_list": task_list,
        }
    except Exception as e:
        print(f"[Decomposer] failed: {e}")
        return {
            "question": user_message,
            "task_list": [{"task": TaskType.GENERAL_CHAT.value, "args": {}}],
            "execution_plan": {"mode": "agent", "reason": "decomposer_failed"},
        }


def orchestrator_node(state: AgentState):
    """
    Task 리스트를 기반으로 순차/병렬 실행 계획을 결정합니다.
    """
    print("---ORCHESTRATOR NODE---")
    task_list = state.get("task_list", [])

    if not task_list:
        return {"execution_plan": {"mode": "agent", "reason": "empty_task_list", "tasks": []}}

    tasks_sorted = sorted(task_list, key=lambda t: _task_priority(str(t.get("task", ""))))
    task_names = [str(t.get("task", "")) for t in tasks_sorted]

    has_order_action = TaskType.ORDER_ACTION.value in task_names
    has_policy_check = TaskType.POLICY_CHECK.value in task_names
    has_order_query = TaskType.ORDER_QUERY.value in task_names

    if task_names == [TaskType.GENERAL_CHAT.value]:
        mode = "agent"
        reason = "general_chat_only"
    # POLICY_CHECK + ORDER_ACTION은 서로 독립이므로 병렬 실행 가능
    elif has_order_action and has_policy_check and not has_order_query:
        mode = "parallel"
        reason = "policy_and_action_independent"
    # ORDER_QUERY + POLICY_CHECK은 ORDER context 의존 가능성이 있어 순차 유지
    elif has_order_query and has_policy_check:
        mode = "sequential"
        reason = "policy_check_depends_on_order_context"
    # ORDER_ACTION 단독은 제어를 위해 순차 유지
    elif has_order_action:
        mode = "sequential"
        reason = "order_action_requires_controlled_execution"
    elif len(tasks_sorted) > 1:
        mode = "parallel"
        reason = "independent_information_tasks"
    else:
        mode = "sequential"
        reason = "single_task"

    return {
        "task_list": tasks_sorted,
        "execution_plan": {
            "mode": mode,
            "reason": reason,
            "tasks": task_names,
        },
    }


def route_after_orchestration(state: AgentState) -> Literal["agent", "sequential_worker", "parallel_worker"]:
    plan = state.get("execution_plan", {})
    mode = plan.get("mode", "agent")

    if mode == "sequential":
        return "sequential_worker"
    if mode == "parallel":
        return "parallel_worker"
    return "agent"


def sequential_worker_node(state: AgentState):
    """
    Task를 순차 실행합니다. (의존성 있는 작업 전용)
    """
    print("---SEQUENTIAL WORKER NODE---")
    task_list = state.get("task_list", [])

    task_results: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    current_task = state.get("current_task")

    for task in task_list:
        executed = _execute_single_task(task, state)
        task_results.append(executed)

        if executed.get("requires_tool_call") and executed.get("tool_call"):
            tool_calls.append(executed["tool_call"])

        if executed.get("current_task"):
            current_task = executed["current_task"]

    updates: Dict[str, Any] = {"task_results": task_results}

    # current_task는 항상 유지 (주문 선택 UI 이후 context 보존)
    if current_task:
        updates["current_task"] = current_task

    if tool_calls:
        updates["messages"] = [
            AIMessage(
                content="요청하신 작업을 순차 실행하기 위해 필요한 도구를 호출합니다.",
                tool_calls=tool_calls,
            )
        ]
        return updates

    summary = _build_task_summary(task_results)
    updates["messages"] = [AIMessage(content=summary)]
    updates["generation"] = summary
    return updates


def parallel_worker_node(state: AgentState):
    """
    독립 Task를 병렬 실행합니다.
    """
    print("---PARALLEL WORKER NODE---")
    task_list = state.get("task_list", [])
    if not task_list:
        msg = "실행할 작업이 없습니다."
        return {"task_results": [], "messages": [AIMessage(content=msg)], "generation": msg}

    task_results: List[Dict[str, Any]] = []
    tool_calls: List[Dict[str, Any]] = []
    current_task = state.get("current_task")

    max_workers = min(4, max(1, len(task_list)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_execute_single_task, task, state): task for task in task_list}
        for future in as_completed(future_map):
            try:
                executed = future.result()
            except Exception as e:
                task = future_map[future]
                executed = {
                    "task": task.get("task", "UNKNOWN"),
                    "result": {"error": f"병렬 실행 실패: {str(e)}"},
                }

            task_results.append(executed)

            if executed.get("requires_tool_call") and executed.get("tool_call"):
                tool_calls.append(executed["tool_call"])

            if executed.get("current_task"):
                current_task = executed["current_task"]

    updates: Dict[str, Any] = {"task_results": task_results}

    # current_task는 항상 유지
    if current_task:
        updates["current_task"] = current_task

    if tool_calls:
        updates["messages"] = [
            AIMessage(
                content="독립 작업을 병렬로 분석한 뒤 필요한 도구를 호출합니다.",
                tool_calls=tool_calls,
            )
        ]
        return updates

    summary = _build_task_summary(task_results)
    updates["messages"] = [AIMessage(content=summary)]
    updates["generation"] = summary
    return updates


def route_after_workers(state: AgentState) -> Literal["validation", "process_output"]:
    messages = state.get("messages", [])
    if not messages:
        return "process_output"

    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "validation"
    return "process_output"


def _make_llm(model: str, temperature: float = 0) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=SecretStr(settings.OPENAI_API_KEY),
    )


def _estimate_tokens(messages: List) -> int:
    """메시지 토큰 수 대략 추정 (1토큰 ≈ 4자)"""
    total_chars = sum(len(str(getattr(m, "content", ""))) for m in messages)
    return total_chars // 4


def _group_messages_into_turns(messages: List) -> List[List]:
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


def _clear_old_turns(messages: List, keep_recent_turns: int) -> List:
    """최근 N턴 제외 메시지를 [cleared]로 치환"""
    turns = _group_messages_into_turns(messages)
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
                cleared_messages.append(ToolMessage(content="[cleared]", tool_call_id=msg.tool_call_id))

    recent_messages = [msg for turn in recent_turns for msg in turn]
    return cleared_messages + recent_messages


def _summarize_messages(messages: List) -> str | None:
    """전체 대화를 다음 턴용으로 요약"""
    if not messages:
        return None

    transcript = "\n".join(
        f"{type(m).__name__}: {str(getattr(m, 'content', ''))[:300]}"
        for m in messages
    )

    try:
        summary_llm = _make_llm(model=SUMMARY_MODEL, temperature=0)
        response = summary_llm.invoke([
            SystemMessage(content=CONTEXT_SUMMARY_SYSTEM_PROMPT),
            HumanMessage(content=transcript[:12000]),
        ])
        return response.content if isinstance(response.content, str) else None
    except Exception as e:
        print(f"[Compaction] Summary failed: {e}")
        return None


def _compress_messages_for_context(messages: List) -> List:
    """토큰 초과 시: 전체 요약 + 최근 3턴 제외 cleared"""
    token_count = _estimate_tokens(messages)
    if token_count <= MAX_HISTORY_TOKENS:
        return messages

    print(f"[Compaction] token={token_count} > {MAX_HISTORY_TOKENS}, compacting...")
    summary = _summarize_messages(messages)
    cleared = _clear_old_turns(messages, KEEP_RECENT_TURNS)

    if summary:
        return [HumanMessage(content=f"[conversation_summary]\n{summary}")] + cleared
    return cleared

@traceable(run_type="chain", name="Agent Node (Tool Calling)")
def agent_node(state: AgentState):
    """
    LLM이 대화 히스토리와 도구 목록을 보고 답변하거나 도구를 호출합니다.
    """
    print("---AGENT NODE---")
    
    # 1. 메시지 준비
    messages = state["messages"]
    messages = _compress_messages_for_context(messages)
    
    # 2. 시스템 프롬프트 준비
    # 매 턴마다 시스템 프롬프트를 컨텍스트로 주입 (state에 저장하지 않음)
    user_context = ""
    if state.get("user_info"):
            user_context += f"User Info: {json.dumps(state['user_info'], ensure_ascii=False)}\n"
    
    # [Context Injection] Prior Action (이전 의도 주입)
    prior_action = state.get("prior_action")
    if not prior_action:
        current_task = state.get("current_task")
        if current_task:
            prior_action = current_task.get("type")
    if prior_action:
        user_context += (
            f"\n[Prior Context]\nUser was trying to perform action: '{prior_action}'.\n"
            "If the user selects an order, proceed with this action.\n"
        )

    final_prompt = ECOMMERCE_SYSTEM_PROMPT + user_context + TOOL_USAGE_INSTRUCTIONS
    system_msg = SystemMessage(content=final_prompt)
    
    # 3. LLM 설정 (ChatOpenAI 사용 권장 for bind_tools)
    llm = _make_llm(model=settings.OPENAI_MODEL, temperature=0)
    
    # 4. 도구 바인딩
    llm_with_tools = llm.bind_tools(TOOLS)
    
    # 5. 호출
    # messages 리스트의 첫 번째가 SystemMessage인지 확인하고, 없으면 추가
    # 주의: invoke 시 messages에는 이미 tool_node가 추가한 ToolMessage들이 포함되어 있음
    current_messages = [system_msg] + messages
    
    response = llm_with_tools.invoke(current_messages)
    
    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """
    도구 호출 여부에 따라 다음 경로를 결정합니다.
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    # ToolCall이 있는 경우
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print(f"---DECISION: CALL TOOL ({len(last_message.tool_calls)})---")
        return "tools"
    
    # 일반 답변인 경우
    print("---DECISION: END---")
    return "end"


def route_after_validation(state: AgentState) -> Literal["tools", "human_approval", "end"]:
    """
    [Smart Validation] 이후의 경로를 결정합니다.
    Smart Validation에 의해 Tool Call이 변경되었을 수 있으므로 다시 검사합니다.
    """
    messages = state["messages"]
    last_message = messages[-1]
    
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return "end"
        
    # 1. TaskContext 확인
    current_task = state.get("current_task")
    
    # 이미 승인된 상태라면 바로 도구 실행
    if current_task and current_task.get("status") == "executing":
        return "tools"

    # 민감한 도구가 있는지 확인 (Human Approval 필요 여부)
    for tool_call in last_message.tool_calls:
        if tool_call["name"] in SENSITIVE_TOOLS:
            return "human_approval"
            
    return "tools"


def smart_validation_node(state: AgentState):
    """
    [Smart Validation]
    LLM이 호출한 도구의 파라미터를 검사하여, 필수 값이 누락된 경우
    지능적으로 다른 도구(예: 주문 목록 조회)로 대체하거나 에러를 반환합니다.
    """
    print("---SMART VALIDATION NODE---")
    messages = state["messages"]
    last_message = messages[-1]
    
    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {} # 변경 없음
        
    
    new_tool_calls = []
    has_changes = False
    
    # Init TaskContext if needed
    current_task = state.get("current_task")
    if not current_task:
        current_task = {
            "type": "general",
            "status": "idle",
            "target_id": None,
            "reason": None,
            "missing_info": []
        }
    
    # Extract user_id from user_info (default to 1 if missing)
    user_info = state.get("user_info", {})
    user_id = user_info.get("id", 1)
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        args = tool_call["args"]
        
        # 1. 환불/반품/취소/교환 시 order_id 누락 체크
        if tool_name in ORDER_ID_REQUIRED_TOOLS:
            order_id = args.get("order_id")
            # order_id가 없거나, "ORD-" 형식이 아니거나, 빈 문자열인 경우
            if not order_id or "ORD-" not in str(order_id):
                print(f"[Validation] Missing/Invalid order_id for {tool_name}. Redirecting to get_user_orders.")
                # 대체 도구 호출 생성: get_user_orders(requires_selection=True)
                new_tool_calls.append({
                    "id": tool_call["id"], # Keep ID to maintain message consistency if possible, or new ID
                    "name": "get_user_orders",
                    "args": {"requires_selection": True, "user_id": user_id},
                    "type": "tool_call" # Standard key
                })
                # 원래 의도 저장 (e.g., 'refund')
                # tool_name을 간단한 action name으로 매핑
                task_type = "general"
                if tool_name == "cancel_order":
                    task_type = "cancel"
                elif tool_name == "register_exchange_request":
                    task_type = "exchange"
                else:
                    task_type = "refund"  # check_refund_eligibility, register_return_request 등
                
                # Update TaskContext
                current_task["type"] = task_type
                current_task["status"] = "validating"
                current_task["missing_info"] = ["order_id"]

                has_changes = True
                continue
        
        # 2. get_user_orders 호출 시 action_context 캡처 및 보정
        if tool_name == "get_user_orders":
            action_context = args.get("action_context")
            
            # [Fallback] LLM이 action_context를 누락한 경우, 사용자 메시지에서 추론
            if not action_context and hasattr(last_message, "content"):
                content = last_message.content if isinstance(last_message.content, str) else ""
                if "환불" in content or "반품" in content:
                    action_context = "refund"
                elif "취소" in content:
                    action_context = "cancel"
                elif "교환" in content:
                    action_context = "exchange"
                
                if action_context:
                    print(f"[Validation] Inferred missing action_context: {action_context}")
                    # 도구 호출 인자에도 주입해주면 좋음 (UI 메시지 생성을 위해)
                    args["action_context"] = action_context
                    has_changes = True

            if action_context:
                print(f"[Validation] Capturing action_context: {action_context}")
                current_task["type"] = action_context
                current_task["status"] = "validating"
                has_changes = True # Flag to update state


        # 기본: 변경 없이 유지 (args가 수정되었을 수 있음)
        new_tool_calls.append({
            "id": tool_call["id"],
            "name": tool_name,
            "args": args,
            "type": tool_call.get("type", "tool_call")
        })
    
    if has_changes:
        # 메시지 갱신 (ID 유지를 위해 속성 변경 후 반환)
        # LangGraph에서는 동일 ID의 메시지를 반환하면 덮어쓰기(Upsert)가 됨
        updated_message = AIMessage(
            content=last_message.content,
            tool_calls=new_tool_calls,
            id=last_message.id 
        )
        # TaskContext도 state에 저장하여 UI 및 다음 턴 Agent가 알 수 있게 함
        return {
            "messages": [updated_message],
            "current_task": current_task
        }
    
    return {} # 변경 없음


def human_approval_node(state: AgentState):
    """
    [Human-in-the-loop]
    민감한 도구 실행 전 사용자의 승인을 요청합니다.
    """
    print("---HUMAN APPROVAL NODE---")
    messages = state["messages"]
    last_message = messages[-1]
    
    # 이미 승인된 상태라면 통과
    current_task = state.get("current_task")
    if current_task and current_task.get("status") == "executing":
        print("---APPROVAL: ALREADY APPROVED---")
        return {}
        
    # 민감한 도구가 포함되어 있는지 확인
    sensitive_calls = [
        tc for tc in last_message.tool_calls 
        if tc["name"] in SENSITIVE_TOOLS
    ]
    
    if not sensitive_calls:
        return {}
        
    # [Infinite Loop Prevention & Context Awareness]
    # 1. 사용자가 이미 승인("응", "진행해")했거나, 
    #    필요한 정보("경기도 ...")를 입력해서 의도를 보인 경우 통과
    
    # 마지막 사용자 메시지 찾기 (역순 탐색)
    last_user_msg = None
    for msg in reversed(messages[:-1]): # 현재 ToolMessage 제외하고 뒤에서부터
        if isinstance(msg, HumanMessage):
            last_user_msg = msg
            break
            
    if last_user_msg and hasattr(last_user_msg, "content"):
        raw_content = last_user_msg.content
        content = raw_content.strip() if isinstance(raw_content, str) else ""
        print(f"---APPROVAL CHECK: Last User Msg='{content}'---")
        
        # A. LLM 기반 승인 여부 판단 (LLM-based Confirmation Check)
        try:
            # 빠른 응답을 위해 3.5-turbo 등 가벼운 모델 사용 권장 (여기서는 기본 설정 따름)
            approval_llm = _make_llm(model="gpt-4o-mini", temperature=0)
            
            prompt = APPROVAL_CHECK_PROMPT_TEMPLATE.format(
                user_message=content,
                tool_name=sensitive_calls[0]["name"],
                tool_args=sensitive_calls[0].get("args"),
            )
            
            response = approval_llm.invoke([HumanMessage(content=prompt)])
            decision_text = response.content if isinstance(response.content, str) else ""
            decision = decision_text.strip().upper()
            print(f"---APPROVAL LLM DECISION: {decision} ({content})---")
            
            if "YES" in decision:
                if current_task:
                    current_task["status"] = "executing"
                return {"current_task": current_task}
                
        except Exception as e:
            print(f"---APPROVAL LLM ERROR: {e}---")
            # Fallback to keyword matching if LLM fails
            positive_keywords = ["응", "네", "예", "맞아", "진행", "해줘", "yes", "ok", "confirm", "좋아", "수락"]
            if any(keyword in content.lower() for keyword in positive_keywords):
                print("---APPROVAL: Detected positive keyword (Fallback)---")
                if current_task:
                    current_task["status"] = "executing"
                return {"current_task": current_task}
            
        # B. 인자 매칭 (Implicit Confirmation via Slot Filling)
        # 툴 호출 인자값(예: 주소)이 사용자 메시지에 포함되어 있다면, 
        # 사용자가 해당 정보를 제공하며 진행을 의도한 것으로 간주
        try:
            tool_args = sensitive_calls[0].get("args", {})
            for _, value in tool_args.items():
                if isinstance(value, str) and len(value) > 1 and value in content:
                    # 예: arg="경기도", content="경기도로 보내줘" -> 매칭
                    print(f"---APPROVAL: Detected argument match ('{value}') in user message---")
                    if current_task:
                        current_task["status"] = "executing"
                    return {"current_task": current_task}
        except Exception as e:
            print(f"---APPROVAL CHECK ERROR: {e}---")

    # 2. state에 pending_approval 상태가 있을 때 (이전 턴에서 시스템이 물어본 경우)
    if current_task and current_task.get("status") == "approving":
            # 위 로직에서 걸러지지 않았더라도, pending 상태에서 다시 왔다면 승인으로 간주
         current_task["status"] = "executing"
         return {"current_task": current_task}
    
    # 2. 첫 진입 (action_status가 'idle'이거나 없거나) -> 승인 요청 UI 띄움
    is_approving = current_task and current_task.get("status") == "approving"
    
    if not is_approving:
        tool_name = sensitive_calls[0]["name"]
        
        print(f"---APPROVAL REQUEST: {tool_name}---")
        
        # Init TaskContext if missing
        if not current_task:
            current_task = {"type": "general", "status": "idle", "target_id": None}
            
        current_task["status"] = "approving"
        
        return {
            "current_task": current_task,
            "messages": [
                # Tool 실행을 중단하고, 시스템(AI)이 질문하는 형태로 반환
                # ToolMessage를 쓰지 않고 AIMessage를 써서 대화를 이어감
                AIMessage(content="해당 작업을 진행하시겠습니까? 확인해 주시면 절차를 진행하겠습니다.")
            ]
        }
    
    # "pending_approval" 상태에서 다시 여기로 왔다면 승인된 것으로 간주하고 통과
    if current_task:
        current_task["status"] = "executing"
    return {"current_task": current_task}


def route_after_approval(state: AgentState) -> Literal["tools", "process_output"]:
    """
    승인 노드 이후의 경로를 결정합니다.
    - executing: 도구 실행 (tools)
    - 그 외: 사용자 입력 대기/대화 종료 처리 (process_output)
    """
    current_task = state.get("current_task")
    status = current_task.get("status") if current_task else "idle"
    print(f"---ROUTE AFTER APPROVAL: {status}---")
    
    if status == "executing":
        return "tools"
    
    return "process_output"


def process_output_node(state: AgentState):
    """
    최종 응답을 API 스펙에 맞게 가공합니다.
    (chat.py에서 참조하는 generation, ui_action, tool_outputs 등을 채움)
    """
    print("---PROCESS OUTPUT---")
    messages = state["messages"]
    last_message = messages[-1]
    
    result = {
        "generation": last_message.content if hasattr(last_message, "content") else str(last_message),
        "tool_outputs": [] # 하위 호환성 (선택사항)
    }
    
    # UI Action 추출 1: task_results에서 (Worker 직접 실행)
    task_results = state.get("task_results", [])
    for task_result in task_results:
        result_data = task_result.get("result")
        if isinstance(result_data, dict) and result_data.get("ui_action"):
            result["tool_outputs"].append(result_data)
    
    # UI Action 추출 2: ToolMessage에서 (Tool Node 실행)
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                content = msg.content
                if not isinstance(content, str):
                    continue
                data = json.loads(content)
                if isinstance(data, dict):
                    # 일반 UI Action
                    if "ui_action" in data:
                        result["tool_outputs"].append(data)
            except Exception:
                pass
            
    # Approval Status 확인
    if state.get("action_status") == "pending_approval":
        # 승인 대기 상태인 경우 명시적 플래그 전달 가능
        # (이미 tool_outputs에 show_confirmation이 들어갔을 것임)
        pass
            
    return result


def route_after_tools(state: AgentState) -> Literal["agent", "process_output"]:
    """
    도구 실행 후 경로를 결정합니다.
    - UI Action이 발생했으면 process_output (텍스트 생성 생략)
    - 일반 도구 실행이면 agent (LLM이 결과 해석 후 답변)
    """
    print("---ROUTE AFTER TOOLS---")
    messages = state["messages"]
    last_message = messages[-1]
    
    if isinstance(last_message, ToolMessage):
        try:
            content = last_message.content
            if not isinstance(content, str):
                return "agent"
            data = json.loads(content)
            if isinstance(data, dict):
                # UI Action이 포함되어 있으면 텍스트 생성 생략하고 바로 종료
                if "ui_action" in data and data["ui_action"]:
                    print(f"---DECISION: UI ACTION ({data['ui_action']}) -> END---")
                    return "process_output"
        except Exception:
            pass
            
    # 기본: Agent로 돌아가서 결과 해석
    print("---DECISION: BACK TO AGENT---")
    return "agent"
