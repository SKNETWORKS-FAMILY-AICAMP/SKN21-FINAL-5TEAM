"""Agent/Workflow 전용 프롬프트 모음."""

TOOL_USAGE_INSTRUCTIONS = """
\n[Tool Usage Instructions]
1. 사용자가 주문 조회, 환불, 배송 확인 등을 요청하면 주저하지 말고 즉시 관련 도구(Tool)를 호출하세요. "확인해보겠습니다"라고 말하기 전에 도구부터 호출하세요.
2. 도구 실행에 'user_id'가 필요한 경우, 위 [User Context]에 있는 User ID를 사용하세요.
3. 주문 번호가 문맥에 있다면 해당 주문 번호를 사용하세요.
4. 사용자가 특정 주문을 선택해야 하는 상황(예: "환불해줘"라고만 하고 주문번호를 안 줌)이라면, get_user_orders를 호출하되 `requires_selection=True` 파라미터를 꼭 설정하세요.
5. 이때, `action_context` 파라미터에 원래 의도('refund', 'exchange', 'cancel')를 반드시 포함하세요. (예: `action_context='refund'`)
6. [CRITICAL] 사용자로부터 '주소'(배송지, 수거지 등)를 입력받아야 할 경우, 절대로 텍스트로 "주소를 입력해주세요"라고 질문하지 마십시오. 대신 무조건 `open_address_search` 도구를 호출하여 주소 검색 팝업을 띄우십시오. 이는 필수 규칙입니다.
"""

CONTEXT_SUMMARY_SYSTEM_PROMPT = (
    "다음 고객상담 대화를 다음 턴에 필요한 사실/상태/의도 중심으로 5문장 이내로 요약하세요."
)

APPROVAL_CHECK_PROMPT_TEMPLATE = """User Message: '{user_message}'
Pending Tool Call: {tool_name} (Args: {tool_args})
System: The user was asked to confirm this action. \
Does the user's message imply confirmation/agreement to proceed? \
Or does it provide necessary information (slot filling) which implies proceeding? \
Answer 'YES' if they agree or provide info. \
Answer 'NO' if they refuse or ask something else. \
Answer only YES or NO."""
