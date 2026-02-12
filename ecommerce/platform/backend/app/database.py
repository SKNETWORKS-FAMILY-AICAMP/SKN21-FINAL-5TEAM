import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from pathlib import Path

# .env 파일 로드
# 현재 파일: .../ecommerce/platform/backend/app/database.py
# Root: .../SKN21-FINAL-5TEAM (.env 위치)
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME")

# MySQL 접속 URL
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# DB 스키마 생성 함수 (서버 시작 시 호출)
from sqlalchemy import text
def create_db_scheme():
    """
    DB 스키마(데이터베이스)가 없으면 생성
    """
    # DB명을 제외한 Root URL
    root_url = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}"
    
    # CREATE DATABASE는 트랜잭션 안에서 실행 불가하므로 AUTOCOMMIT 설정
    root_engine = create_engine(root_url, isolation_level="AUTOCOMMIT")
    
    try:
        with root_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            # print(f"✅ Database '{DB_NAME}' checked/created.")
    except Exception as e:
        print(f"⚠️  Database creation check failed: {e}")
    finally:
        root_engine.dispose()


# SQLAlchemy Engine 생성
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # 연결 유지 체크
)

# 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base 클래스 생성 (모델들이 상속할 클래스)
Base = declarative_base()

# Dependency 함수 (FastAPI에서 사용할 수 있게)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
