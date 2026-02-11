"""
FastAPI Router - Products Module
상품 관련 API 엔드포인트
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from decimal import Decimal
import logging

from ecommerce.platform.backend.app.database import get_db
from ecommerce.platform.backend.app.router.products import crud, schemas

# 로깅 설정
logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["products"]
)


# ==================== 카테고리 ====================

@router.get("/categories", response_model=List[schemas.CategoryResponse])
def list_categories(
    parent_id: Optional[int] = Query(None, description="상위 카테고리 ID"),
    is_active: Optional[bool] = Query(None, description="활성화 여부"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """카테고리 목록 조회"""
    logger.info(f"Fetching categories, parent_id={parent_id}")
    return crud.get_categories(db, parent_id, is_active, skip, limit)


@router.get("/categories/{category_id}", response_model=schemas.CategoryResponse)
def get_category(category_id: int, db: Session = Depends(get_db)):
    """카테고리 조회"""
    category = crud.get_category_by_id(db, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다")
    return category


@router.post("/categories", response_model=schemas.CategoryResponse, status_code=201)
def create_category(
    category_data: schemas.CategoryCreate,
    db: Session = Depends(get_db)
):
    """카테고리 생성"""
    logger.info(f"Creating category: {category_data.name}")
    return crud.create_category(db, category_data)


@router.put("/categories/{category_id}", response_model=schemas.CategoryResponse)
def update_category(
    category_id: int,
    category_update: schemas.CategoryUpdate,
    db: Session = Depends(get_db)
):
    """카테고리 수정"""
    category = crud.update_category(db, category_id, category_update)
    if not category:
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다")
    return category


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    """카테고리 삭제"""
    if not crud.delete_category(db, category_id):
        raise HTTPException(status_code=404, detail="카테고리를 찾을 수 없습니다")
    return None


# ==================== 신상품 ====================

@router.get("/new", response_model=List[schemas.ProductResponse])
def list_products(
    category_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(None),
    keyword: Optional[str] = Query(None),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """신상품 목록 조회"""
    logger.info(f"Fetching products, keyword={keyword}")
    return crud.get_products(db, category_id, is_active, keyword, min_price, max_price, skip, limit)


@router.get("/new/{product_id}", response_model=schemas.ProductWithOptions)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """신상품 조회 (옵션 포함)"""
    product = crud.get_product_with_options(db, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.post("/new", response_model=schemas.ProductResponse, status_code=201)
def create_product(
    product_data: schemas.ProductCreate,
    db: Session = Depends(get_db)
):
    """신상품 생성"""
    logger.info(f"Creating product: {product_data.name}")
    return crud.create_product(db, product_data)


@router.put("/new/{product_id}", response_model=schemas.ProductResponse)
def update_product(
    product_id: int,
    product_update: schemas.ProductUpdate,
    db: Session = Depends(get_db)
):
    """신상품 수정"""
    product = crud.update_product(db, product_id, product_update)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.delete("/new/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    soft_delete: bool = Query(True, description="소프트 삭제 여부"),
    db: Session = Depends(get_db)
):
    """신상품 삭제"""
    if not crud.delete_product(db, product_id, soft_delete):
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return None


# ==================== 신상품 옵션 ====================

@router.get("/new/{product_id}/options", response_model=List[schemas.ProductOptionResponse])
def list_product_options(
    product_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db)
):
    """신상품 옵션 목록 조회"""
    return crud.get_product_options_by_product(db, product_id, is_active)


@router.post("/new/{product_id}/options", response_model=schemas.ProductOptionResponse, status_code=201)
def create_product_option(
    product_id: int,
    option_data: schemas.ProductOptionCreate,
    db: Session = Depends(get_db)
):
    """신상품 옵션 생성"""
    return crud.create_product_option(db, option_data)


@router.put("/options/{option_id}", response_model=schemas.ProductOptionResponse)
def update_product_option(
    option_id: int,
    option_update: schemas.ProductOptionUpdate,
    db: Session = Depends(get_db)
):
    """신상품 옵션 수정"""
    option = crud.update_product_option(db, option_id, option_update)
    if not option:
        raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다")
    return option


@router.delete("/options/{option_id}", status_code=204)
def delete_product_option(option_id: int, db: Session = Depends(get_db)):
    """신상품 옵션 삭제"""
    if not crud.delete_product_option(db, option_id):
        raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다")
    return None


# ==================== 중고 품목 상태 ====================

@router.get("/used/conditions", response_model=List[schemas.UsedProductConditionResponse])
def list_used_product_conditions(db: Session = Depends(get_db)):
    """중고 품목 상태 목록 조회"""
    return crud.get_used_product_conditions(db)


@router.post("/used/conditions", response_model=schemas.UsedProductConditionResponse, status_code=201)
def create_used_product_condition(
    condition_data: schemas.UsedProductConditionCreate,
    db: Session = Depends(get_db)
):
    """중고 품목 상태 생성"""
    return crud.create_used_product_condition(db, condition_data)


# ==================== 중고상품 ====================

@router.get("/used", response_model=List[schemas.UsedProductResponse])
def list_used_products(
    category_id: Optional[int] = Query(None),
    seller_id: Optional[int] = Query(None),
    condition_id: Optional[int] = Query(None),
    status: Optional[schemas.UsedProductStatus] = Query(None),
    keyword: Optional[str] = Query(None),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """중고상품 목록 조회"""
    logger.info(f"Fetching used products, keyword={keyword}")
    return crud.get_used_products(
        db, category_id, seller_id, condition_id, status,
        keyword, min_price, max_price, skip, limit
    )


@router.get("/used/{used_product_id}", response_model=schemas.UsedProductWithOptions)
def get_used_product(used_product_id: int, db: Session = Depends(get_db)):
    """중고상품 조회 (옵션 포함)"""
    product = crud.get_used_product_with_options(db, used_product_id)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.post("/used", response_model=schemas.UsedProductResponse, status_code=201)
def create_used_product(
    product_data: schemas.UsedProductCreate,
    db: Session = Depends(get_db)
):
    """중고상품 생성"""
    logger.info(f"Creating used product: {product_data.name}")
    return crud.create_used_product(db, product_data)


@router.put("/used/{used_product_id}", response_model=schemas.UsedProductResponse)
def update_used_product(
    used_product_id: int,
    product_update: schemas.UsedProductUpdate,
    db: Session = Depends(get_db)
):
    """중고상품 수정"""
    product = crud.update_used_product(db, used_product_id, product_update)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.delete("/used/{used_product_id}", status_code=204)
def delete_used_product(
    used_product_id: int,
    soft_delete: bool = Query(True, description="소프트 삭제 여부"),
    db: Session = Depends(get_db)
):
    """중고상품 삭제"""
    if not crud.delete_used_product(db, used_product_id, soft_delete):
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return None


@router.patch("/used/{used_product_id}/approve", response_model=schemas.UsedProductResponse)
def approve_used_product(used_product_id: int, db: Session = Depends(get_db)):
    """중고상품 승인"""
    product = crud.approve_used_product(db, used_product_id)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


@router.patch("/used/{used_product_id}/reject", response_model=schemas.UsedProductResponse)
def reject_used_product(used_product_id: int, db: Session = Depends(get_db)):
    """중고상품 거절"""
    product = crud.reject_used_product(db, used_product_id)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return product


# ==================== 중고상품 옵션 ====================

@router.get("/used/{used_product_id}/options", response_model=List[schemas.UsedProductOptionResponse])
def list_used_product_options(
    used_product_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db)
):
    """중고상품 옵션 목록 조회"""
    return crud.get_used_product_options_by_product(db, used_product_id, is_active)


@router.post("/used/{used_product_id}/options", response_model=schemas.UsedProductOptionResponse, status_code=201)
def create_used_product_option(
    used_product_id: int,
    option_data: schemas.UsedProductOptionCreate,
    db: Session = Depends(get_db)
):
    """중고상품 옵션 생성"""
    return crud.create_used_product_option(db, option_data)


@router.put("/used/options/{option_id}", response_model=schemas.UsedProductOptionResponse)
def update_used_product_option(
    option_id: int,
    option_update: schemas.UsedProductOptionUpdate,
    db: Session = Depends(get_db)
):
    """중고상품 옵션 수정"""
    option = crud.update_used_product_option(db, option_id, option_update)
    if not option:
        raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다")
    return option


@router.delete("/used/options/{option_id}", status_code=204)
def delete_used_product_option(option_id: int, db: Session = Depends(get_db)):
    """중고상품 옵션 삭제"""
    if not crud.delete_used_product_option(db, option_id):
        raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다")
    return None


# ==================== 상품 이미지 ====================

@router.get("/images/{product_type}/{product_id}", response_model=List[schemas.ProductImageResponse])
def list_product_images(
    product_type: schemas.ProductType,
    product_id: int,
    db: Session = Depends(get_db)
):
    """상품 이미지 목록 조회"""
    return crud.get_product_images(db, product_type, product_id)


@router.post("/images", response_model=schemas.ProductImageResponse, status_code=201)
def create_product_image(
    image_data: schemas.ProductImageCreate,
    db: Session = Depends(get_db)
):
    """상품 이미지 생성"""
    return crud.create_product_image(db, image_data)


@router.put("/images/{image_id}", response_model=schemas.ProductImageResponse)
def update_product_image(
    image_id: int,
    image_update: schemas.ProductImageUpdate,
    db: Session = Depends(get_db)
):
    """상품 이미지 수정"""
    image = crud.update_product_image(db, image_id, image_update)
    if not image:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")
    return image


@router.delete("/images/{image_id}", status_code=204)
def delete_product_image(image_id: int, db: Session = Depends(get_db)):
    """상품 이미지 삭제"""
    if not crud.delete_product_image(db, image_id):
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")
    return None


@router.patch("/images/{image_id}/set-primary", response_model=schemas.ProductImageResponse)
def set_primary_image(
    image_id: int,
    product_type: schemas.ProductType = Query(...),
    product_id: int = Query(...),
    db: Session = Depends(get_db)
):
    """대표 이미지 설정"""
    image = crud.set_primary_image(db, product_type, product_id, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")
    return image


# ==================== 헬스 체크 ====================

@router.get("/health", status_code=200)
def health_check():
    """상품 API 헬스 체크"""
    return {"status": "healthy", "service": "products"}
