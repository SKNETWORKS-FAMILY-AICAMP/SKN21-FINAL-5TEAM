"""
Database Reset Script
데이터베이스를 초기화(모든 테이블 삭제 후 재생성)하는 스크립트입니다.
"""
import logging
import sys
import os
from pathlib import Path

# 프로젝트 루트 디렉토리를 sys.path에 추가 (ecommerce 패키지 인식을 위해)
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from ecommerce.backend.app.database import engine, Base

# 중앙 집중식 모델 import (모든 모델을 자동으로 로드)
from ecommerce.backend.app import init_models

# 모든 모델 로드
init_models()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_db():
    try:
        logger.info("🗑️  기존 테이블 삭제 중...")
        from sqlalchemy import text
        # 0. 외래 키 제약 조건 비활성화
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        
        # 1. 모든 테이블 삭제
        Base.metadata.drop_all(bind=engine)
        logger.info("✅ 테이블 삭제 완료.")
        
        # 2. 모든 테이블 재생성
        logger.info("🆕 테이블 재생성 중...")
        Base.metadata.create_all(bind=engine)
        
        # 3. 외래 키 제약 조건 활성화
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            
        logger.info("✅ 테이블 재생성 완료.")
        
    except Exception as e:
        logger.error(f"❌ DB 초기화 실패: {e}")
        raise e

if __name__ == "__main__":
    # 자동 실행을 위해 입력 확인 제거하고 바로 실행 (또는 인자로 제어 가능)
    # 여기서는 스크립트 실행 시 바로 초기화하도록 함
    reset_db()
