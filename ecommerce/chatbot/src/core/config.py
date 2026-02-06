
import os
from typing import Literal
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Get the project root directory (assuming .env is in the root: SKN21-FINAL-5TEAM)
# config.py is in ecommerce/chatbot/src/core/
# Path(__file__) = .../ecommerce/chatbot/src/core/config.py
# .parent = .../core
# .parent = .../src
# .parent = .../chatbot
# .parent = .../ecommerce
# .parent = .../SKN21-FINAL-5TEAM (Root)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent

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

settings = Settings()
