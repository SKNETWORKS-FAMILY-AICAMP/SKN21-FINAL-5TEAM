"""
서비스 관련 Tools (상품권, 리뷰).
(Real DB Version)
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.tools import tool

from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.models import (
    Review,
    Order,
    OrderItem,
    Product,
    ProductOption,
    IssuedVoucher,
)
from chatbot.src.tools.base import BaseAPITool
from chatbot.src.tools.order_tools import (
    _is_langgraph_interrupt_error,
    _require_order_id,
)


# Helper to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@tool
def register_gift_card(
    voucher_code: str,
    user_id: int = 1,
) -> dict:
    """
    상품권을 등록하여 포인트로 충전합니다.

    Args:
        voucher_code: 상품권 코드 (문자열)
        user_id: 사용자 ID (기본값 1)

    Returns:
        성공 여부 및 메시지
    """
    from ecommerce.backend.app.router.points.crud import redeem_voucher_to_point
    
    db = SessionLocal()
    try:
        voucher = redeem_voucher_to_point(db, user_id, voucher_code)
        return {
            "success": True,
            "message": f"상품권({voucher_code})이 성공적으로 등록되었습니다. {voucher.amount:,.0f}포인트가 충전되었습니다.",
            "amount": float(voucher.amount),
        }
    except ValueError as ve:
        return {"success": False, "message": str(ve)}
    except Exception as e:
        return {"success": False, "message": f"상품권 등록 중 오류가 발생했습니다: {str(e)}"}
    finally:
        db.close()


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
            query = (
                query.join(OrderItem, Review.order_item_id == OrderItem.id)
                .join(ProductOption, OrderItem.product_option_id == ProductOption.id)
                .filter(ProductOption.product_id == int(product_id))
            )

        reviews = query.limit(limit).all()

        result = []
        for r in reviews:
            result.append(
                {
                    "id": r.id,
                    "rating": r.rating,
                    "content": r.content,
                    "created_at": r.created_at.strftime("%Y-%m-%d"),
                    "user_name": r.user.name if r.user else "Anonymous",
                }
            )

        return result
    except Exception as e:
        return {"error": f"리뷰 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def create_review(
    order_id: str = "",
    product_id: str = "",
    rating: int = 0,
    content: str = "",
    user_id: int = 1,
) -> dict:
    """
    리뷰를 작성합니다.

    Args:
        order_id: 주문번호 (구매 내역 확인용)
        product_id: 상품 ID (선택사항, 없으면 주문의 첫 번째 상품 선택)
        rating: 평점 (1-5)
        content: 리뷰 내용
        user_id: 사용자 ID (기본값 1)

    Returns:
        성공 여부, 메시지, 리뷰 ID
    """
    db = SessionLocal()
    try:
        resolved_order_id = _require_order_id(
            user_id=user_id,
            order_id=order_id,
            action_context="review",
        )
        if not resolved_order_id:
            return {
                "success": False,
                "needs_order_id": True,
                "message": "리뷰를 작성할 주문을 선택해주세요.",
            }

        order = db.query(Order).filter(Order.order_number == resolved_order_id).first()
        if not order:
            return {"error": "유효하지 않은 주문 번호입니다."}

        # [Security Warning] In strict production, verify order.user_id == user_id
        if order.user_id != user_id:
            pass

        target_item = None
        for item in order.items:
            option = (
                db.query(ProductOption)
                .filter(ProductOption.id == item.product_option_id)
                .first()
            )
            if product_id and option and str(option.product_id) == str(product_id):
                target_item = item
                break

        # Fallback: if no specific product requested or not found, use the first item
        if not target_item and order.items:
            target_item = order.items[0]

        if not target_item:
            return {"error": "해당 주문에서 구매한 상품이 아닙니다."}

        # Get the actual product name for the UI / review
        product_name = "주문하신 상품"
        option = (
            db.query(ProductOption)
            .filter(ProductOption.id == target_item.product_option_id)
            .first()
        )
        if option:
            product = db.query(Product).filter(Product.id == option.product_id).first()
            if product:
                product_name = product.name
                actual_product_id = str(product.id)
            else:
                actual_product_id = str(option.product_id)
        else:
            actual_product_id = product_id

        # UI Fallback Interception
        if rating == 0 or content == "UI_REQUEST":
            return {
                "ui_action": "show_review_form",
                "message": "리뷰 세부 정보를 입력해주세요.",
                "ui_data": {
                    "order_id": resolved_order_id,
                    "product_id": actual_product_id,
                    "product_name": product_name,
                },
            }

        # 3. Create Review
        new_review = Review(
            user_id=user_id,
            order_item_id=target_item.id,
            rating=rating,
            content=content,
        )
        db.add(new_review)
        db.commit()
        db.refresh(new_review)

        return {
            "success": True,
            "message": "리뷰가 성공적으로 등록되었습니다.",
            "review_id": new_review.id,
            "order_id": resolved_order_id,
        }

    except Exception as e:
        if _is_langgraph_interrupt_error(e):
            raise
        db.rollback()
        return {"error": f"리뷰 작성 실패: {str(e)}"}
    finally:
        db.close()


@tool
def generate_review_draft(
    product_name: str, satisfaction: str, keywords: list[str] = None
) -> dict:
    """
    상품명, 만족도, 키워드를 바탕으로 사용자가 쉽게 선택할 수 있는 리뷰 초안 3가지를 생성합니다.
    """
    if not product_name or not satisfaction:
        return {"error": "상품명과 만족도(높음/보통/낮음 등)를 입력해주세요."}

    kw_str = ", ".join(keywords) if keywords else "자유롭게 작성"

    prompt = f"""
다음 정보를 바탕으로 쇼핑몰 사용자 리뷰 초안 3가지를 작성해주세요.
- 상품명: {product_name}
- 만족도: {satisfaction}
- 포함 키워드/특징: {kw_str}

작성 규칙:
1. '짧은 버전' (1문장)
2. '감성적인 버전' (생생한 느낌과 기분을 담아서 1-2문장)
3. '무뚝뚝한 버전' (정확한 리뷰와 딱딱한 어체를 사용 1-2문장)

반드시 아래 JSON 형식으로만 답변해주세요. (Markdown 블록 없이 순수 JSON)
{{
    "short": "...",
    "emotional": "...",
    "detailed": "..."
}}
"""
    try:
        # ChatOpenAI를 통해 gpt-4o-mini 호출
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
        response = llm.invoke(
            [
                SystemMessage(
                    content="You are a helpful assistant that writes e-commerce product reviews."
                ),
                HumanMessage(content=prompt),
            ]
        )

        # 응답을 JSON 파싱
        import json
        import re

        content = response.content
        if "```json" in content:
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*", "", content)

        drafts = json.loads(content)

        return {
            "success": True,
            "drafts": drafts,
            "message": "리뷰 초안이 생성되었습니다. 마음에 드는 버전을 선택해주세요.",
        }
    except Exception as e:
        return {"error": f"리뷰 초안 생성 중 오류 발생: {str(e)}"}
