import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 1. 테스트용 DB 환경 변수 설정 (가장 먼저 실행되어야 함)
os.environ["DB_NAME"] = "test_ecommerce"
os.environ["DB_HOST"] = "127.0.0.1" # 로컬 호스트 기준
os.environ["DB_PORT"] = "3307" # docker-compose에 노출된 포트 사용
os.environ["DB_USER"] = "ecom_user"
os.environ["DB_PASSWORD"] = "ecopchatbot!"

from ecommerce.backend.app.database import DATABASE_URL, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
from ecommerce.backend.app.database import Base
# 명시적으로 모델을 임포트하여 Base.metadata에 등록되도록 함
from ecommerce.backend.app.models import User, Order, OrderItem, ShippingInfo, Product, ProductOption, UsedProductOption
from ecommerce.backend.app.router.inventories.models import InventoryTransaction
from ecommerce.backend.app.router.shipping.models import ShippingAddress

# 테스트용 DB 생성 및 연결
def _create_test_db():
    root_user = "root"
    root_password = "root1234"
    root_url = f"mysql+pymysql://{root_user}:{root_password}@{DB_HOST}:{DB_PORT}"
    root_engine = create_engine(root_url, isolation_level="AUTOCOMMIT")
    with root_engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
        # ecom_user에게 test_ecommerce 권한 부여
        conn.execute(text(f"GRANT ALL PRIVILEGES ON {DB_NAME}.* TO '{DB_USER}'@'%'"))
        conn.execute(text("FLUSH PRIVILEGES"))
    root_engine.dispose()

_create_test_db()

test_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session")
def setup_database():
    """세션 단위: 처음 한 번만 스키마를 초기화합니다."""
    # 모든 테이블 드롭 후 다시 생성 (초기화)
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    # 필요시 주석 해제하여 테스트 후 테이블 삭제
    # Base.metadata.drop_all(bind=test_engine)

@pytest.fixture(scope="function")
def db_session(setup_database):
    """함수 단위: 각 테스트마다 새로운 트랜잭션을 실행하고, 끝나면 롤백합니다."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()
