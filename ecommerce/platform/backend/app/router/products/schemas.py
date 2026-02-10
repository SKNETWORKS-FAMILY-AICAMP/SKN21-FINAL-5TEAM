"""
Pydantic Schemas - Products Module
상품 관련 스키마
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

# Enum을 models에서 import
from ecommerce.platform.backend.app.router.products.models import ProductType, UsedProductStatus


# ============================================
# Category Schemas
# ============================================

class CategoryBase(BaseModel):
    """카테고리 기본 스키마"""
    name: str = Field(..., min_length=1, max_length=100, description="카테고리명")
    parent_id: Optional[int] = Field(None, description="상위 카테고리 ID")
    display_order: int = Field(default=0, description="표시 순서")
    is_active: bool = Field(default=True, description="활성화 여부")


class CategoryCreate(CategoryBase):
    """카테고리 생성 스키마"""
    pass


class CategoryUpdate(BaseModel):
    """카테고리 수정 스키마"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    parent_id: Optional[int] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class CategoryResponse(CategoryBase):
    """카테고리 응답 스키마"""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryWithChildren(CategoryResponse):
    """하위 카테고리 포함 응답"""
    children: List["CategoryResponse"] = []


# ============================================
# Product Schemas
# ============================================

class ProductBase(BaseModel):
    """신상품 기본 스키마"""
    category_id: int = Field(..., description="카테고리 ID")
    name: str = Field(..., min_length=1, max_length=255, description="품목명")
    description: Optional[str] = Field(None, description="상품 설명")
    tags: Optional[str] = Field(None, description="태그")
    price: Decimal = Field(..., gt=0, description="가격")
    is_active: bool = Field(default=True, description="판매 활성화 여부")


class ProductCreate(ProductBase):
    """신상품 생성 스키마"""
    pass


class ProductUpdate(BaseModel):
    """신상품 수정 스키마"""
    category_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0)
    is_active: Optional[bool] = None


class ProductResponse(ProductBase):
    """신상품 응답 스키마"""
    id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ============================================
# ProductOption Schemas
# ============================================

class ProductOptionBase(BaseModel):
    """신상품 옵션 기본 스키마"""
    size_name: Optional[str] = Field(None, max_length=20, description="사이즈명")
    color: Optional[str] = Field(None, max_length=50, description="색상")
    quantity: int = Field(default=0, ge=0, description="재고 수량")
    sku: Optional[str] = Field(None, max_length=100, description="SKU")
    is_active: bool = Field(default=True, description="옵션 활성화 여부")


class ProductOptionCreate(ProductOptionBase):
    """신상품 옵션 생성 스키마"""
    product_id: int = Field(..., description="신상품 ID")


class ProductOptionUpdate(BaseModel):
    """신상품 옵션 수정 스키마"""
    size_name: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=50)
    quantity: Optional[int] = Field(None, ge=0)
    sku: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class ProductOptionResponse(ProductOptionBase):
    """신상품 옵션 응답 스키마"""
    id: int
    product_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProductWithOptions(ProductResponse):
    """옵션 포함 신상품 응답"""
    options: List[ProductOptionResponse] = []


# ============================================
# UsedProductCondition Schemas
# ============================================

class UsedProductConditionBase(BaseModel):
    """중고 품목 상태 기본 스키마"""
    condition_name: str = Field(..., max_length=50, description="중고 품목 상태")
    depreciation_percent: Optional[Decimal] = Field(None, ge=0, le=100, description="감가 퍼센트")
    description: Optional[str] = Field(None, description="상태 설명")


class UsedProductConditionCreate(UsedProductConditionBase):
    """중고 품목 상태 생성 스키마"""
    pass


class UsedProductConditionUpdate(BaseModel):
    """중고 품목 상태 수정 스키마"""
    condition_name: Optional[str] = Field(None, max_length=50)
    depreciation_percent: Optional[Decimal] = Field(None, ge=0, le=100)
    description: Optional[str] = None


class UsedProductConditionResponse(UsedProductConditionBase):
    """중고 품목 상태 응답 스키마"""
    id: int

    model_config = ConfigDict(from_attributes=True)


# ============================================
# UsedProduct Schemas
# ============================================

