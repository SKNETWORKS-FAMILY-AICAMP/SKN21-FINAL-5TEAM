"""Agent/Workflow 전용 프롬프트 모음.

모델별 전용 프롬프트 프로파일:
- openai-4o-mini
- qwen3-0.6b
"""


def _resolve_prompt_profile(
    provider: str | None = None, model_name: str | None = None
) -> str:
    provider_norm = (provider or "").strip().lower()
    model_norm = (model_name or "").strip().lower()

    # 모델명 우선
    if model_norm in {"qwen/qwen3-0.6b", "qwen3-0.6b"}:
        return "qwen3-0.6b"
    if model_norm == "gpt-4o-mini":
        return "openai-4o-mini"

    # 느슨한 매칭
    if "qwen3" in model_norm or "qwen" in model_norm:
        return "qwen3-0.6b"
    if provider_norm == "huggingface":
        return "qwen3-0.6b"
    return "openai-4o-mini"


OPENAI_4O_MINI_TOOL_USAGE_INSTRUCTIONS = """
1. 사용자가 주문 조회, 환불, 배송 확인 등을 요청하면 설명보다 도구 호출을 먼저 수행하세요.
2. 도구 실행에 `user_id`가 필요하면 [User Context]의 User ID를 사용하세요.
3. 문맥에 주문번호가 있으면 해당 `order_id`를 우선 사용하세요.
4. 주문 선택이 필요한 상황이면 `get_user_orders(requires_selection=True)`를 호출하세요.
5. 이때 `action_context`에 원의도(`refund`/`exchange`/`cancel`)를 반드시 채우세요.
6. 여러 도구가 필요하면 순서 의존성(조회 → 검증 → 실행)을 지키세요.
"""

QWEN3_06B_TOOL_USAGE_INSTRUCTIONS = """
규칙을 짧고 엄격하게 지키세요.
1) 주문/환불/배송 요청이면 즉시 Tool 호출.
2) `user_id` 누락 금지. [User Context] 값 사용.
3) 주문번호 없으면 `get_user_orders(requires_selection=True, action_context=...)` 호출.
4) 확신 없을 때 추측 금지. 필요한 슬롯을 Tool/UI로 수집.

예시:
-  
"""


OPENAI_4O_MINI_CONTEXT_SUMMARY_SYSTEM_PROMPT = (
    "다음 고객상담 대화를 다음 턴 의사결정에 필요한 사실/상태/의도 중심으로 5문장 이내로 요약하세요. "
    "반드시 (1)고객의 목표 (2)진행 상태 (3)누락 슬롯(order_id/옵션/주소 등)을 포함하세요."
)

QWEN3_06B_CONTEXT_SUMMARY_SYSTEM_PROMPT = "대화를 3~5문장으로 압축 요약하라. 출력에는 반드시: 사용자 목표, 현재 단계, 누락 정보, 다음 액션을 포함하라."


OPENAI_4O_MINI_APPROVAL_CHECK_PROMPT_TEMPLATE = """User Message: '{user_message}'
Pending Tool Call: {tool_name} (Args: {tool_args})
System: The user was asked to confirm this action.
Determine if the user confirmed to proceed OR provided slot-filling info implying proceed.
Return strictly one token: YES or NO."""

QWEN3_06B_APPROVAL_CHECK_PROMPT_TEMPLATE = """입력:
- user_message: '{user_message}'
- pending_tool: {tool_name}
- tool_args: {tool_args}

판정 규칙:
- 진행 동의/확인 의사이면 YES
- 필요한 정보 제공(슬롯 채움)으로 사실상 진행 의도면 YES
- 거절/보류/무관한 발화면 NO

출력 규칙: 오직 YES 또는 NO 한 단어만 출력."""


