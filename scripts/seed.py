"""
Database Seeding Script
서버 시작 시 초기 데이터를 DB에 적재하는 스크립트입니다.
"""
import logging
from decimal import Decimal
from sqlalchemy.orm import Session
from ecommerce.platform.backend.app.router.users.models import User, UserStatus
from ecommerce.platform.backend.app.router.products.models import (
    Category, Product, ProductOption, ProductType
)
# 필요한 경우 다른 모델들도 import

logger = logging.getLogger(__name__)

def init_db(db: Session):
    """
    초기 데이터 적재 함수
    데이터가 비어있을 경우에만 실행됩니다.
    """
    try:
        # 1. 사용자 데이터 확인 및 생성
        if not db.query(User).first():
            logger.info("🛠️ 초기 사용자 데이터 생성 중...")
            create_users(db)
        
        # 2. 카테고리 데이터 확인 및 생성
        if not db.query(Category).first():
            logger.info("🛠️ 초기 카테고리 데이터 생성 중...")
            create_categories(db)
            
        # 3. 상품 데이터 확인 및 생성
        if not db.query(Product).first():
            logger.info("🛠️ 초기 상품 데이터 생성 중...")
            create_products(db)
            
        db.commit()
        logger.info("✅ 초기 데이터 적재 완료")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ 초기 데이터 적재 실패: {e}")
        raise e

from ecommerce.platform.backend.app.router.users.crud import hash_password

def create_users(db: Session):
    """테스트 사용자 생성"""
    users = [
        User(
            email="test@example.com",
            # 초기 비밀번호: password123
            password_hash=hash_password("password123"), 
            name="테스트유저",
            phone="010-1234-5678",
            status=UserStatus.ACTIVE,
            address1="서울시 강남구",
            address2="테헤란로 123",
            agree_marketing=True,
            agree_sms=True,
            agree_email=True
        ),
        User(
            email="admin@example.com",
            # 초기 비밀번호: admin123
            password_hash=hash_password("admin123"),
            name="관리자",
            phone="010-9999-9999",
            status=UserStatus.ACTIVE,
            address1="서울시 중구",
            address2="1번지",
            agree_marketing=False,
            agree_sms=False,
            agree_email=False
        )
    ]
    db.add_all(users)
    db.flush() # ID 생성을 위해 flush

def create_categories(db: Session):
    """카테고리 생성"""
    # 대분류
    categories = {
        "상의": ["티셔츠", "셔츠/블라우스", "니트/스웨터", "후드/맨투맨"],
        "하의": ["청바지", "슬랙스", "스커트", "트레이닝 바지"],
        "아우터": ["코트", "자켓", "패딩", "가디건"],
        "신발": ["스니커즈", "구두", "부츠", "샌들"]
    }
    
    for main_name, sub_names in categories.items():
        main_cat = Category(name=main_name, parent_id=None, display_order=1)
        db.add(main_cat)
        db.flush() # ID 확보
        
        for idx, sub_name in enumerate(sub_names):
            sub_cat = Category(name=sub_name, parent_id=main_cat.id, display_order=idx+1)
            db.add(sub_cat)

def create_products(db: Session):
    """상품 및 옵션 생성"""
    # 상의 - 티셔츠 카테고리 조회
    tshirt_cat = db.query(Category).filter(Category.name == "티셔츠").first()
    
    if not tshirt_cat:
        return

    products = [
        Product(
            category_id=tshirt_cat.id,
            name="베이직 코튼 티셔츠",
            description="편안한 착용감의 기본 티셔츠입니다.",
            price=Decimal("15000"),
            is_active=True,
            tags="티셔츠,기본템,데일리"
        ),
        Product(
            category_id=tshirt_cat.id,
            name="오버핏 로고 티셔츠",
            description="트렌디한 오버핏 실루엣의 티셔츠입니다.",
            price=Decimal("25000"),
            is_active=True,
            tags="오버핏,로고,스트릿"
        )
    ]
    
    db.add_all(products)
    db.flush()
    
    # 옵션 추가
    for product in products:
        options = [
            ProductOption(product_id=product.id, size_name="M", color="White", quantity=100, is_active=True),
            ProductOption(product_id=product.id, size_name="L", color="White", quantity=100, is_active=True),
            ProductOption(product_id=product.id, size_name="M", color="Black", quantity=50, is_active=True),
            ProductOption(product_id=product.id, size_name="L", color="Black", quantity=50, is_active=True),
        ]
        db.add_all(options)
