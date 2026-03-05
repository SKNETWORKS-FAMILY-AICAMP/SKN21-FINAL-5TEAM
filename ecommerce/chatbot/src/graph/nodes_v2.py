"""LangGraph 노드 정의 (v2 — Agent 중심 아키텍처).

이전의 Decomposer → Fixed Worker 이중 라우팅을 제거하고,
LLM이 bind_tools를 통해 직접 도구를 선택하는 구조로 단순화.

워크플로우:
  START → guardrail → preprocess → agent ⇄ (validation → approval → tools)
                                         → ui_generator → process_output → END
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
from ecommerce.chatbot.src.tools.used_tools import (
    open_used_sale_form,
    register_used_sale,
    request_pickup,
)

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
    open_used_sale_form,
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

    # 중고 판매 폼 제출 이벤트
    if event == "used_sale_submitted":
        category_id = payload.get("category_id")
        category_name = str(payload.get("category") or "").strip()
        item_name = str(payload.get("item_name") or "").strip()
        description = str(payload.get("description") or "").strip()
        condition_id = payload.get("condition_id")
        condition_name = str(payload.get("condition") or "").strip()
        expected_price = payload.get("expected_price")

        if expected_price in ("", None):
            natural_msg = (
                "중고 판매 등록을 진행해주세요. "
                f"category_id는 {category_id}, category는 '{category_name}', 상품명은 '{item_name}', "
                f"description은 '{description}', condition_id는 {condition_id}, 상태명은 '{condition_name}', 희망 가격은 미정입니다."
            )
        else:
            natural_msg = (
                "중고 판매 등록을 진행해주세요. "
                f"category_id는 {category_id}, category는 '{category_name}', 상품명은 '{item_name}', "
                f"description은 '{description}', condition_id는 {condition_id}, 상태명은 '{condition_name}', 희망 가격은 {expected_price}원입니다."
            )

        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg}

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
        return {"messages": new_messages, "question": natural_msg, "skip_agent": False}

    # 이미지 업로드 이벤트
    if event == "image_uploaded":
        image_url = payload.get("image_url") or payload.get("imageUrl")
        description = (
            str(payload.get("description") or "").strip()
            or "첨부한 이미지를 참고하여 관련 정보를 알려주세요."
        )
        query_text = str(payload.get("query") or "").strip()
        base_msg = (
            f"{description} 이미지 URL: {image_url}"
            if image_url
            else description
        )
        natural_msg = (
            f"{base_msg} 요청: {query_text}" if query_text else base_msg
        )

        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg}

    # 주문 선택 이벤트
    order_id = payload.get("order_id") or payload.get("selected_order_id")
    action = payload.get("action")

    # action-to-tool 직접 매핑: 주문이 이미 특정됐으므로 get_user_orders 재호출 방지
    _ACTION_TOOL_HINT = {
        "refund":   "check_refund_eligibility 도구를 바로 호출하세요. get_user_orders는 절대 호출하지 마세요.",
        "exchange": "check_exchange_eligibility 도구를 바로 호출하세요. get_user_orders는 절대 호출하지 마세요.",
        "cancel":   "cancel_order 도구를 바로 호출하세요. get_user_orders는 절대 호출하지 마세요.",
        "review":   "create_review 또는 generate_review_draft 도구를 바로 호출하세요. get_user_orders는 절대 호출하지 마세요.",
    }

    if order_id and action:
        hint = _ACTION_TOOL_HINT.get(str(action).lower(), "")
        natural_msg = (
            f"사용자가 주문번호 {order_id}을(를) 선택했습니다. "
            f"요청 액션: {action}. "
            f"{hint}"
        )
        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg}
    # ── 주문 선택 이벤트 (order_selected) ─────────────────────────────
    # LLM을 거치지 않고 직접 tool_calls를 주입 → validation 노드로 직행
    if event == "order_selected":
        order_id = payload.get("selected_order_id") or payload.get("order_id")
        action = str(payload.get("action") or "").lower()
        user_id = _resolve_user_id(state)

        # action → 직접 실행할 tool 이름 + 인자 매핑
        _ORDER_ACTION_TOOL: dict[str, tuple[str, dict]] = {
            "refund": (
                "check_refund_eligibility",
                {"order_id": order_id, "user_id": user_id, "reason": "환불 요청"},
            ),
            "exchange": (
                "check_exchange_eligibility",
                {"order_id": order_id, "user_id": user_id, "reason": "교환 요청"},
            ),
            "cancel": (
                "cancel_order",
                {"order_id": order_id, "user_id": user_id, "reason": "취소 요청", "confirmed": True},
            ),
        }

        if order_id and action in _ORDER_ACTION_TOOL:
            tool_name, tool_args = _ORDER_ACTION_TOOL[action]
            # AIMessage에 tool_calls 직접 주입 (LLM 호출 없음)
            import uuid as _uuid
            _tc_id = f"fc_{_uuid.uuid4().hex[:16]}"  # 최대 19자 (OpenAI 40자 제한)
            forced_ai_msg = AIMessage(
                content="",
                tool_calls=[{
                    "id": _tc_id,
                    "name": tool_name,
                    "args": tool_args,
                    "type": "tool_call",
                }],
            )
            readable_human = HumanMessage(content=f"주문번호 {order_id} {action} 요청")
            new_messages = messages[:-1] + [readable_human, forced_ai_msg]
            print(f"---PREPROCESS: order_selected → {tool_name} 직접 주입 (skip_agent)---")
            return {
                "messages": new_messages,
                "question": f"주문번호 {order_id} {action} 요청",
                "skip_agent": True,
            }

        # review 등 매핑이 없는 action → agent에게 명확한 메시지로 위임
        if order_id:
            natural_msg = f"주문번호 {order_id}에 대해 {action or '처리'} 진행해주세요."
            new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
            return {"messages": new_messages, "question": natural_msg, "skip_agent": False}

    # ── 기타 order_id 포함 이벤트 ─────────────────────────────────────
    order_id = payload.get("order_id") or payload.get("selected_order_id")
    action = payload.get("action")

    if order_id and action:
        natural_msg = f"주문번호 {order_id}에 대해 {action} 진행해주세요."
        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg, "skip_agent": False}

    if order_id:
        current_task = state.get("current_task") or {}
        task_type = current_task.get("type", "general")
        if task_type in {"cancel", "refund", "exchange"}:
            natural_msg = f"주문번호 {order_id}에 대해 {task_type} 진행해주세요."
        else:
            natural_msg = f"주문번호 {order_id}의 상세 정보를 알려주세요."
        new_messages = messages[:-1] + [HumanMessage(content=natural_msg)]
        return {"messages": new_messages, "question": natural_msg, "skip_agent": False}

    return {"question": user_message, "skip_agent": False}


# ── Router: after preprocess ──────────────────────────────
def route_after_preprocess(state: AgentState) -> Literal["agent", "validation"]:
    """
    preprocess_node가 skip_agent=True를 설정했으면 validation으로 직행.
    (order_selected 이벤트에서 AIMessage tool_calls를 직접 주입한 경우)
    """
    if state.get("skip_agent"):
        print("---ROUTE: preprocess → validation (skip_agent)---")
        return "validation"
    return "agent"


# ── Node: Agent ───────────────────────────────────────────


def agent_node(state: AgentState):
    
    """
    LLM이 대화 히스토리와 도구 목록을 보고 답변하거나 도구를 호출합니다.
    이전의 Decomposer + Fixed Worker 역할을 통합합니다.
    """
    image_bytes = state.get("image_bytes")

    if image_bytes:
        print("---IMAGE SEARCH TRIGGERED---")

        return {
            "messages": [
                AIMessage(
                    content="이미지를 분석해서 유사 상품을 찾겠습니다.",
                    tool_calls=[
                        {
                            "name": "search_by_image",
                            "args": {"image_bytes": image_bytes},
                            "id": "image_search_call",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    
    print("---AGENT NODE---")
    # skip_agent 플래그 리셋 (다음 턴에 영향 없도록)
    state["skip_agent"] = False
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
    - UI Template이 있으면 → ui_generator (LLM이 동적 UI config 생성)
      단, 현재 턴이 order_selected 이벤트(이미 주문 특정)이면 agent로 보내 결과 해석
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
                if isinstance(data, dict):
                    # 기존 방식: ui_action이 직접 지정된 경우 (주소검색, 중고판매 폼 등)
                    if data.get("ui_action"):
                        print(f"---DECISION: UI ACTION ({data['ui_action']}) -> END---")
                        return "process_output"
                    # 신규 방식: ui_template이 있는 경우
                    if data.get("ui_template"):
                        # order_selected 이벤트 후 호출된 도구이면 agent로 보내 결과 해석
                        # (주문 선택 → 환불가능여부 확인 → 결과 설명 흐름)
                        current_human = _get_last_user_message(messages)
                        human_payload = _extract_json_payload(current_human)
                        if human_payload and human_payload.get("event") == "order_selected":
                            print(f"---DECISION: UI TEMPLATE after order_selected -> AGENT (결과 해석)---")
                            return "agent"
                        print(f"---DECISION: UI TEMPLATE ({data['ui_template']}) -> UI GENERATOR---")
                        return "ui_generator"
        except Exception:
            pass

    print("---DECISION: BACK TO AGENT---")
    return "agent"


# ── Node: UI Generator ───────────────────────────────────

_UI_GENERATOR_SYSTEM_PROMPT = """당신은 이커머스 챗봇의 UI 구성을 동적으로 결정하는 전문가입니다.
사용자의 요청 의도와 도구 실행 결과를 분석하여, 가장 적절한 UI 설정을 JSON으로 반환하세요.