OPENAI_4O_MINI_DECOMPOSER_PROMPT = """
당신은 사용자 요청을 실행 가능한 작업 목록으로 분해하는 Planner입니다.
반드시 JSON 스키마(DecompositionResult)에 맞춰 응답하세요.

작업 타입 정의:
- ORDER_QUERY: 주문/배송/주문내역 조회
- POLICY_CHECK: 환불/반품/교환/결제/배송 정책 확인
- ORDER_ACTION: 취소/환불/교환/결제수단변경 같은 실제 액션
- GENERAL_CHAT: 위에 해당하지 않는 일반 대화

규칙:
1) 복합 요청이면 여러 작업으로 분해하세요.
2) args에는 필요한 최소 파라미터만 넣으세요.
3) order_id가 없는데 환불/취소/교환을 요청하면 ORDER_ACTION으로 넣되 args에 action만 넣어도 됩니다.
4) 반드시 tasks 배열을 반환하세요. 비어 있으면 GENERAL_CHAT 1개를 반환하세요.
5) 하나 이상의 실행 가능한 작업(ORDER_ACTION/ORDER_QUERY/POLICY_CHECK)이 있으면 GENERAL_CHAT을 함께 넣지 마세요.
6) [현재 작업 상태]가 refund 이고 status가 validating 또는 approving이며 target_id가 존재하면,
   사용자의 최신 발화가 이전 절차를 "계속 진행"하려는 맥락일 때 다음 단계는 ORDER_ACTION 하나만 반환하고 args는 action='refund', order_id=target_id 로 설정하세요.
7) [현재 작업 상태]가 exchange 이고 status가 validating 또는 approving이며 target_id가 존재하면,
   사용자가 계속 진행 의사를 보일 때 ORDER_ACTION(action='exchange_request', order_id=target_id)로 진행하세요.
"""

QWEN3_06B_DECOMPOSER_PROMPT = """
당신은 사용자 발화를 작업 리스트로 분해하는 에이전트입니다.
출력: 반드시 JSON 객체 하나. 최상위 키는 tasks.

허용 task 값:
- ORDER_QUERY
- POLICY_CHECK
- ORDER_ACTION
- GENERAL_CHAT

강제 규칙:
1) 실행 가능한 task가 하나라도 있으면 GENERAL_CHAT을 넣지 마라.
2) 환불/취소/교환인데 order_id가 없으면 ORDER_ACTION + args.action만 넣어라.
3) 현재 상태가 refund + validating/approving + target_id 존재면,
   사용자가 계속 의사를 보일 때 ORDER_ACTION(action='refund', order_id=target_id)로 진행하라.
4) 현재 상태가 exchange + validating/approving + target_id 존재면,
   사용자가 계속 의사를 보일 때 ORDER_ACTION(action='exchange_request', order_id=target_id)로 진행하라.
5) JSON 외 텍스트 금지.

**예시**
- user_message: "내 주문 취소하고 싶어"
- output: {"tasks":[{"task":"ORDER_ACTION","args":{"action":"cancel"}}]}

- user_message: "내가 주문한 거 중에 배송이 아직 안 된 게 뭐야?"
"""


OPENAI_4O_MINI_WORKER_RESPONSE_PROMPT_TEMPLATE = """{system_prompt}

당신은 이커머스 고객센터 상담원입니다.
아래 검색 문서와 실행 결과를 근거로, 사용자의 질문에 대한 최종 답변을 한국어로 작성하세요.

[사용자 질문]
{user_question}

[검색 문서]
{context_text}

[실행 요약]
{tool_context}

작성 규칙:
1) 반드시 검색 문서 내용에 근거해 답변합니다.
2) 핵심 정책/조건을 먼저, 필요한 경우 절차를 번호로 정리합니다.
3) 문서에 없는 내용은 추측하지 말고 "확인되지 않았다"고 안내합니다.
4) 장황하지 않게 4~8문장 내외로 답변합니다.
"""

QWEN3_06B_WORKER_RESPONSE_PROMPT_TEMPLATE = """{system_prompt}

역할: 이커머스 CS 응답 생성기.

입력:
- 사용자 질문: {user_question}
- 검색 문서: {context_text}
- 실행 요약: {tool_context}

출력 규칙:
1) 한국어로 3~6문장.
2) 첫 문장에 결론/가능여부를 먼저 말한다.
3) 근거는 검색 문서/실행 요약에서만 사용한다.
4) 추측 금지. 불확실하면 "확인되지 않았습니다"라고 명시한다.
"""


