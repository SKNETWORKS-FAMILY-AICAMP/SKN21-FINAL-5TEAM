
import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore"
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
    QDRANT_URL: str = "https://75daa0f4-de48-4954-857a-1fbc276e298f.us-east4-0.gcp.cloud.qdrant.io"
    QDRANT_API_KEY: str | None = None
    
    # Collections
    COLLECTION_FASHION: str = "fashion_products"
    COLLECTION_FAQ: str = "musinsa_faq"
    COLLECTION_TERMS: str = "ecommerce_terms"

settings = Settings()
