"""
CRUD Operations - Products Module
상품 관련 CRUD 함수
"""
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func

from ecommerce.backend.app.router.products import models, schemas

# mapping.py

COLOR_MAP = {
    "검정": "Black", "검은": "Black", "블랙": "Black",
    "흰색": "White", "흰": "White", "화이트": "White",
    "빨강": "Red", "빨간": "Red", "레드": "Red",
    "파랑": "Blue", "파란": "Blue", "블루": "Blue",
    "초록": "Green", "초록색": "Green", "그린": "Green",
    "노랑": "Yellow", "노란": "Yellow", "옐로우": "Yellow",
    "핑크": "Pink",
    "보라": "Purple", "퍼플": "Purple",
    "회색": "Grey", "그레이": "Grey",
    "갈색": "Brown", "브라운": "Brown",
    "네이비": "Navy",
    "베이지": "Beige",
    "크림": "Cream",
    "와인": "Maroon", "버건디": "Maroon",
    "주황": "Orange", "오렌지": "Orange",
    "골드": "Gold",
    "실버": "Silver",
    "멀티": "Multi", "여러색": "Multi",
    "아이보리": "Ivory",
    "차콜": "Charcoal",
}

SEASON_MAP = {
    "봄": "Spring",
    "여름": "Summer",
    "가을": "Fall",
    "겨울": "Winter",
}

GENDER_MAP = {
    "남성": "Men", "남자": "Men",
    "여성": "Women", "여자": "Women",
    "남아": "Boys",
    "여아": "Girls",
    "공용": "Unisex",
}

PRODUCT_TYPE_MAP = {
    "샌들": "Sandals",
    "구두": "Heels",
    "플랫": "Flats",
    "운동화": "Shoes",
    "티셔츠": "T-shirt",
    "반팔": "T-shirt",
    "청바지": "Jeans",
    "레깅스": "Leggings",
    "원피스": "Dress",
    "가방": "Bag",
    "핸드백": "Handbag",
    "목걸이": "Necklace",
    "팔찌": "Bracelet",
    "반지": "Ring",
    "시계": "Watch",
    "립스틱": "Lipstick",
    "파운데이션": "Foundation",
    "선크림": "Sunscreen",
    "자켓": "Jacket", "재킷": "Jacket",
    "바지": "Pants",
    "잠옷": "Nightdress",
}

# ============================================
# Category CRUD
# ============================================

def get_category_by_id(db: Session, category_id: int) -> Optional[models.Category]:
    """
    카테고리 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        category_id: 카테고리 ID
    
    Returns:
        Category 객체 또는 None
    """
    return db.query(models.Category).filter(models.Category.id == category_id).first()


