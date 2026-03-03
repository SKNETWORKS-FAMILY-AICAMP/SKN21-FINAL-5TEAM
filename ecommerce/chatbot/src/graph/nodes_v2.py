"""LangGraph 노드 정의 (v2 — Agent 중심 아키텍처).

이전의 Decomposer → Fixed Worker 이중 라우팅을 제거하고,
LLM이 bind_tools를 통해 직접 도구를 선택하는 구조로 단순화.

워크플로우:
  START → guardrail → preprocess → agent ⇄ (validation → approval → tools)
                                         → process_output → END
"""

import json
from typing import Any, Dict, List, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import ToolNode

from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.prompts.system_prompts import get_ecommerce_system_prompt
from ecommerce.chatbot.src.prompts.agent_prompts import (
    get_tool_usage_instructions,
    get_approval_check_prompt_template,
    get_guardrail_prompt,
)
from ecommerce.chatbot.src.graph.llm_providers import (
    resolve_llm_config,
    make_chat_llm,
    hf_invoke,
    compress_messages_for_context,
)

# ── Tool Registry ─────────────────────────────────────────
# 모든 도구를 한 곳에 등록하여 LLM이 bind_tools로 직접 선택하게 합니다.

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
    register_exchange_request,
)
from ecommerce.chatbot.src.tools.service_tools import (
    get_reviews,
    create_review,
    register_gift_card,
    generate_review_draft,
)
from ecommerce.chatbot.src.tools.retrieval_tools import search_knowledge_base
from ecommerce.chatbot.src.tools.address_tools import (
    open_address_search,
    save_shipping_address_from_ui,
)
from ecommerce.chatbot.src.tools.product_tools import search_products_vector
from ecommerce.chatbot.src.tools.recommendation_tools import (
    recommend_clothes,
    search_by_image,
)
from ecommerce.chatbot.src.tools.used_tools import register_used_sale, request_pickup

# 전체 도구 목록 — LLM이 이 중에서 직접 선택합니다
TOOLS = [
    # 주문 관련
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
    # 서비스
    get_reviews,
    create_review,
    register_gift_card,
    generate_review_draft,
    # 검색/지식
    search_knowledge_base,
    search_products_vector,
    # 추천
    recommend_clothes,
    search_by_image,
    # 중고
    register_used_sale,
    request_pickup,
    # 주소
    open_address_search,
    save_shipping_address_from_ui,
]

# 민감 도구 — Human Approval 필요
SENSITIVE_TOOLS = {
    "cancel_order",
    "register_return_request",
    "register_exchange_request",
    "update_payment_method",
}

# order_id가 필수인 도구
ORDER_ID_REQUIRED_TOOLS = {
    "check_refund_eligibility",
    "cancel_order",
    "register_return_request",
    "register_exchange_request",
}

ORDER_ACTION_COMPLETION_TYPES = {"refund", "cancel", "exchange"}

# ToolNode 인스턴스 (workflow.py에서 사용)
tool_node = ToolNode(TOOLS)


# ── Helper functions ──────────────────────────────────────


def _get_last_user_message(messages: List) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str):
            return msg.content.strip()
    return ""


def _extract_json_payload(text: str) -> Dict[str, Any] | None:
    """사용자 입력이 JSON 문자열인 경우 dict로 반환합니다."""
    if not text:
        return None
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return None
    return None


def _extract_json_object(text: str) -> Dict[str, Any] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None

    return None


def _resolve_user_id(state: AgentState) -> int:
    user_info = state.get("user_info", {})
    try:
        return int(user_info.get("id", 1))
    except Exception:
        return 1


# ── Node: Guardrail ───────────────────────────────────────


