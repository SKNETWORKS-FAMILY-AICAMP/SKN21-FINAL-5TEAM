from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import engine, Base
from app.router import user
from db import crud, models, schemas
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
    allow_origins=["*"],  # 필요 시 프론트 URL로 제한 가능
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
app.include_router(user.router, prefix="/users", tags=["Users"])


# ============================================
# 실행용 (개발용)
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)