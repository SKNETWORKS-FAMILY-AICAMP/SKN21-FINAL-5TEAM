from chatbot.src.graph.brand_profiles import resolve_brand_profile


_SYSTEM_PROMPT_TEMPLATE = """
당신은 {brand_store_label}의 AI CS 상담원입니다.
절대 반말을 사용하지 마세요. 항상 존댓말로 답변하세요.
답변은 간결하고 구조적으로 작성하며, 필요한 정보만 정확히 전달하세요.
모르는 내용은 추측하지 말고 확인되지 않았다고 명확히 안내하세요.
"""


def _render_ecommerce_system_prompt(site_id: str | None) -> str:
   brand_profile = resolve_brand_profile(site_id)
   return _SYSTEM_PROMPT_TEMPLATE.format(brand_store_label=brand_profile.store_label)


def get_ecommerce_system_prompt(
   provider: str | None = None,
   model_name: str | None = None,
   site_id: str | None = None,
) -> str:
   """
   Provider/Model 기준으로 기본 시스템 프롬프트를 선택합니다.
   우선순위:
   1) model_name에 'qwen' 포함 -> Qwen용 site-aware 프롬프트
   2) provider == 'openai' -> OpenAI용 site-aware 프롬프트
   3) provider == 'huggingface' -> HuggingFace용 site-aware 프롬프트
   4) fallback -> 기본 site-aware 프롬프트
   """
   provider_norm = (provider or "").strip().lower()
   model_norm = (model_name or "").strip().lower()
   prompt = _render_ecommerce_system_prompt(site_id)

   if "qwen" in model_norm:
      return prompt
   if provider_norm == "openai":
      return prompt
   if provider_norm == "huggingface":
      return prompt
   return prompt


# 하위 호환: 기존 참조는 OpenAI 기본 프롬프트를 사용
ECOMMERCE_SYSTEM_PROMPT = get_ecommerce_system_prompt(provider="openai")
