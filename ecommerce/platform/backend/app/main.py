from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from ecommerce.platform.backend.app.database import engine, Base, create_db_scheme
from ecommerce.platform.backend.app.router.carts.router import router as carts_router
from ecommerce.platform.backend.app.router.users.router import router as users_router
from ecommerce.platform.backend.app.router.shipping.router import router as shipping_router
from ecommerce.platform.backend.app.router.orders.router import router as orders_router
from ecommerce.platform.backend.app.router.payments.router import router as payments_router
from ecommerce.platform.backend.app.router.inventories.router import router as inventories_router
from ecommerce.platform.backend.app.router.points.router import router as points_router
from ecommerce.platform.backend.app.router.reviews.router import router as reviews_router
from ecommerce.platform.backend.app.router.products.router import router as products_router

# Import models to register them with Base.metadata
import ecommerce.platform.backend.app.router.users.models
import logging
import os
from ecommerce.chatbot.src.core.config import settings
from ecommerce.chatbot.src.api.v1.endpoints.chat import router as chatbot_router
from starlette.middleware.sessions import SessionMiddleware # 미드웨워 추가


# ============================================
# Lifespan 이벤트 (서버 시작/종료)
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # LangSmith 환경 변수 설정 (Chatbot)
    os.environ["LANGCHAIN_TRACING_V2"] = settings.LANGCHAIN_TRACING_V2
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    logging.info(f"🔗 LangSmith tracing enabled for project: {settings.LANGCHAIN_PROJECT}")

    # 서버 시작 시
    logging.info("서버 시작")
    
    # 0. DB 스키마 생성(없을 시)
    create_db_scheme()

    # 1. 테이블 생성
    Base.metadata.create_all(bind=engine)  # 테이블이 없다면 생성
    
    # 초기 데이터 적재 (Seed)
    from ecommerce.platform.backend.app.database import SessionLocal
    from ecommerce.scripts.seed import init_db
    
    db = SessionLocal()
    try:
        init_db(db)
    finally:
        db.close()
        
    yield
    # 서버 종료 시
    logging.info("서버 종료")

# ============================================
# FastAPI 앱 생성
# ============================================
app = FastAPI(
    title="E-commerce Platform",
    lifespan=lifespan  # Lifespan 이벤트 적용
)

# ============================================
# CORS 설정 (프론트엔드와 통신 허용)
# ============================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.0.30:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# 세션 미들웨어 설정 (Chatbot)
# ============================================
app.add_middleware(
    SessionMiddleware,
    secret_key="dev-secret-key",  # 나중에 환경변수로
    same_site="lax",
    https_only=False,  # 로컬 개발이므로 False
)

# ============================================
# 헬스체크
# ============================================
@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "message": "서버가 정상적으로 실행 중입니다!"}

# ============================================
# 라우터 등록
# ============================================

app.include_router(carts_router, prefix="/carts", tags=["Carts"])
app.include_router(users_router, prefix="/users", tags=["Users"])
app.include_router(shipping_router, prefix="/shipping", tags=["Shipping"])
app.include_router(orders_router, prefix="/orders", tags=["Orders"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(payments_router, prefix="/inventories", tags=["Inventories"])
app.include_router(payments_router, prefix="/points", tags=["Points"])
app.include_router(payments_router, prefix="/reviews", tags=["Reviews"])
app.include_router(payments_router, prefix="/products", tags=["Products"])
app.include_router(chatbot_router, prefix="/api/v1/chat", tags=["Chatbot"])


# ============================================
# 실행용 (개발용)
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ecommerce.platform.backend.app.main:app", host="0.0.0.0", port=8000, reload=True)