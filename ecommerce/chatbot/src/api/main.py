# uv run uvicorn ecommerce.chatbot.src.api.main:app --reload
from fastapi import FastAPI
from contextlib import asynccontextmanager
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.api.v1.endpoints import chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic (e.g. initialize DB connections)
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
