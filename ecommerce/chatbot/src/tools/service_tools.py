"""
서비스 관련 Tools (상품권, 리뷰).
(Real DB Version)
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session
from sqlalchemy import func

from ecommerce.platform.backend.app.database import SessionLocal
# Updated imports
from ecommerce.platform.backend.app.router.reviews.models import Review
from ecommerce.platform.backend.app.router.orders.models import Order, OrderItem
from ecommerce.platform.backend.app.router.products.models import Product, ProductOption

# Import other models to ensure SQLAlchemy registry is fully populated
from ecommerce.platform.backend.app.router.users.models import User
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress
from ecommerce.chatbot.src.tools.base import BaseAPITool

# Helper to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@tool
def register_gift_card(code: str, user_id: str = None) -> dict:
    """
    상품권 코드를 등록합니다.
    (현재 DB 모델 미구현으로 Mock 동작 유지)
    
    Args:
        code: 상품권 코드
        user_id: 사용자 ID (선택)
        
    Returns:
        성공 여부, 메시지, 잔액, 유효기간
    """
    # TODO: Implement real DB logic when GiftCard/Voucher model is available.
    api = BaseAPITool(use_mock=True)
    data = {
        "code": code,
        "user_id": user_id
    }
    return api._call_api("/gift-card/register", method="POST", data=data)


@tool
def get_reviews(product_id: str = None, limit: int = 10) -> dict:
    """
    리뷰를 조회합니다.
    
    Args:
        product_id: 상품 ID (선택, 없으면 전체 조회)
        limit: 조회할 리뷰 개수 (기본 10)
        
    Returns:
        리뷰 목록
    """
    db = SessionLocal()
    try:
        query = db.query(Review)
        
        if product_id:
            # Complex join to filter by product_id
            # Review -> OrderItem -> ProductOption -> Product
            query = query.join(OrderItem, Review.order_item_id == OrderItem.id)\
                         .join(ProductOption, OrderItem.product_option_id == ProductOption.id)\
                         .filter(ProductOption.product_id == int(product_id))
        
        reviews = query.limit(limit).all()
        
        result = []
        for r in reviews:
            result.append({
                "id": r.id,
                "rating": r.rating,
                "content": r.content,
                "created_at": r.created_at.strftime("%Y-%m-%d"),
                "user_name": r.user.name if r.user else "Anonymous"
            })
            
        return result
    except Exception as e:
        return {"error": f"리뷰 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def create_review(
    product_id: str, 
    rating: int, 
    content: str,
    order_id: str = None
) -> dict:
    """
    리뷰를 작성합니다.
    
    Args:
        product_id: 상품 ID
        rating: 평점 (1-5)
        content: 리뷰 내용
        order_id: 주문번호 (선택)
        
    Returns:
        성공 여부, 메시지, 리뷰 ID
    """
    if not order_id:
        return {"error": "리뷰 작성을 위해 주문 번호가 필요합니다."}

    db = SessionLocal()
    try:
        # 1. Provide a temporary user ID since auth context is missing in tool
        # In production, pass user_id via tool arguments or context
        user_id = 1 
        
        # 2. Find Order Item to attach review to
        # We need to find an OrderItem in this order that matches the product_id
        # This is tricky because product_id might be generic, but OrderItem links to ProductOption.
        # We need to join ProductOption to check product_id.
        
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
             return {"error": "유효하지 않은 주문 번호입니다."}
             
        target_item = None
        for item in order.items:
            # Check if this item's option belongs to the product
            option = db.query(ProductOption).filter(ProductOption.id == item.product_option_id).first()
            if option and str(option.product_id) == str(product_id):
                target_item = item
                break
        
        if not target_item:
            return {"error": "해당 주문에서 구매한 상품이 아닙니다."}

        # 3. Create Review
        new_review = Review(
            user_id=user_id,
            order_item_id=target_item.id,
            rating=rating,
            content=content
        )
        db.add(new_review)
        db.commit()
        db.refresh(new_review)
        
        return {
            "success": True,
            "message": "리뷰가 성공적으로 등록되었습니다.",
            "review_id": new_review.id
        }

    except Exception as e:
        db.rollback()
        return {"error": f"리뷰 작성 실패: {str(e)}"}
    finally:
        db.close()

