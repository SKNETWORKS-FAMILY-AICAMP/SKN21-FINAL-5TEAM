
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
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o-mini"  # Default to 4o
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # Qdrant
    QDRANT_URL: str
    QDRANT_API_KEY: str
    
    # LangSmith
    LANGCHAIN_TRACING_V2: str
    LANGCHAIN_ENDPOINT: str
    LANGCHAIN_API_KEY: str
    LANGCHAIN_PROJECT: str
    
    # Backend API
    BACKEND_API_URL: str = "http://localhost:3000"
    
    # Collections
    COLLECTION_FASHION: str = "fashion_products"
    COLLECTION_FAQ: str = "musinsa_faq"
    COLLECTION_TERMS: str = "ecommerce_terms"
    
    # Chat History Optimization
    MAX_RECENT_MESSAGES: int = 5  # 최근 유지할 메시지 개수 (Sliding Window)
    MAX_TOTAL_MESSAGES: int = 10   # 전체 메시지 최대 개수

settings = Settings()
