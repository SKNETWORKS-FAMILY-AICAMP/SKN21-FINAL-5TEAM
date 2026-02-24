# 답변 생성을 위한 시스템 프롬프트 (Model/Provider 별)
# - 아래 두 상수만 수정하면 모델별 톤/규칙을 쉽게 관리할 수 있습니다.
OPENAI_ECOMMERCE_SYSTEM_PROMPT = """
당신은 MOYEO 쇼핑몰의 AI CS 상담원입니다.
절대 반말을 사용하지 마세요. 항상 존댓말로 답변하세요.
답변은 간결하고 구조적으로 작성하며, 필요한 정보만 정확히 전달하세요.
모르는 내용은 추측하지 말고 확인되지 않았다고 명확히 안내하세요.
"""

QWEN_ECOMMERCE_SYSTEM_PROMPT = """
당신은 MOYEO 쇼핑몰의 AI CS 상담원입니다.
절대 반말을 사용하지 마세요. 항상 존댓말로 답변하세요.
답변은 간결하고 구조적으로 작성하며, 필요한 정보만 정확히 전달하세요.
모르는 내용은 추측하지 말고 확인되지 않았다고 명확히 안내하세요.
"""


def get_ecommerce_system_prompt(provider: str | None = None, model_name: str | None = None) -> str:
   """
   Provider/Model 기준으로 기본 시스템 프롬프트를 선택합니다.
   우선순위:
   1) model_name에 'qwen' 포함 -> QWEN_ECOMMERCE_SYSTEM_PROMPT
   2) provider == 'openai' -> OPENAI_ECOMMERCE_SYSTEM_PROMPT
   3) provider == 'huggingface' -> QWEN_ECOMMERCE_SYSTEM_PROMPT (기본)
   4) fallback -> OPENAI_ECOMMERCE_SYSTEM_PROMPT
   """
   provider_norm = (provider or "").strip().lower()
   model_norm = (model_name or "").strip().lower()

   if "qwen" in model_norm:
      return QWEN_ECOMMERCE_SYSTEM_PROMPT
   if provider_norm == "openai":
      return OPENAI_ECOMMERCE_SYSTEM_PROMPT
   if provider_norm == "huggingface":
      return QWEN_ECOMMERCE_SYSTEM_PROMPT
   return OPENAI_ECOMMERCE_SYSTEM_PROMPT


# 하위 호환: 기존 참조는 OpenAI 기본 프롬프트를 사용
ECOMMERCE_SYSTEM_PROMPT = OPENAI_ECOMMERCE_SYSTEM_PROMPT
