# uv run uvicorn ecommerce.chatbot.src.api.main:app --reload
import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.api.v1.endpoints import chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic: LangSmith 환경 변수 설정
    os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    print(f"🔗 LangSmith tracing enabled for project: {settings.LANGCHAIN_PROJECT}")
    yield
    # Shutdown logic

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Include Routers
app.include_router(chat.router, prefix=f"{settings.API_V1_STR}/chat", tags=["chat"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