def get_categories(
    db: Session,
    parent_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100
) -> List[models.Category]:
    """
    카테고리 목록 조회
    
    Args:
        db: 데이터베이스 세션
        parent_id: 상위 카테고리 ID (None이면 최상위 카테고리)
        is_active: 활성화 여부
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        Category 객체 리스트
    """
    query = db.query(models.Category)
    
    if parent_id is not None:
        query = query.filter(models.Category.parent_id == parent_id)
    
    if is_active is not None:
        query = query.filter(models.Category.is_active == is_active)
    
    return (
        query
        .order_by(models.Category.display_order, models.Category.name)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_category_tree(db: Session, parent_id: Optional[int] = None) -> List[models.Category]:
    """
    카테고리 계층 구조 조회
    
    Args:
        db: 데이터베이스 세션
        parent_id: 시작 카테고리 ID
    
    Returns:
        하위 카테고리를 포함한 Category 객체 리스트
    """
    return (
        db.query(models.Category)
        .filter(models.Category.parent_id == parent_id)
        .options(joinedload(models.Category.children))
        .order_by(models.Category.display_order)
        .all()
    )


def create_category(
    db: Session,
    category_data: schemas.CategoryCreate
) -> models.Category:
    """
    카테고리 생성
    
    Args:
        db: 데이터베이스 세션
        category_data: 카테고리 생성 데이터
    
    Returns:
        생성된 Category 객체
    """
    category = models.Category(**category_data.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(
    db: Session,
    category_id: int,
    category_update: schemas.CategoryUpdate
) -> Optional[models.Category]:
    """
    카테고리 수정
    
    Args:
        db: 데이터베이스 세션
        category_id: 카테고리 ID
        category_update: 수정할 카테고리 정보
    
    Returns:
        수정된 Category 객체 또는 None
    """
    category = get_category_by_id(db, category_id)
    
    if not category:
        return None
    
    update_data = category_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(category, key, value)
    
    db.commit()
    db.refresh(category)
    
    return category


def delete_category(db: Session, category_id: int) -> bool:
    """
    카테고리 삭제
    
    Args:
        db: 데이터베이스 세션
        category_id: 카테고리 ID
    
    Returns:
        삭제 성공 여부
    """
    category = get_category_by_id(db, category_id)
    
    if not category:
        return False
    
    db.delete(category)
    db.commit()
    
    return True


# ============================================
# Product CRUD
# ============================================

def get_product_by_id(
    db: Session,
    product_id: int,
    include_deleted: bool = False
) -> Optional[models.Product]:

    query = db.query(models.Product).filter(models.Product.id == product_id)

    if not include_deleted:
        query = query.filter(models.Product.deleted_at.is_(None))

    return query.first()


def get_products(
    db: Session,
    category_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    keyword: Optional[str] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    skip: int = 0,
    limit: int = 100
) -> List[models.Product]:

    # ---------------------------
    # 기본 Query (JOIN 포함)
    # ---------------------------
    query = (
        db.query(models.Product)
        .join(
            models.ProductOption,
            models.ProductOption.product_id == models.Product.id,
            isouter=True
        )
        .join(
            models.Category,
            models.Category.id == models.Product.category_id,
            isouter=True
        )
        .filter(models.Product.deleted_at.is_(None))
    )

    # ---------------------------
    # 기본 필터
    # ---------------------------
    if category_id is not None:
        query = query.filter(models.Product.category_id == category_id)

    if is_active is not None:
        query = query.filter(models.Product.is_active == is_active)

    # ---------------------------
    # 🔎 검색 (AND 유지)
    # ---------------------------
    if keyword:
        words = keyword.strip().split()
        # ---------------------------
        # 🔁 한글 → 영어 변환
        # ---------------------------
        normalized_words = []

        for word in words:
            if word in COLOR_MAP:
                normalized_words.append(COLOR_MAP[word])
            elif word in SEASON_MAP:
                normalized_words.append(SEASON_MAP[word])
            elif word in GENDER_MAP:
                normalized_words.append(GENDER_MAP[word])
            elif word in PRODUCT_TYPE_MAP:
                normalized_words.append(PRODUCT_TYPE_MAP[word])
            else:
                normalized_words.append(word)

        words = normalized_words
        
        for word in words:
            search = f"%{word.lower()}%"

            query = query.filter(
                or_(
                    func.lower(models.Product.name).like(search),
                    func.lower(func.coalesce(models.Product.description, "")).like(search),
                    func.lower(func.coalesce(models.Product.tags, "")).like(search),
                    func.lower(func.coalesce(models.ProductOption.color, "")).like(search),
                    func.lower(func.coalesce(models.Category.name, "")).like(search),
                )
            )

    # ---------------------------
    # 가격 필터
    # ---------------------------
    if min_price is not None:
        query = query.filter(models.Product.price >= min_price)

    if max_price is not None:
        query = query.filter(models.Product.price <= max_price)

    # ---------------------------
    # 중복 제거 + 정렬
    # ---------------------------
    query = query.distinct().order_by(models.Product.id.desc())

    return query.offset(skip).limit(limit).all()


def get_product_with_options(
    db: Session,
    product_id: int
) -> Optional[models.Product]:

    return (
        db.query(models.Product)
        .filter(
            models.Product.id == product_id,
            models.Product.deleted_at.is_(None)
        )
        .options(joinedload(models.Product.options))
        .first()
    )


def create_product(
    db: Session,
    product_data: schemas.ProductCreate
) -> models.Product:

    product = models.Product(**product_data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def update_product(
    db: Session,
    product_id: int,
    product_update: schemas.ProductUpdate
) -> Optional[models.Product]:

    product = get_product_by_id(db, product_id)

    if not product:
        return None

    update_data = product_update.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(product, key, value)

    db.commit()
    db.refresh(product)

    return product


def delete_product(db: Session, product_id: int, soft_delete: bool = True) -> bool:

    product = get_product_by_id(db, product_id)

    if not product:
        return False

    if soft_delete:
        product.deleted_at = datetime.utcnow()
        db.commit()
    else:
        db.delete(product)
        db.commit()

    return True

# ============================================
# ProductOption CRUD
# ============================================

def get_product_option_by_id(db: Session, option_id: int) -> Optional[models.ProductOption]:
    """
    신상품 옵션 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        option_id: 옵션 ID
    
    Returns:
        ProductOption 객체 또는 None
    """
    return db.query(models.ProductOption).filter(models.ProductOption.id == option_id).first()


def get_product_options_by_product(
    db: Session,
    product_id: int,
    is_active: Optional[bool] = None
) -> List[models.ProductOption]:
    """
    신상품별 옵션 목록 조회
    
    Args:
        db: 데이터베이스 세션
        product_id: 신상품 ID
        is_active: 활성화 여부
    
    Returns:
        ProductOption 객체 리스트
    """
    query = db.query(models.ProductOption).filter(
        models.ProductOption.product_id == product_id
    )
    
    if is_active is not None:
        query = query.filter(models.ProductOption.is_active == is_active)
    
    return query.all()


def create_product_option(
    db: Session,
    option_data: schemas.ProductOptionCreate
) -> models.ProductOption:
    """
    신상품 옵션 생성
    
    Args:
        db: 데이터베이스 세션
        option_data: 옵션 생성 데이터
    
    Returns:
        생성된 ProductOption 객체
    """
    option = models.ProductOption(**option_data.model_dump())
    db.add(option)
    db.commit()
    db.refresh(option)
    return option


def update_product_option(
    db: Session,
    option_id: int,
    option_update: schemas.ProductOptionUpdate
) -> Optional[models.ProductOption]:
    """
    신상품 옵션 수정
    
    Args:
        db: 데이터베이스 세션
        option_id: 옵션 ID
        option_update: 수정할 옵션 정보
    
    Returns:
        수정된 ProductOption 객체 또는 None
    """
    option = get_product_option_by_id(db, option_id)
    
    if not option:
        return None
    
    update_data = option_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(option, key, value)
    
    db.commit()
    db.refresh(option)
    
    return option


def delete_product_option(db: Session, option_id: int) -> bool:
    """
    신상품 옵션 삭제
    
    Args:
        db: 데이터베이스 세션
        option_id: 옵션 ID
    
    Returns:
        삭제 성공 여부
    """
    option = get_product_option_by_id(db, option_id)
    
    if not option:
        return False
    
    db.delete(option)
    db.commit()
    
    return True

from decimal import Decimal
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from ecommerce.backend.app.router.products import models, schemas


# ============================================
# UsedProductCondition CRUD
# ============================================

def get_used_product_condition_by_id(db: Session, condition_id: int) -> Optional[models.UsedProductCondition]:
    """중고 품목 상태 ID로 조회"""
    return db.query(models.UsedProductCondition).filter(
        models.UsedProductCondition.id == condition_id
    ).first()


def get_used_product_conditions(db: Session) -> List[models.UsedProductCondition]:
    """중고 품목 상태 목록 조회"""
    return db.query(models.UsedProductCondition).all()


def create_used_product_condition(
    db: Session,
    condition_data: schemas.UsedProductConditionCreate
) -> models.UsedProductCondition:
    """중고 품목 상태 생성"""
    condition = models.UsedProductCondition(**condition_data.model_dump())
    db.add(condition)
    db.commit()
    db.refresh(condition)
    return condition


def update_used_product_condition(
    db: Session,
    condition_id: int,
    condition_update: schemas.UsedProductConditionUpdate
) -> Optional[models.UsedProductCondition]:
    """중고 품목 상태 수정"""
    condition = get_used_product_condition_by_id(db, condition_id)
    
    if not condition:
        return None
    
    update_data = condition_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(condition, key, value)
    
    db.commit()
    db.refresh(condition)
    
    return condition


def delete_used_product_condition(db: Session, condition_id: int) -> bool:
    """중고 품목 상태 삭제"""
    condition = get_used_product_condition_by_id(db, condition_id)
    
    if not condition:
        return False
    
    db.delete(condition)
    db.commit()
    
    return True


# ============================================
# UsedProduct CRUD
# ============================================

def get_used_product_by_id(
    db: Session,
    used_product_id: int,
    include_deleted: bool = False
) -> Optional[models.UsedProduct]:
    """
    중고 품목 ID로 조회
    
    Args:
        db: 데이터베이스 세션
        used_product_id: 중고 품목 ID
        include_deleted: 삭제된 상품 포함 여부
    
    Returns:
        UsedProduct 객체 또는 None
    """
    query = db.query(models.UsedProduct).filter(models.UsedProduct.id == used_product_id)
    
    if not include_deleted:
        query = query.filter(models.UsedProduct.deleted_at.is_(None))
    
    return query.first()


def get_used_products(
    db: Session,
    category_id: Optional[int] = None,
    seller_id: Optional[int] = None,
    condition_id: Optional[int] = None,
    status: Optional[schemas.UsedProductStatus] = None,
    keyword: Optional[str] = None,
    min_price: Optional[Decimal] = None,
    max_price: Optional[Decimal] = None,
    skip: int = 0,
    limit: int = 100
) -> List[models.UsedProduct]:
    """
    중고 품목 목록 조회
    
    Args:
        db: 데이터베이스 세션
        category_id: 카테고리 ID
        seller_id: 판매자 ID
        condition_id: 상태 ID
        status: 판매 상태
        keyword: 검색 키워드
        min_price: 최소 가격
        max_price: 최대 가격
        skip: 건너뛸 레코드 수
        limit: 최대 조회 레코드 수
    
    Returns:
        UsedProduct 객체 리스트
    """
    query = (
        db.query(models.UsedProduct)
        .options(joinedload(models.UsedProduct.condition))  # ✅ condition JOIN 추가
        .filter(models.UsedProduct.deleted_at.is_(None))
    )
    
    if category_id is not None:
        query = query.filter(models.UsedProduct.category_id == category_id)
    
    if seller_id is not None:
        query = query.filter(models.UsedProduct.seller_id == seller_id)
    
    if condition_id is not None:
        query = query.filter(models.UsedProduct.condition_id == condition_id)
    
    # ✅ 기본값: 승인된 상품만 노출
    if status is not None:
        query = query.filter(models.UsedProduct.status == status)
    else:
        query = query.filter(
            models.UsedProduct.status == models.UsedProductStatus.APPROVED
        )
    
    if keyword:
        search_pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                models.UsedProduct.name.ilike(search_pattern),
                models.UsedProduct.description.ilike(search_pattern),
                models.UsedProduct.tags.ilike(search_pattern)
            )
        )
    
    if min_price is not None:
        query = query.filter(models.UsedProduct.price >= min_price)
    
    if max_price is not None:
        query = query.filter(models.UsedProduct.price <= max_price)
    
    return (
        query
        .order_by(models.UsedProduct.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

def get_used_product_with_options(
    db: Session,
    used_product_id: int
) -> Optional[models.UsedProduct]:
    """
    옵션 포함 중고 품목 조회
    
    Args:
        db: 데이터베이스 세션
        used_product_id: 중고 품목 ID
    
    Returns:
        옵션이 포함된 UsedProduct 객체 또는 None
    """
    return (
        db.query(models.UsedProduct)
        .filter(
            models.UsedProduct.id == used_product_id,
            models.UsedProduct.deleted_at.is_(None)
        )
        .options(
            joinedload(models.UsedProduct.options),
            joinedload(models.UsedProduct.condition)  # ✅ condition JOIN 추가
        )
        .first()
    )


def sync_used_product_status_by_stock(db: Session, used_product_id: int) -> None:
    """
    중고상품 옵션 재고 기준으로 상태를 자동 갱신
    - 모든 옵션 재고 합이 0이면 `SOLD`
    - 다시 재고가 생기면 `APPROVED`로 복원
    """
    total_quantity = (
        db.query(
            func.coalesce(func.sum(models.UsedProductOption.quantity), 0)
        )
        .filter(
            models.UsedProductOption.used_product_id == used_product_id,
            models.UsedProductOption.is_active == True
        )
        .scalar() or 0
    )

    used_product = get_used_product_by_id(db, used_product_id)
    if not used_product:
        return

    if total_quantity <= 0 and used_product.status == models.UsedProductStatus.APPROVED:
        used_product.status = models.UsedProductStatus.SOLD
    elif total_quantity > 0 and used_product.status == models.UsedProductStatus.SOLD:
        used_product.status = models.UsedProductStatus.APPROVED

def create_used_product(
    db: Session,
    used_product_data: schemas.UsedProductCreate
) -> models.UsedProduct:
    """
    중고 품목 생성
    
    Args:
        db: 데이터베이스 세션
        used_product_data: 중고 품목 생성 데이터
    
    Returns:
        생성된 UsedProduct 객체
    """
    used_product = models.UsedProduct(**used_product_data.model_dump())
    db.add(used_product)
    db.commit()
    db.refresh(used_product)
    return used_product


def update_used_product(
    db: Session,
    used_product_id: int,
    used_product_update: schemas.UsedProductUpdate
) -> Optional[models.UsedProduct]:
    """
    중고 품목 수정
    
    Args:
        db: 데이터베이스 세션
        used_product_id: 중고 품목 ID
        used_product_update: 수정할 중고 품목 정보
    
    Returns:
        수정된 UsedProduct 객체 또는 None
    """
    used_product = get_used_product_by_id(db, used_product_id)
    
    if not used_product:
        return None
    
    update_data = used_product_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(used_product, key, value)
    
    db.commit()
    db.refresh(used_product)
    
    return used_product


def delete_used_product(
    db: Session,
    used_product_id: int,
    soft_delete: bool = True
) -> bool:
    """
    중고 품목 삭제
    
    Args:
        db: 데이터베이스 세션
        used_product_id: 중고 품목 ID
        soft_delete: 소프트 삭제 여부
    
    Returns:
        삭제 성공 여부
    """
    used_product = get_used_product_by_id(db, used_product_id)
    
    if not used_product:
        return False
    
    if soft_delete:
        used_product.deleted_at = datetime.utcnow()
        db.commit()
    else:
        db.delete(used_product)
        db.commit()
    
    return True


def approve_used_product(db: Session, used_product_id: int) -> Optional[models.UsedProduct]:
    """중고 품목 승인"""
    used_product = get_used_product_by_id(db, used_product_id)
    
    if not used_product:
        return None
    
    used_product.status = schemas.UsedProductStatus.APPROVED
    db.commit()
    db.refresh(used_product)
    
    return used_product


def reject_used_product(db: Session, used_product_id: int) -> Optional[models.UsedProduct]:
    """중고 품목 거절"""
    used_product = get_used_product_by_id(db, used_product_id)
    
    if not used_product:
        return None
    
    used_product.status = schemas.UsedProductStatus.REJECTED
    db.commit()
    db.refresh(used_product)
    
    return used_product


# ============================================
# UsedProductOption CRUD
# ============================================

def get_used_product_option_by_id(db: Session, option_id: int) -> Optional[models.UsedProductOption]:
    """중고상품 옵션 ID로 조회"""
    return db.query(models.UsedProductOption).filter(
        models.UsedProductOption.id == option_id
    ).first()


def get_used_product_options_by_product(
    db: Session,
    used_product_id: int,
    is_active: Optional[bool] = None
) -> List[models.UsedProductOption]:
    """중고 품목별 옵션 목록 조회"""
    query = db.query(models.UsedProductOption).filter(
        models.UsedProductOption.used_product_id == used_product_id
    )
    
    if is_active is not None:
        query = query.filter(models.UsedProductOption.is_active == is_active)
    
    return query.all()


def create_used_product_option(
    db: Session,
    option_data: schemas.UsedProductOptionCreate
) -> models.UsedProductOption:
    """중고상품 옵션 생성"""
    option = models.UsedProductOption(**option_data.model_dump())
    db.add(option)
    db.commit()
    db.refresh(option)
    return option


def update_used_product_option(
    db: Session,
    option_id: int,
    option_update: schemas.UsedProductOptionUpdate
) -> Optional[models.UsedProductOption]:
    """중고상품 옵션 수정"""
    option = get_used_product_option_by_id(db, option_id)
    
    if not option:
        return None
    
    update_data = option_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(option, key, value)

    sync_used_product_status_by_stock(db, option.used_product_id)

    db.commit()
    db.refresh(option)
    
    return option


def delete_used_product_option(db: Session, option_id: int) -> bool:
    """중고상품 옵션 삭제"""
    option = get_used_product_option_by_id(db, option_id)
    
    if not option:
        return False
    
    db.delete(option)
    db.commit()
    
    return True


# ============================================
# ProductImage CRUD
# ============================================

def get_product_image_by_id(db: Session, image_id: int) -> Optional[models.ProductImage]:
    """상품 이미지 ID로 조회"""
    return db.query(models.ProductImage).filter(models.ProductImage.id == image_id).first()


def get_product_images(
    db: Session,
    product_type: schemas.ProductType,
    product_id: int
) -> List[models.ProductImage]:
    """상품별 이미지 목록 조회"""
    return (
        db.query(models.ProductImage)
        .filter(
            and_(
                models.ProductImage.product_type == product_type,
                models.ProductImage.product_id == product_id
            )
        )
        .order_by(models.ProductImage.display_order)
        .all()
    )


def create_product_image(
    db: Session,
    image_data: schemas.ProductImageCreate
) -> models.ProductImage:
    """상품 이미지 생성"""
    image = models.ProductImage(**image_data.model_dump())
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def update_product_image(
    db: Session,
    image_id: int,
    image_update: schemas.ProductImageUpdate
) -> Optional[models.ProductImage]:
    """상품 이미지 수정"""
    image = get_product_image_by_id(db, image_id)
    
    if not image:
        return None
    
    update_data = image_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(image, key, value)
    
    db.commit()
    db.refresh(image)
    
    return image


def delete_product_image(db: Session, image_id: int) -> bool:
    """상품 이미지 삭제"""
    image = get_product_image_by_id(db, image_id)
    
    if not image:
        return False
    
    db.delete(image)
    db.commit()
    
    return True


def set_primary_image(
    db: Session,
    product_type: schemas.ProductType,
    product_id: int,
    image_id: int
) -> Optional[models.ProductImage]:
    """대표 이미지 설정"""
    # 해당 상품의 모든 이미지를 비대표로 설정
    db.query(models.ProductImage).filter(
        and_(
            models.ProductImage.product_type == product_type,
            models.ProductImage.product_id == product_id
        )
    ).update({"is_primary": False})
    
    # 선택한 이미지를 대표로 설정
    image = get_product_image_by_id(db, image_id)
    
    if image:
        image.is_primary = True
        db.commit()
        db.refresh(image)
    
    return image
