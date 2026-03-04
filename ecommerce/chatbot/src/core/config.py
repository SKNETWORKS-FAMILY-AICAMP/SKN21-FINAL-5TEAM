from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
        env_file_encoding="utf-8",
    )

    # Project Info
    PROJECT_NAME: str = "Ecommerce Chatbot"
    API_V1_STR: str = "/api/v1"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5-mini"  # Default to 4o

    # vLLM (OpenAI-compatible endpoint; e.g., RunPod)
    VLLM_BASE_URL: str = ""
    VLLM_API_KEY: str = "EMPTY"
    VLLM_MODEL: str = "Qwen/Qwen3.5-35B-A3B"

    # Runtime LLM routing
    LLM_PROVIDER: str = "openai"  # openai | huggingface | vllm
    HF_MODEL_ID: str = "Qwen/Qwen3-0.6B"
    HF_QUANTIZATION: str = "auto"  # auto | none | bnb-4bit | bnb-8bit | dynamic-int8

    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024

    # Qdrant
    QDRANT_URL: str
    QDRANT_API_KEY: str

    # Langfuse (nodes_v3 observability)
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_BASE_URL: str = "https://us.cloud.langfuse.com"

    # Backend API
    BACKEND_API_URL: str = "http://localhost:3000"

    # Collections
    COLLECTION_FASHION: str = "fashion_products"
    COLLECTION_FAQ: str = "musinsa_faq"
    COLLECTION_TERMS: str = "ecommerce_terms"

    # Chat History Optimization
    MAX_RECENT_MESSAGES: int = 5  # 최근 유지할 메시지 개수 (Sliding Window)
    MAX_TOTAL_MESSAGES: int = 10  # 전체 메시지 최대 개수


settings = Settings()  # type: ignore[call-arg]
