from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database import engine, Base
# from router.carts.router import router as carts_router
from router.shipping.router import router as shipping_router
import logging

# ============================================
# Lifespan 이벤트 (서버 시작/종료)
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시
    logging.info("서버 시작")
    Base.metadata.create_all(bind=engine)  # 테이블이 없다면 생성
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
    allow_origins=["http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

# app.include_router(carts_router, prefix="/carts", tags=["Carts"])
app.include_router(shipping_router, prefix="/shipping", tags=["Shipping"])


# ============================================
# 실행용 (개발용)
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)