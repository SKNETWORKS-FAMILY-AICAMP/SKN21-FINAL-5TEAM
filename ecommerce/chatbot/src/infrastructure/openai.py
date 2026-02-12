
from openai import OpenAI
from ecommerce.chatbot.src.core.config import settings

class OpenAIClientWrapper:
    _instance: OpenAI | None = None

    @classmethod
    def get_client(cls) -> OpenAI:
        if cls._instance is None:
            cls._instance = OpenAI(
                api_key=settings.OPENAI_API_KEY,
                max_retries=2,
                timeout=30.0
            )
        return cls._instance

def get_openai_client() -> OpenAI:
    return OpenAIClientWrapper.get_client()
