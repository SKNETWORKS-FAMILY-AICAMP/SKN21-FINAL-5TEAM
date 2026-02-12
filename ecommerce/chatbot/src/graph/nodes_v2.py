import json
from typing import List, Literal

from langchain_core.messages import ToolMessage, AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode
from langsmith import traceable

from ecommerce.chatbot.src.graph.state import AgentState
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.prompts.system_prompts import ECOMMERCE_SYSTEM_PROMPT

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
    open_address_search
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
    register_gift_card,
    search_knowledge_base,
    open_address_search
]

# Initialize ToolNode -> workflow.py로 이동
tool_node = ToolNode(TOOLS)

@traceable(run_type="chain", name="Agent Node (Tool Calling)")
def agent_node(state: AgentState):
    """
    LLM이 대화 히스토리와 도구 목록을 보고 답변하거나 도구를 호출합니다.
    """
    print("---AGENT NODE---")
    
    # 1. 메시지 준비
    messages = state["messages"]
    
    # 2. 시스템 프롬프트 준비
    # 매 턴마다 시스템 프롬프트를 컨텍스트로 주입 (state에 저장하지 않음)
    user_context = ""
    if state.get("user_info"):
            user_context += f"User Info: {json.dumps(state['user_info'], ensure_ascii=False)}\n"
    
    # [Context Injection] Prior Action (이전 의도 주입)
    if state.get("prior_action"):
        user_context += f"\n[Prior Context]\nUser was trying to perform action: '{state['prior_action']}'.\nIf the user selects an order, proceed with this action.\n"

    tool_instructions = """
\n[Tool Usage Instructions]
1. 사용자가 주문 조회, 환불, 배송 확인 등을 요청하면 주저하지 말고 즉시 관련 도구(Tool)를 호출하세요. "확인해보겠습니다"라고 말하기 전에 도구부터 호출하세요.
2. 도구 실행에 'user_id'가 필요한 경우, 위 [User Context]에 있는 User ID를 사용하세요.
3. 주문 번호가 문맥에 있다면 해당 주문 번호를 사용하세요.
4. 사용자가 특정 주문을 선택해야 하는 상황(예: "환불해줘"라고만 하고 주문번호를 안 줌)이라면, get_user_orders를 호출하되 `requires_selection=True` 파라미터를 꼭 설정하세요.
5. 이때, `action_context` 파라미터에 원래 의도('refund', 'exchange', 'cancel')를 반드시 포함하세요. (예: `action_context='refund'`)
6. [CRITICAL] 사용자로부터 '주소'(배송지, 수거지 등)를 입력받아야 할 경우, 절대로 텍스트로 "주소를 입력해주세요"라고 질문하지 마십시오. 대신 무조건 `open_address_search` 도구를 호출하여 주소 검색 팝업을 띄우십시오. 이는 필수 규칙입니다.
    """

    final_prompt = ECOMMERCE_SYSTEM_PROMPT + user_context + tool_instructions
    system_msg = SystemMessage(content=final_prompt)
    
    # 3. LLM 설정 (ChatOpenAI 사용 권장 for bind_tools)
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY
    )
    
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
    if current_task and current_task.get("status") == "approved":
        return "tools"

    # 민감한 도구가 있는지 확인 (Human Approval 필요 여부)
    for tool_call in last_message.tool_calls:
        if tool_call["name"] in SENSITIVE_TOOLS:
            return "human_approval"
            
    return "tools"


# Sensitive Tools requiring Human Approval
SENSITIVE_TOOLS = [
    "cancel_order", 
    "register_return_request", 
    "register_exchange_request", 
    "update_payment_method"
]

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
        if tool_name in ["check_refund_eligibility", "cancel_order", "register_return_request", "register_exchange_request"]:
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
                if tool_name == "cancel_order": task_type = "cancel"
                elif tool_name == "register_exchange_request": task_type = "exchange"
                else: task_type = "refund" # check_refund_eligibility, register_return_request 등
                
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
    if current_task and current_task.get("status") == "approved":
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
        content = last_user_msg.content.strip() if last_user_msg.content else ""
        print(f"---APPROVAL CHECK: Last User Msg='{content}'---")
        
        # A. LLM 기반 승인 여부 판단 (LLM-based Confirmation Check)
        try:
            # 빠른 응답을 위해 3.5-turbo 등 가벼운 모델 사용 권장 (여기서는 기본 설정 따름)
            approval_llm = ChatOpenAI(temperature=0, model="gpt-4o-mini") 
            
            prompt = (
                f"User Message: '{content}'\n"
                f"Pending Tool Call: {sensitive_calls[0]['name']} (Args: {sensitive_calls[0].get('args')})\n"
                "System: The user was asked to confirm this action. "
                "Does the user's message imply confirmation/agreement to proceed? "
                "Or does it provide necessary information (slot filling) which implies proceeding? "
                "Answer 'YES' if they agree or provide info. "
                "Answer 'NO' if they refuse or ask something else. "
                "Answer only YES or NO."
            )
            
            response = approval_llm.invoke([HumanMessage(content=prompt)])
            decision = response.content.strip().upper()
            print(f"---APPROVAL LLM DECISION: {decision} ({content})---")
            
            if "YES" in decision:
                if current_task: current_task["status"] = "approved"
                return {"current_task": current_task}
                
        except Exception as e:
            print(f"---APPROVAL LLM ERROR: {e}---")
            # Fallback to keyword matching if LLM fails
            positive_keywords = ["응", "네", "예", "맞아", "진행", "해줘", "yes", "ok", "confirm", "좋아", "수락"]
            if any(keyword in content.lower() for keyword in positive_keywords):
                print(f"---APPROVAL: Detected positive keyword (Fallback)---")
                if current_task: current_task["status"] = "approved"
                return {"current_task": current_task}
            
        # B. 인자 매칭 (Implicit Confirmation via Slot Filling)
        # 툴 호출 인자값(예: 주소)이 사용자 메시지에 포함되어 있다면, 
        # 사용자가 해당 정보를 제공하며 진행을 의도한 것으로 간주
        try:
            tool_args = sensitive_calls[0].get("args", {})
            for key, value in tool_args.items():
                if isinstance(value, str) and len(value) > 1 and value in content:
                    # 예: arg="경기도", content="경기도로 보내줘" -> 매칭
                    print(f"---APPROVAL: Detected argument match ('{value}') in user message---")
                    if current_task: current_task["status"] = "approved"
                    return {"current_task": current_task}
        except Exception as e:
            print(f"---APPROVAL CHECK ERROR: {e}---")

    # 2. state에 pending_approval 상태가 있을 때 (이전 턴에서 시스템이 물어본 경우)
    if current_task and current_task.get("status") == "approving":
         # 위 로직에서 걸러지지 않았더라도, pending 상태에서 다시 왔다면 승인으로 간주
         pass
         current_task["status"] = "approved"
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
    current_task["status"] = "approved"
    return {"current_task": current_task}


def route_after_approval(state: AgentState) -> Literal["tools", "process_output"]:
    """
    승인 노드 이후의 경로를 결정합니다.
    - approved: 도구 실행 (tools)
    - pending_approval: 사용자 입력 대기 (process_output -> end)
    """
    current_task = state.get("current_task")
    status = current_task.get("status") if current_task else "idle"
    print(f"---ROUTE AFTER APPROVAL: {status}---")
    
    if status == "approved":
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
    
    # UI Action 추출 (최근 ToolMessage 검색)
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            try:
                content = msg.content
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