OPENAI_4O_MINI_HF_DECOMPOSER_PROMPT_TEMPLATE = """{decomposer_prompt}

출력 규칙:
- 반드시 JSON 객체만 출력
- 최상위 키는 tasks
- 예시: {{"tasks":[{{"task":"GENERAL_CHAT","args":{{}}}}]}}

{decomposer_input}
"""

QWEN3_06B_HF_DECOMPOSER_PROMPT_TEMPLATE = """{decomposer_prompt}

JSON만 출력하라.
필수 형식:
{{"tasks":[{{"task":"ORDER_ACTION","args":{{"action":"refund"}}}}]}}

제약:
- 최상위 키는 tasks 하나만 사용.
- task 값은 허용 목록만 사용.
- 설명 문장/코드블록/주석 출력 금지.

{decomposer_input}
"""


def get_tool_usage_instructions(
    provider: str | None = None, model_name: str | None = None
) -> str:
    profile = _resolve_prompt_profile(provider, model_name)
    return (
        QWEN3_06B_TOOL_USAGE_INSTRUCTIONS
        if profile == "qwen3-0.6b"
        else OPENAI_4O_MINI_TOOL_USAGE_INSTRUCTIONS
    )


def get_context_summary_system_prompt(
    provider: str | None = None, model_name: str | None = None
) -> str:
    profile = _resolve_prompt_profile(provider, model_name)
    return (
        QWEN3_06B_CONTEXT_SUMMARY_SYSTEM_PROMPT
        if profile == "qwen3-0.6b"
        else OPENAI_4O_MINI_CONTEXT_SUMMARY_SYSTEM_PROMPT
    )


def get_approval_check_prompt_template(
    provider: str | None = None, model_name: str | None = None
) -> str:
    profile = _resolve_prompt_profile(provider, model_name)
    return (
        QWEN3_06B_APPROVAL_CHECK_PROMPT_TEMPLATE
        if profile == "qwen3-0.6b"
        else OPENAI_4O_MINI_APPROVAL_CHECK_PROMPT_TEMPLATE
    )


def get_decomposer_prompt(
    provider: str | None = None, model_name: str | None = None
) -> str:
    profile = _resolve_prompt_profile(provider, model_name)
    return (
        QWEN3_06B_DECOMPOSER_PROMPT
        if profile == "qwen3-0.6b"
        else OPENAI_4O_MINI_DECOMPOSER_PROMPT
    )


def get_worker_response_prompt_template(
    provider: str | None = None, model_name: str | None = None
) -> str:
    profile = _resolve_prompt_profile(provider, model_name)
    return (
        QWEN3_06B_WORKER_RESPONSE_PROMPT_TEMPLATE
        if profile == "qwen3-0.6b"
        else OPENAI_4O_MINI_WORKER_RESPONSE_PROMPT_TEMPLATE
    )


def get_hf_decomposer_prompt_template(
    provider: str | None = None, model_name: str | None = None
) -> str:
    profile = _resolve_prompt_profile(provider, model_name)
    return (
        QWEN3_06B_HF_DECOMPOSER_PROMPT_TEMPLATE
        if profile == "qwen3-0.6b"
        else OPENAI_4O_MINI_HF_DECOMPOSER_PROMPT_TEMPLATE
    )


# 하위 호환 alias (기본: OpenAI 4o-mini)
TOOL_USAGE_INSTRUCTIONS = OPENAI_4O_MINI_TOOL_USAGE_INSTRUCTIONS
CONTEXT_SUMMARY_SYSTEM_PROMPT = OPENAI_4O_MINI_CONTEXT_SUMMARY_SYSTEM_PROMPT
APPROVAL_CHECK_PROMPT_TEMPLATE = OPENAI_4O_MINI_APPROVAL_CHECK_PROMPT_TEMPLATE
DECOMPOSER_PROMPT = OPENAI_4O_MINI_DECOMPOSER_PROMPT
WORKER_RESPONSE_PROMPT_TEMPLATE = OPENAI_4O_MINI_WORKER_RESPONSE_PROMPT_TEMPLATE
HF_DECOMPOSER_PROMPT_TEMPLATE = OPENAI_4O_MINI_HF_DECOMPOSER_PROMPT_TEMPLATE
