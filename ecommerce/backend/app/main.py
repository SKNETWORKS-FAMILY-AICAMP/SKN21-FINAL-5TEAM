from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import time
from ecommerce.backend.app.database import engine, Base, create_db_scheme
from sqlalchemy import inspect, text
from ecommerce.backend.app.router.carts.router import router as carts_router
from ecommerce.backend.app.router.users.router import router as users_router
from ecommerce.backend.app.router.shipping.router import (
    router as shipping_router,
)
from ecommerce.backend.app.router.orders.router import router as orders_router
from ecommerce.backend.app.router.payments.router import (
    router as payments_router,
)
from ecommerce.backend.app.router.inventories.router import (
    router as inventories_router,
)
from ecommerce.backend.app.router.points.router import router as points_router
from ecommerce.backend.app.router.reviews.router import (
    router as reviews_router,
)
from ecommerce.backend.app.router.products.router import (
    router as products_router,
)
from ecommerce.backend.app.router.user_history.router import (
    router as user_history_router,
)

# Import models to register them with Base.metadata
import ecommerce.backend.app.router.users.models
import ecommerce.backend.app.router.user_history.models
import logging
from chatbot.src.api.v1.endpoints.chat import router as chatbot_router
from ecommerce.backend.app.uploads import CHATBOT_UPLOAD_DIR
from starlette.middleware.sessions import SessionMiddleware  # 미드웨워 추가


def _get_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _should_preload_heavy_models_once_per_reload_session() -> bool:
    """
    모델 프리로드는 워커 프로세스 시작 시마다 수행합니다.
    프로세스 메모리에 적재되는 모델 특성상 reload 후 새 워커에서는 재로드가 필요합니다.
    """
    return _get_env_bool("PRELOAD_HEAVY_MODELS", True)


# ============================================
# 자동 컬럼 마이그레이션
# ============================================
def auto_add_missing_columns():
    """
    테이블은 있지만 컬럼이 없을 때 자동으로 컬럼 추가
    SQLAlchemy 모델과 실제 DB를 비교하여 누락된 컬럼을 추가합니다.
    """
    inspector = inspect(engine)
    pending_sqls: list[str] = []
    total_missing = 0

    try:
        # Base.metadata에 등록된 모든 테이블 순회
        for table_name, table in Base.metadata.tables.items():
            # 테이블이 DB에 존재하는지 확인
            if not inspector.has_table(table_name):
                continue

            # 실제 DB의 컬럼 목록
            existing_columns = {
                col["name"] for col in inspector.get_columns(table_name)
            }

            # 모델에 정의된 컬럼 목록
            model_columns = {col.name: col for col in table.columns}

            # 누락된 컬럼 찾기
            missing_columns = set(model_columns.keys()) - existing_columns

            if missing_columns:
                for col_name in missing_columns:
                    col = model_columns[col_name]

                    # 컬럼 타입 결정
                    col_type = str(col.type.compile(dialect=engine.dialect))

                    # NULL 여부
                    nullable = "NULL" if col.nullable else "NOT NULL"

                    # 기본값 처리
                    default_clause = ""
                    if col.default is not None:
                        if hasattr(col.default, "arg"):
                            # scalar default
                            default_value = col.default.arg
                            if isinstance(default_value, str):
                                default_clause = f"DEFAULT '{default_value}'"
                            elif isinstance(default_value, bool):
                                default_clause = f"DEFAULT {1 if default_value else 0}"
                            else:
                                default_clause = f"DEFAULT {default_value}"

                    # ALTER TABLE 문 생성
                    alter_sql = f"""
                        ALTER TABLE {table_name}
                        ADD COLUMN {col_name} {col_type} {nullable} {default_clause}
                    """

                    pending_sqls.append(alter_sql)
                    total_missing += 1

        if not pending_sqls:
            logging.info("누락 컬럼 없음: 자동 컬럼 마이그레이션 스킵")
            return

        with engine.begin() as conn:
            for alter_sql in pending_sqls:
                conn.execute(text(alter_sql))

        logging.info(f"자동 컬럼 마이그레이션 완료: {total_missing}개 컬럼 추가")

    except Exception:
        logging.exception("자동 컬럼 마이그레이션 실패")