def guardrail_node(state: AgentState):
    """
    보안 가드레일:
    사용자 입력(마지막 메시지)에 PII나 악의적 프롬프트가 있는지 LLM으로 검사합니다.
    """
    print("---GUARDRAIL NODE---")
    messages = state.get("messages", [])
    user_message = _get_last_user_message(messages)

    if not user_message:
        return {"is_safe": True, "safe_message": None}

    # 프론트 이벤트(JSON)는 안전 패스
    if _extract_json_payload(user_message):
        return {"is_safe": True, "safe_message": None}

    provider, model_name = resolve_llm_config(state)
    guardrail_prompt = get_guardrail_prompt(provider=provider, model_name=model_name)

    try:
        if provider in {"openai", "vllm"}:
            llm = make_chat_llm(provider=provider, model=model_name, temperature=0)
            response = llm.with_config({"run_name": "guardrail_llm"}).invoke(
                [
                    SystemMessage(content=guardrail_prompt),
                    HumanMessage(content=user_message),
                ]
            )
            raw = response.content if isinstance(response.content, str) else ""
        else:
            response = hf_invoke(
                [
                    SystemMessage(content=guardrail_prompt),
                    HumanMessage(content=user_message),
                ],
                model_name,
                temperature=0,
            )
            raw = response.content if isinstance(response.content, str) else ""

        parsed = _extract_json_object(raw)
        if parsed and isinstance(parsed, dict):
            is_safe = parsed.get("is_safe", True)
            message = parsed.get("message")
            return {
                "is_safe": is_safe,
                "safe_message": message if not is_safe else None,
            }

        return {"is_safe": True, "safe_message": None}
    except Exception as e:
        print(f"[Guardrail] failed: {e}")
        return {"is_safe": True, "safe_message": None}


def route_after_guardrail(state: AgentState) -> Literal["preprocess", "process_output"]:
    """가드레일 통과 여부에 따라 다음 경로를 결정합니다."""
    if state.get("is_safe", True):
        return "preprocess"
    return "process_output"


# ── Node: Preprocess ──────────────────────────────────────


def preprocess_node(state: AgentState):
    """
    프론트엔드 JSON 이벤트(주소선택 등)를 자연어 + 컨텍스트로 변환하여
    Agent가 이해할 수 있게 준비합니다.
    """
    print("---PREPROCESS NODE---")
    messages = state.get("messages", [])
    user_message = _get_last_user_message(messages)

    if not user_message:
        return {}

    payload = _extract_json_payload(user_message)
    if not payload:
        return {"question": user_message}

    event = payload.get("event", "")

    # 주소 선택 이벤트 → 자연어로 변환
    if event == "address_selected":
        address = payload.get("address", {})
        road = address.get("road_address") or address.get("roadAddress") or ""
        detail = address.get("detail_address") or address.get("detailAddress") or ""
        full_address = f"{road} {detail}".strip()

        current_task = state.get("current_task") or {}
        task_type = current_task.get("type", "general")
        target_id = current_task.get("target_id")

        if task_type == "refund" and target_id:
            natural_msg = (
                f"주문번호 {target_id}의 반품 수거지를 '{full_address}'으로 "
                f"설정하고 반품을 접수해주세요."
            )
        elif task_type == "exchange" and target_id:
            natural_msg = (
                f"주문번호 {target_id}의 교환 수거지를 '{full_address}'으로 "
                f"설정하고 교환을 접수해주세요."
            )
        else:
            natural_msg = f"주소를 '{full_address}'으로 저장해주세요."

        # 기존 HumanMessage를 자연어로 교체
        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg}

    # 주문 선택 이벤트
    order_id = payload.get("order_id") or payload.get("selected_order_id")
    action = payload.get("action")

    if order_id and action:
        natural_msg = f"주문번호 {order_id}에 대해 {action} 처리해주세요."
        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg}

    if order_id:
        current_task = state.get("current_task") or {}
        task_type = current_task.get("type", "general")
        if task_type in {"cancel", "refund", "exchange"}:
            natural_msg = f"주문번호 {order_id}에 대해 {task_type} 진행해주세요."
        else:
            natural_msg = f"주문번호 {order_id}의 상세 정보를 알려주세요."
        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg}

    return {"question": user_message}


# ── Node: Agent ───────────────────────────────────────────


