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

from ecommerce.platform.backend.app.database import engine, Base

# 모든 모델을 import해야 Base.metadata에 등록되어 삭제/생성이 가능합니다.
import ecommerce.platform.backend.app.router.users.models
import ecommerce.platform.backend.app.router.products.models
import ecommerce.platform.backend.app.router.carts.models
import ecommerce.platform.backend.app.router.orders.models
import ecommerce.platform.backend.app.router.shipping.models
import ecommerce.platform.backend.app.router.payments.models
import ecommerce.platform.backend.app.router.points.models
import ecommerce.platform.backend.app.router.reviews.models
import ecommerce.platform.backend.app.router.inventories.models

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_db():
    try:
        logger.info("🗑️  기존 테이블 삭제 중...")
        # 모든 테이블 삭제 (CASCADE로 연관된 테이블도 삭제됨)
        Base.metadata.drop_all(bind=engine)
        logger.info("✅ 테이블 삭제 완료.")
        
        logger.info("🆕 테이블 재생성 중...")
        # 모든 테이블 재생성
        Base.metadata.create_all(bind=engine)
        logger.info("✅ 테이블 재생성 완료.")
        
    except Exception as e:
        logger.error(f"❌ DB 초기화 실패: {e}")
        raise e

if __name__ == "__main__":
    # 자동 실행을 위해 입력 확인 제거하고 바로 실행 (또는 인자로 제어 가능)
    # 여기서는 스크립트 실행 시 바로 초기화하도록 함
    reset_db()