# ============================================
# Lifespan 이벤트 (서버 시작/종료)
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 시작 시
    logging.info("서버 시작")
    startup_t0 = time.perf_counter()

    # 0. DB 스키마 생성(없을 시)
    step_t0 = time.perf_counter()
    create_db_scheme()
    logging.info(f"[startup] DB 스키마 확인 완료: {time.perf_counter() - step_t0:.2f}s")

    # 1. 테이블 생성
    step_t0 = time.perf_counter()
    Base.metadata.create_all(bind=engine)  # 테이블이 없다면 생성
    logging.info(f"[startup] 테이블 생성 완료: {time.perf_counter() - step_t0:.2f}s")

    # 2. 누락된 컬럼 자동 추가
    step_t0 = time.perf_counter()
    auto_add_missing_columns()
    logging.info(f"[startup] 컬럼 마이그레이션 완료: {time.perf_counter() - step_t0:.2f}s")

    # 3. 초기 데이터 적재 (Seed)
    from ecommerce.backend.app.database import SessionLocal
    from ecommerce.scripts.seed import init_db

    db = SessionLocal()
    try:
        step_t0 = time.perf_counter()
        init_db(db)
        logging.info(f"[startup] 초기 데이터 적재 완료: {time.perf_counter() - step_t0:.2f}s")
    finally:
        db.close()

    if _should_preload_heavy_models_once_per_reload_session():
        # 4. 챗봇 리트리버 모델 미리 로드 (Pre-loading)
        try:
            from chatbot.src.tools.retrieval_tools import ensure_retrieval_models

            step_t0 = time.perf_counter()
            ensure_retrieval_models()
            logging.info(f"챗봇 리트리버 모델 로딩 완료: {time.perf_counter() - step_t0:.2f}s")
        except Exception as e:
            logging.error(f"챗봇 모델 로딩 실패: {e}")

        # 5. Guardrail 모델 미리 로드 (prismdata/guardrail-ko-11class)
        try:
            from chatbot.src.graph.nodes.guardrail import load_guardrail_model

            step_t0 = time.perf_counter()
            load_guardrail_model()
            logging.info(f"Guardrail 모델 로딩 완료: {time.perf_counter() - step_t0:.2f}s")
        except Exception as e:
            logging.error(f"Guardrail 모델 로딩 실패: {e}")

        # 6. BGE-M3 임베딩 모델 미리 로드 (BAAI/bge-m3)
        try:
            from chatbot.src.data_preprocessing.bge_m3_embedding import preload_model as preload_bge_m3

            step_t0 = time.perf_counter()
            preload_bge_m3()
            logging.info(f"BGE-M3 임베딩 모델 로딩 완료: {time.perf_counter() - step_t0:.2f}s")
        except Exception as e:
            logging.error(f"BGE-M3 모델 로딩 실패: {e}")

        # 7. KoBART 대화 요약 모델 미리 로드 (EbanLee/kobart-summary-v3)
        try:
            from chatbot.src.infrastructure.kobart_summarizer import preload_model as preload_kobart

            step_t0 = time.perf_counter()
            preload_kobart()
            logging.info(f"KoBART 요약 모델 로딩 완료: {time.perf_counter() - step_t0:.2f}s")
        except Exception as e:
            logging.error(f"KoBART 모델 로딩 실패: {e}")

        # 8. CLIP 검색 모델 미리 로드 (openai/clip-vit-base-patch32)
        try:
            from chatbot.src.tools.image_search_tools import preload_clip_resources

            step_t0 = time.perf_counter()
            preload_clip_resources()
            logging.info(f"CLIP 검색 모델 로딩 완료: {time.perf_counter() - step_t0:.2f}s")
        except Exception as e:
            logging.error(f"CLIP 모델 로딩 실패: {e}")
    else:
        logging.info("모델 프리로드 스킵: 같은 uvicorn reload 세션에서 이미 1회 수행됨")

    logging.info(f"[startup] 전체 초기화 완료: {time.perf_counter() - startup_t0:.2f}s")

    yield
    # 서버 종료 시
    logging.info("서버 종료")


# ============================================
# FastAPI 앱 생성
# ============================================
app = FastAPI(
    title="E-commerce Platform",
    lifespan=lifespan,  # Lifespan 이벤트 적용
)

# Chatbot uploads 공개 폴더
app.mount("/uploads/chatbot", StaticFiles(directory=CHATBOT_UPLOAD_DIR), name="chatbot_uploads")

# ============================================
# CORS 설정 (프론트엔드와 통신 허용)
# ============================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.0.30:3000",
        "http://192.168.0.90:3000",
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
app.include_router(inventories_router, prefix="/inventories", tags=["Inventories"])
app.include_router(points_router, prefix="/points", tags=["Points"])
app.include_router(reviews_router, prefix="/reviews", tags=["Reviews"])
app.include_router(products_router, prefix="/products", tags=["Products"])
app.include_router(user_history_router, prefix="/user-history", tags=["UserHistory"])
app.include_router(chatbot_router, prefix="/api/v1/chat", tags=["Chatbot"])


# ============================================
# 실행용 (개발용)
# ============================================
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("UVICORN_HOST", "0.0.0.0")
    port = int(os.getenv("UVICORN_PORT", "8000"))
    reload_enabled = _get_env_bool("UVICORN_RELOAD", False)
    workers = int(os.getenv("UVICORN_WORKERS", "4"))

    # Uvicorn requires single worker when reload is enabled.
    if reload_enabled and workers != 1:
        logging.warning("UVICORN_RELOAD=true enforces single worker; overriding UVICORN_WORKERS to 1")
        workers = 1

    uvicorn.run(
        "ecommerce.backend.app.main:app",
        host=host,
        port=port,
        reload=reload_enabled,
        workers=workers,
    )