def agent_node(state: AgentState):
    """
    LLM이 대화 히스토리와 도구 목록을 보고 답변하거나 도구를 호출합니다.
    이전의 Decomposer + Fixed Worker 역할을 통합합니다.
    """
    print("---AGENT NODE---")
    provider, model_name = resolve_llm_config(state)
    system_prompt = get_ecommerce_system_prompt(
        provider=provider, model_name=model_name
    )
    tool_usage_instructions = get_tool_usage_instructions(
        provider=provider, model_name=model_name
    )

    # 1. 메시지 컴팩션
    messages = state["messages"]
    messages = compress_messages_for_context(messages, provider, model_name)

    # 2. 시스템 프롬프트 구성
    user_context = ""
    if state.get("user_info"):
        user_context += (
            f"User Info: {json.dumps(state['user_info'], ensure_ascii=False)}\n"
        )

    # 현재 작업 컨텍스트 주입
    current_task = state.get("current_task")
    if current_task and isinstance(current_task, dict):
        task_type = current_task.get("type")
        status = current_task.get("status")
        target_id = current_task.get("target_id")
        missing = current_task.get("missing_info")
        reason = current_task.get("reason")

        context_parts = ["\n[현재 작업 컨텍스트]"]
        if task_type:
            context_parts.append(f"- 작업 유형: {task_type}")
        if status:
            context_parts.append(f"- 진행 단계: {status}")
        if target_id:
            context_parts.append(f"- 대상 주문: {target_id}")
        if reason:
            context_parts.append(f"- 사유: {reason}")
        if missing:
            context_parts.append(f"- 부족한 정보: {', '.join(missing)}")

        if task_type in {"cancel", "refund", "exchange"} and status in {
            "validating",
            "approving",
        }:
            context_parts.append(
                f"\n[중요] 사용자가 {task_type} 작업을 진행 중입니다. "
                "사용자가 주문을 선택하거나 진행 의사를 보이면 해당 작업을 이어서 처리하세요."
            )

        user_context += "\n".join(context_parts)

    final_prompt = system_prompt + user_context + tool_usage_instructions
    system_msg = SystemMessage(content=final_prompt)
    current_messages = [system_msg] + messages

    if provider in {"openai", "vllm"}:
        llm = make_chat_llm(provider=provider, model=model_name, temperature=0)
        llm_with_tools = llm.bind_tools(TOOLS)
        response = llm_with_tools.invoke(current_messages)
    else:
        response = hf_invoke(current_messages, model_name, temperature=0)

    return {"messages": [response]}


