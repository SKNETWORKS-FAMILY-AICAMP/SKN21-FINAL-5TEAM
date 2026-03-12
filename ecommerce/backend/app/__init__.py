"""
FastAPI Backend App

현업 표준 구조:
- app/models/: 모든 SQLAlchemy 모델 중앙 관리
- app/router/: 비즈니스 로직 (API 엔드포인트)
- models에서 router를 import하지 않음 (순환 참조 방지)
"""

# 하위 호환성을 위한 함수 (이제 사용 안함)
def init_models():
    """
    Deprecated: app.models 패키지를 직접 import하세요
    
    예시:
        from ecommerce.platform.backend.app.models import User, Product
    """
    from ecommerce.platform.backend.app.models import (
        Payment, PointHistory, Review, UserHistory,
        ShippingAddress, ShippingInfo,
        Product, ProductOption, Category, ProductImage,
        UsedProduct, UsedProductOption, UsedProductCondition,
        ProductType, UsedProductStatus,
        Cart, CartItem, User, Order, OrderItem
    )
    
    return {
        'Payment': Payment,
        'PointHistory': PointHistory,
        'Review': Review,
        'UserHistory': UserHistory,
        'ShippingAddress': ShippingAddress,
        'ShippingInfo': ShippingInfo,
        'Cart': Cart,
        'CartItem': CartItem,
        'Product': Product,
        'ProductOption': ProductOption,
        'Category': Category,
        'ProductImage': ProductImage,
        'UsedProduct': UsedProduct,
        'UsedProductOption': UsedProductOption,
        'UsedProductCondition': UsedProductCondition,
        'ProductType': ProductType,
        'UsedProductStatus': UsedProductStatus,
        'User': User,
        'Order': Order,
        'OrderItem': OrderItem,
    }
