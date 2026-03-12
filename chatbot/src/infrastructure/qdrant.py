
from qdrant_client import QdrantClient
from ecommerce.chatbot.src.core.config import settings

class QdrantClientWrapper:
    _instance: QdrantClient | None = None

    @classmethod
    def get_client(cls) -> QdrantClient:
        if cls._instance is None:
            cls._instance = QdrantClient(
                url=settings.QDRANT_URL,
                api_key=settings.QDRANT_API_KEY,
            )
        return cls._instance

def get_qdrant_client() -> QdrantClient:
    return QdrantClientWrapper.get_client()