## 규칙

### template_type
- "order_list": 주문 목록을 보여줘야 할 때
- "product_list": 상품/추천 목록을 보여줘야 할 때

### template_config (template_type별 필드)

**order_list 일 때:**
- enable_refund_button (bool): 사용자가 환불/반품 의도가 있을 때 true
- enable_exchange_button (bool): 사용자가 교환 의도가 있을 때 true
- enable_cancel_button (bool): 사용자가 취소 의도가 있을 때 true
- enable_selection (bool): 사용자가 특정 주문을 선택해야 할 때 true (단순 조회면 false)
- selectable_statuses (list[str]): 선택 가능한 주문 상태 목록 (예: ["delivered", "shipped"])
- action_label (str): 선택 후 버튼 레이블 (예: "환불 신청하기", "교환 신청하기")

**product_list 일 때:**
- enable_selection (bool): 상품을 선택해야 할 때 true
- show_add_to_cart (bool): 장바구니 담기 버튼 표시 여부
- show_recommend_badge (bool): "추천" 뱃지 표시 여부 (추천 맥락이면 true)

## 반환 형식 (JSON만 반환, 설명 없이)
{
  "template_type": "...",
  "message": "사용자에게 표시할 안내 메시지",
  "template_config": { ... }
}"""


def ui_generator_node(state: AgentState):
    """
    LLM이 Tool 결과 + 사용자 의도를 보고 동적 UI 메타데이터를 생성합니다.

    - ui_template이 있는 ToolMessage가 있을 때 호출됩니다.
    - 생성된 ui_metadata는 process_output_node에서 최종 tool_outputs에 반영됩니다.
    """
    print("---UI GENERATOR NODE---")
    messages = state["messages"]

    # 현재 턴의 메시지와 도구 결과 수집
    current_turn_messages: list = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            current_turn_messages.append(msg)
            break
        current_turn_messages.append(msg)
    current_turn_messages = list(reversed(current_turn_messages))

    # ui_template이 포함된 ToolMessage 추출
    tool_results_with_template: list[dict] = []
    for msg in current_turn_messages:
        if isinstance(msg, ToolMessage):
            try:
                data = json.loads(msg.content)
                if isinstance(data, dict) and data.get("ui_template"):
                    tool_results_with_template.append(data)
            except Exception:
                pass

    if not tool_results_with_template:
        return {"ui_metadata": None}

    # 사용자 메시지 추출
    user_message = _get_last_user_message(messages)

    # 도구 결과 요약 (ui_data가 크면 앞 3개만 샘플로 전달)
    summarized_results = []
    for r in tool_results_with_template:
        summarized = dict(r)
        if isinstance(summarized.get("ui_data"), list) and len(summarized["ui_data"]) > 3:
            summarized["ui_data"] = summarized["ui_data"][:3]
            summarized["ui_data_total"] = len(r["ui_data"])
        summarized_results.append(summarized)

    user_content = (
        f"사용자 요청: {user_message}\n\n"
        f"도구 결과:\n{json.dumps(summarized_results, ensure_ascii=False, indent=2)}"
    )

    provider, model_name = resolve_llm_config(state)
    try:
        llm = make_chat_llm(provider=provider, model_name=model_name, temperature=0)
        response = llm.invoke(
            [
                SystemMessage(content=_UI_GENERATOR_SYSTEM_PROMPT),
                HumanMessage(content=user_content),
            ]
        )
        raw = response.content if hasattr(response, "content") else str(response)
        ui_metadata = _extract_json_object(raw)
        if not ui_metadata:
            raise ValueError("LLM이 유효한 JSON을 반환하지 않았습니다.")
        print(f"---UI GENERATOR: template={ui_metadata.get('template_type')}---")
    except Exception as e:
        print(f"---UI GENERATOR ERROR: {e}, using fallback---")
        # Fallback: Tool 결과의 ui_template을 그대로 사용
        first = tool_results_with_template[0]
        ui_metadata = {
            "template_type": first.get("ui_template", "order_list"),
            "message": first.get("message", ""),
            "template_config": {
                "enable_selection": first.get("requires_selection", False),
            },
        }

    return {"ui_metadata": ui_metadata}


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
        isinstance(task, dict)
        and str(task.get("task", "")).lower() in {"order_action", "order-action"}
        for task in task_results
    )


def process_output_node(state: AgentState):
    """
    최종 응답을 API 스펙에 맞게 가공합니다.
    (chat.py에서 참조하는 generation, ui_action, tool_outputs 등을 채움)

    두 가지 경로를 처리합니다:
    1. ui_metadata 있음 (ui_generator 경유): LLM이 동적으로 생성한 UI config + Tool 데이터를 조합
    2. ui_action 있음 (기존 방식): 주소검색/중고판매 폼 등 고정 UI trigger
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

    # 현재 턴 메시지 수집 (HumanMessage 이후부터)
    current_turn_messages: list = []
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            break
        current_turn_messages.append(msg)
    current_turn_messages = list(reversed(current_turn_messages))

    # ── 경로 1: LLM 동적 UI (ui_generator 경유) ──────────────
    ui_metadata = state.get("ui_metadata")
    if ui_metadata and isinstance(ui_metadata, dict) and ui_metadata.get("template_type"):
        # ui_template이 있는 ToolMessage에서 raw 데이터 수집
        all_ui_data: list = []
        for msg in current_turn_messages:
            if isinstance(msg, ToolMessage):
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and data.get("ui_template"):
                        if isinstance(data.get("ui_data"), list):
                            all_ui_data.extend(data["ui_data"])
                except Exception:
                    pass

        result["tool_outputs"] = [
            {
                "ui_action": ui_metadata["template_type"],   # 프론트가 읽는 키 통일
                "ui_template": ui_metadata["template_type"],
                "ui_config": ui_metadata.get("template_config", {}),
                "ui_data": all_ui_data,
                "message": ui_metadata.get("message", ""),
            }
        ]
        result["generation"] = ""

    else:
        # ── 경로 2: 고정 ui_action (주소검색, 중고판매 폼 등) ──────
        for msg in current_turn_messages:
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

        if result["tool_outputs"]:
            result["generation"] = ""

    if _should_reset_order_action_context(state):
        current_task = state.get("current_task")
        if isinstance(current_task, dict):
            completed_task = dict(current_task)
            completed_task["status"] = "completed"
            result["last_completed_task"] = completed_task
        result["current_task"] = None
        result["prior_action"] = None

    return result