class UsedProductBase(BaseModel):
    """중고 품목 기본 스키마"""
    category_id: int = Field(..., description="카테고리 ID")
    name: str = Field(..., min_length=1, max_length=255, description="품목명")
    description: Optional[str] = Field(None, description="상품 설명")
    tags: Optional[str] = Field(None, description="태그")
    price: Decimal = Field(..., gt=0, description="가격")
    condition_id: int = Field(..., description="중고 품목 상태 ID")
    status: UsedProductStatus = Field(default=UsedProductStatus.PENDING, description="판매 상태")


class UsedProductCreate(UsedProductBase):
    """중고 품목 생성 스키마"""
    seller_id: int = Field(..., description="판매자 ID")


class UsedProductUpdate(BaseModel):
    """중고 품목 수정 스키마"""
    category_id: Optional[int] = None
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    tags: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0)
    condition_id: Optional[int] = None
    status: Optional[UsedProductStatus] = None


class UsedProductResponse(UsedProductBase):
    """중고 품목 응답 스키마"""
    id: int
    seller_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


# ============================================
# UsedProductOption Schemas
# ============================================

class UsedProductOptionBase(BaseModel):
    """중고상품 옵션 기본 스키마"""
    size_name: Optional[str] = Field(None, max_length=20, description="사이즈명")
    color: Optional[str] = Field(None, max_length=50, description="색상")
    quantity: int = Field(default=1, ge=0, description="수량")
    is_active: bool = Field(default=True, description="옵션 활성화 여부")


class UsedProductOptionCreate(UsedProductOptionBase):
    """중고상품 옵션 생성 스키마"""
    used_product_id: int = Field(..., description="중고 품목 ID")


class UsedProductOptionUpdate(BaseModel):
    """중고상품 옵션 수정 스키마"""
    size_name: Optional[str] = Field(None, max_length=20)
    color: Optional[str] = Field(None, max_length=50)
    quantity: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class UsedProductOptionResponse(UsedProductOptionBase):
    """중고상품 옵션 응답 스키마"""
    id: int
    used_product_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UsedProductWithOptions(UsedProductResponse):
    """옵션 포함 중고 품목 응답"""
    options: List[UsedProductOptionResponse] = []


# ============================================
# ProductImage Schemas
# ============================================

class ProductImageBase(BaseModel):
    """상품 이미지 기본 스키마"""
    product_type: ProductType = Field(..., description="상품 유형")
    product_id: int = Field(..., description="상품 ID")
    image_url: str = Field(..., max_length=500, description="이미지 URL")
    display_order: int = Field(default=0, description="표시 순서")
    is_primary: bool = Field(default=False, description="대표 이미지 여부")


class ProductImageCreate(ProductImageBase):
    """상품 이미지 생성 스키마"""
    pass


class ProductImageUpdate(BaseModel):
    """상품 이미지 수정 스키마"""
    image_url: Optional[str] = Field(None, max_length=500)
    display_order: Optional[int] = None
    is_primary: Optional[bool] = None


class ProductImageResponse(ProductImageBase):
    """상품 이미지 응답 스키마"""
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================
# Search & Filter Schemas
# ============================================

class ProductSearchParams(BaseModel):
    """상품 검색 파라미터"""
    keyword: Optional[str] = Field(None, description="검색 키워드")
    category_id: Optional[int] = Field(None, description="카테고리 ID")
    min_price: Optional[Decimal] = Field(None, ge=0, description="최소 가격")
    max_price: Optional[Decimal] = Field(None, ge=0, description="최대 가격")
    is_active: Optional[bool] = Field(None, description="활성화 여부")
    skip: int = Field(default=0, ge=0, description="건너뛸 레코드 수")
    limit: int = Field(default=100, ge=1, le=1000, description="최대 조회 레코드 수")


class UsedProductSearchParams(BaseModel):
    """중고 상품 검색 파라미터"""
    keyword: Optional[str] = Field(None, description="검색 키워드")
    category_id: Optional[int] = Field(None, description="카테고리 ID")
    seller_id: Optional[int] = Field(None, description="판매자 ID")
    condition_id: Optional[int] = Field(None, description="상태 ID")
    status: Optional[UsedProductStatus] = Field(None, description="판매 상태")
    min_price: Optional[Decimal] = Field(None, ge=0, description="최소 가격")
    max_price: Optional[Decimal] = Field(None, ge=0, description="최대 가격")
    skip: int = Field(default=0, ge=0, description="건너뛸 레코드 수")
    limit: int = Field(default=100, ge=1, le=1000, description="최대 조회 레코드 수")