# ── Route: Should Continue ────────────────────────────────


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """도구 호출 여부에 따라 다음 경로를 결정합니다."""
    messages = state["messages"]
    last_message = messages[-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print(f"---DECISION: CALL TOOL ({len(last_message.tool_calls)})---")
        return "tools"

    print("---DECISION: END---")
    return "end"


# ── Node: Smart Validation ────────────────────────────────


def smart_validation_node(state: AgentState):
    """
    LLM이 호출한 도구의 파라미터를 검사하여, 필수 값이 누락된 경우
    지능적으로 다른 도구(예: 주문 목록 조회)로 대체합니다.
    """
    print("---SMART VALIDATION NODE---")
    messages = state["messages"]
    last_message = messages[-1]

    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return {}

    new_tool_calls = []
    has_changes = False

    current_task = state.get("current_task") or {
        "type": "general",
        "status": "idle",
        "target_id": None,
        "reason": None,
        "missing_info": [],
    }

    user_id = _resolve_user_id(state)

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        args = tool_call["args"]

        # 1. order_id 필수 도구에서 누락 체크
        if tool_name in ORDER_ID_REQUIRED_TOOLS:
            order_id = args.get("order_id")
            if not order_id or "ORD-" not in str(order_id):
                print(
                    f"[Validation] Missing/Invalid order_id for {tool_name}. "
                    "Redirecting to get_user_orders."
                )

                # action_context 추론 (LLM이 못 넣었을 때 보정)
                action_context = {
                    "cancel_order": "cancel",
                    "register_return_request": "refund",
                    "check_refund_eligibility": "refund",
                    "register_exchange_request": "exchange",
                    "check_exchange_eligibility": "exchange",
                }.get(tool_name, "general")

                new_tool_calls.append(
                    {
                        "id": tool_call["id"],
                        "name": "get_user_orders",
                        "args": {
                            "requires_selection": True,
                            "user_id": user_id,
                            "action_context": action_context,
                        },
                        "type": "tool_call",
                    }
                )

                current_task["type"] = action_context
                current_task["status"] = "validating"
                current_task["missing_info"] = ["order_id"]
                has_changes = True
                continue

        # 2. get_user_orders 호출 시 action_context 보정
        if tool_name == "get_user_orders":
            action_context = args.get("action_context")
            if not action_context:
                # 현재 작업 컨텍스트에서 추론
                task_type = current_task.get("type")
                if task_type in {"cancel", "refund", "exchange"}:
                    args["action_context"] = task_type
                    has_changes = True

            if args.get("action_context"):
                current_task["type"] = args["action_context"]
                current_task["status"] = "validating"
                has_changes = True

        new_tool_calls.append(
            {
                "id": tool_call["id"],
                "name": tool_name,
                "args": args,
                "type": tool_call.get("type", "tool_call"),
            }
        )

    if has_changes:
        updated_message = AIMessage(
            content=last_message.content, tool_calls=new_tool_calls, id=last_message.id
        )
        return {"messages": [updated_message], "current_task": current_task}

    return {}


# ── Route: After Validation ───────────────────────────────


def route_after_validation(
    state: AgentState,
) -> Literal["tools", "human_approval", "end"]:
    """
    Validation 이후 경로:
    - 민감 도구 → human_approval
    - 이미 승인됨 → tools
    - 그 외 → tools
    """
    messages = state["messages"]
    last_message = messages[-1]

    if not hasattr(last_message, "tool_calls") or not last_message.tool_calls:
        return "end"

    current_task = state.get("current_task")
    if current_task and current_task.get("status") == "executing":
        return "tools"

    for tool_call in last_message.tool_calls:
        if tool_call["name"] in SENSITIVE_TOOLS:
            return "human_approval"

    return "tools"


# ── Node: Human Approval ─────────────────────────────────


def human_approval_node(state: AgentState):
    """
    민감한 도구 실행 전 사용자의 승인을 LLM으로 판단합니다.
    """
    print("---HUMAN APPROVAL NODE---")
    messages = state["messages"]
    last_message = messages[-1]

    current_task = state.get("current_task")

    # 이미 승인된 상태면 통과
    if current_task and current_task.get("status") == "executing":
        print("---APPROVAL: ALREADY APPROVED---")
        return {}

    sensitive_calls = [
        tc for tc in last_message.tool_calls if tc["name"] in SENSITIVE_TOOLS
    ]
    if not sensitive_calls:
        return {}

    # 사용자의 마지막 메시지로 승인 여부 판단
    last_user_msg = None
    for msg in reversed(messages[:-1]):
        if isinstance(msg, HumanMessage):
            last_user_msg = msg
            break

    if last_user_msg and hasattr(last_user_msg, "content"):
        content = (
            last_user_msg.content.strip()
            if isinstance(last_user_msg.content, str)
            else ""
        )
        print(f"---APPROVAL CHECK: Last User Msg='{content}'---")

        # LLM 기반 승인 판단
        try:
            provider, model_name = resolve_llm_config(state)
            approval_prompt = get_approval_check_prompt_template(
                provider=provider, model_name=model_name
            )
            prompt = approval_prompt.format(
                user_message=content,
                tool_name=sensitive_calls[0]["name"],
                tool_args=sensitive_calls[0].get("args"),
            )

            if provider in {"openai", "vllm"}:
                approval_llm = make_chat_llm(
                    provider=provider, model=model_name, temperature=0
                )
                response = approval_llm.with_config(
                    {"run_name": "approval_llm"}
                ).invoke([HumanMessage(content=prompt)])
            else:
                response = hf_invoke(
                    [HumanMessage(content=prompt)], model_name, temperature=0
                )

            decision = (
                response.content.strip().upper()
                if isinstance(response.content, str)
                else ""
            )
            print(f"---APPROVAL LLM DECISION: {decision}---")

            if "YES" in decision:
                if current_task:
                    current_task["status"] = "executing"
                return {"current_task": current_task}

        except Exception as e:
            print(f"---APPROVAL LLM ERROR: {e}---")

    # 이전에 승인 요청 상태였다면 (2번째 진입) → 승인으로 간주
    if current_task and current_task.get("status") == "approving":
        current_task["status"] = "executing"
        return {"current_task": current_task}

    # 첫 진입 → 승인 요청 UI 표시
    if not current_task:
        current_task = {"type": "general", "status": "idle", "target_id": None}

    current_task["status"] = "approving"
    print(f"---APPROVAL REQUEST: {sensitive_calls[0]['name']}---")

    return {
        "current_task": current_task,
        "messages": [
            AIMessage(
                content="해당 작업을 진행하시겠습니까? 확인해 주시면 절차를 진행하겠습니다."
            )
        ],
    }


def route_after_approval(state: AgentState) -> Literal["tools", "process_output"]:
    """
    승인 노드 이후:
    - executing → tools
    - 그 외 → process_output (승인 요청 메시지를 보여줌)
    """
    current_task = state.get("current_task")
    status = current_task.get("status") if current_task else "idle"
    print(f"---ROUTE AFTER APPROVAL: {status}---")
    return "tools" if status == "executing" else "process_output"


# ── Route: After Tools ────────────────────────────────────


def route_after_tools(state: AgentState) -> Literal["agent", "process_output"]:
    """
    도구 실행 후:
    - UI Action이 있으면 → process_output (텍스트 생성 생략)
    - 그 외 → agent (LLM이 결과 해석 후 답변)
    """
    print("---ROUTE AFTER TOOLS---")
    messages = state["messages"]
    last_message = messages[-1]

    if isinstance(last_message, ToolMessage):
        try:
            content = last_message.content
            if isinstance(content, str):
                data = json.loads(content)
                if isinstance(data, dict) and data.get("ui_action"):
                    print(f"---DECISION: UI ACTION ({data['ui_action']}) -> END---")
                    return "process_output"
        except Exception:
            pass

    print("---DECISION: BACK TO AGENT---")
    return "agent"


# ── Node: Process Output ─────────────────────────────────


def _should_reset_order_action_context(state: AgentState) -> bool:
    """
    ORDER_ACTION(환불/취소/교환)이 최종 실행돼서 현재 후속 컨텍스트를 더 이상 유지할 필요가 없을 때 True.
    """
    current_task = state.get("current_task")
    if not isinstance(current_task, dict):
        return False

    task_type = current_task.get("type")
    if task_type not in ORDER_ACTION_COMPLETION_TYPES:
        return False

    if current_task.get("status") != "executing":
        return False

    task_results = state.get("task_results")
    if not isinstance(task_results, list):
        return False

    return any(
        isinstance(task, dict) and task.get("task") == TaskType.ORDER_ACTION.value
        for task in task_results
    )


def process_output_node(state: AgentState):
    """
    최종 응답을 API 스펙에 맞게 가공합니다.
    (chat.py에서 참조하는 generation, ui_action, tool_outputs 등을 채움)
    """
    print("---PROCESS OUTPUT---")

    # 가드레일 실패인 경우
    is_safe = state.get("is_safe", True)
    if not is_safe:
        safe_message = (
            state.get("safe_message") or "부적절한 입력으로 인해 처리할 수 없습니다."
        )
        return {
            "generation": safe_message,
            "messages": [AIMessage(content=safe_message)],
            "tool_outputs": [],
        }

    messages = state["messages"]
    last_message = messages[-1]

    result = {
        "generation": last_message.content
        if hasattr(last_message, "content")
        else str(last_message),
        "tool_outputs": [],
    }

    # UI Action 추출: ToolMessage에서
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                content = msg.content
                if not isinstance(content, str):
                    continue
                data = json.loads(content)
                if isinstance(data, dict) and "ui_action" in data:
                    result["tool_outputs"].append(data)
            except Exception:
                pass

    if _should_reset_order_action_context(state):
        current_task = state.get("current_task")
        if isinstance(current_task, dict):
            completed_task = dict(current_task)
            completed_task["status"] = "completed"
            result["last_completed_task"] = completed_task
        result["current_task"] = None
        result["prior_action"] = None

    return result
