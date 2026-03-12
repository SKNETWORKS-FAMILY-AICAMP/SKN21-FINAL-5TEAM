"""
Central Models Package
현업 표준: 모든 SQLAlchemy 모델을 중앙에서 관리

장점:
1. 순환 import 방지
2. 명확한 의존성 관리
3. 한 곳에서 모든 모델 확인 가능
4. router는 비즈니스 로직에만 집중
"""

# SQLAlchemy 모델들을 의존성 순서대로 import
# 다른 모델을 참조하지 않는 모델부터 먼저 로드

# 독립적인 모델들
from ecommerce.platform.backend.app.router.payments.models import Payment
from ecommerce.platform.backend.app.router.points.models import PointHistory
from ecommerce.platform.backend.app.router.reviews.models import Review
from ecommerce.platform.backend.app.router.user_history.models import UserHistory
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress, ShippingInfo

# Product 계열 (Enum 포함)
from ecommerce.platform.backend.app.router.products.models import (
    Product, ProductOption, Category, ProductImage,
    UsedProduct, UsedProductOption, UsedProductCondition,
    ProductType, UsedProductStatus  # Enums
)

# Cart (Product 의존)
from ecommerce.platform.backend.app.router.carts.models import Cart, CartItem

# User (Cart 의존)
from ecommerce.platform.backend.app.router.users.models import User

# Order (User, Product 의존)
from ecommerce.platform.backend.app.router.orders.models import Order, OrderItem

# 모든 모델 export
__all__ = [
    # Payment
    'Payment',
    # Points
    'PointHistory',
    # Reviews
    'Review',
    # User History
    'UserHistory',
    # Shipping
    'ShippingAddress',
    'ShippingInfo',
    # Products (Enums 포함)
    'Product',
    'ProductOption',
    'Category',
    'ProductImage',
    'UsedProduct',
    'UsedProductOption',
    'UsedProductCondition',
    'ProductType',
    'UsedProductStatus',
    # Carts
    'Cart',
    'CartItem',
    # Users
    'User',
    # Orders
    'Order',
    'OrderItem',
]
