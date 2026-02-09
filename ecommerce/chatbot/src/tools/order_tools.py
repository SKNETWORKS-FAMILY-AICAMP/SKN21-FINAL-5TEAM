"""
배송 및 주문 관련 Tools.
(Real DB Version)
"""

from langchain_core.tools import tool
from sqlalchemy.orm import Session
from datetime import datetime

from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.db.models import Order, OrderStatus, ShippingInfo
# Import other models to ensure SQLAlchemy registry is fully populated
from ecommerce.platform.backend.app.router.users.models import User
from ecommerce.platform.backend.app.router.shipping.models import ShippingAddress

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@tool
def get_order_details(order_id: str, user_id: int) -> dict:
    """
    주문 상세 정보를 조회합니다.
    
    Args:
        order_id: 주문번호 (예: ORD-20240209-0001)
        user_id: 요청자 사용자 ID (본인 확인용)
        
    Returns:
        주문 상태, 상품 목록, 금액, 환불 가능 여부 등
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
        
        # [Security] Authorization Check
        if order.user_id != user_id:
            return {"error": "PERMISSION_DENIED: 본인의 주문 정보만 조회할 수 있습니다."}
        
        items = []
        for item in order.items:
            items.append({
                "product_id": item.product_option_id,
                "quantity": item.quantity,
                "subtotal": float(item.subtotal)
            })

        return {
            "order_id": order.order_number,
            "status": order.status.value,
            "total_amount": float(order.total_amount),
            "items": items,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "shipping_address": getattr(order.shipping_address, "address1", "N/A"),
            "can_refund": order.status in [OrderStatus.DELIVERED, OrderStatus.PAID] 
        }
    except Exception as e:
        return {"error": f"조회 중 오류 발생: {str(e)}"}
    finally:
        db.close()


@tool
def request_refund(order_id: str, user_id: int, reason: str) -> dict:
    """
    환불을 요청합니다.
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 환불 사유
        
    Returns:
        환불 요청 결과 (성공 여부, 환불 금액 등)
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
        
        # [Security] Authorization Check
        if order.user_id != user_id:
            return {"error": "PERMISSION_DENIED: 본인의 주문만 환불 신청할 수 있습니다."}
        
        order.status = OrderStatus.REFUNDED
        order.shipping_request = f"Refund Requested: {reason}"
        db.commit()
        
        return {
            "success": True,
            "message": f"주문({order_id})에 대한 환불 요청이 접수되었습니다.",
            "refund_amount": float(order.total_amount)
        }
    except Exception as e:
        db.rollback()
        return {"error": f"환불 요청 실패: {str(e)}"}
    finally:
        db.close()


@tool
def get_delivery_status(order_id: str, user_id: int) -> dict:
    """
    주문 번호로 배송 현황을 조회합니다.
    
    Args:
        order_id: 주문번호
        
    Returns:
        배송 상태, 택배사, 송장번호, 현재 위치, 예상 도착일
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
            
        shipping_info = order.shipping_info
        if not shipping_info:
            return {"status": "배송 준비 중", "message": "아직 배송 정보가 등록되지 않았습니다."}
            
        return {
            "status": "배송 중" if order.status == OrderStatus.SHIPPED else order.status.value,
            "courier": shipping_info.courier_company,
            "tracking_number": shipping_info.tracking_number,
            "shipped_at": shipping_info.shipped_at.strftime("%Y-%m-%d") if shipping_info.shipped_at else None
        }
    except Exception as e:
        return {"error": f"배송 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def get_courier_contact(order_id: str) -> dict:
    """
    주문의 배송업체 연락처를 조회합니다.
    
    Args:
        order_id: 주문번호
        
    Returns:
        택배사명, 전화번호, 웹사이트
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
            
        shipping_info = order.shipping_info
        if not shipping_info:
            return {"error": "배송 정보가 없습니다."}
            
        # Mock contact info based on courier name
        courier = shipping_info.courier_company
        if courier == "FastDelivery":
            return {"courier": courier, "phone": "1588-0000", "website": "www.fastdelivery.com"}
        else:
            return {"courier": courier, "phone": "Unknown", "website": "Unknown"}
            
    except Exception as e:
        return {"error": f"택배사 정보 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def get_user_orders(user_id: int = 1, limit: int = 5) -> dict:
    """
    사용자의 최근 주문 목록을 조회합니다 (UI 렌더링용).
    
    Args:
        user_id: 사용자 ID (기본값 1)
        limit: 조회할 주문 개수
        
    Returns:
        주문 목록 및 각 주문별 가능 액션 (UI 데이터)
    """
    db = SessionLocal()
    try:
        orders = db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit).all()
        
        ui_data = []
        for order in orders:
            # Determine available actions based on status
            actions = ["tracking"] # Tracking is always available
            if order.status in [OrderStatus.PENDING, OrderStatus.PAID]:
                actions.append("cancel")
            if order.status in [OrderStatus.DELIVERED]:
                actions.append("refund")
                actions.append("review")
            
            # Get main product name
            product_name = "상품 정보 없음"
            if order.items:
                first_item = order.items[0]
                # In real app, join with Product/ProductOption to get name
                # Here we mock it or fetch if needed. 
                # Ideally, models should allow easy access.
                product_name = f"상품 {first_item.product_option_id} 등 {len(order.items)}건"

            ui_data.append({
                "order_id": order.order_number,
                "date": order.created_at.strftime("%Y-%m-%d"),
                "status": order.status.value,
                "product_name": product_name,
                "amount": float(order.total_amount),
                "available_actions": actions
            })
            
        return {
            "ui_action": "show_order_list",
            "message": "최근 주문 내역입니다. 원하시는 주문을 선택해주세요.",
            "ui_data": ui_data
        }
    except Exception as e:
        return {"error": f"주문 목록 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def update_payment_info(order_id: str, payment_method: str, card_number: str = None) -> dict:
    """
    주문의 결제 정보를 변경합니다.
    
    Args:
        order_id: 주문번호
        payment_method: 결제 수단 (카드/계좌이체/무통장입금)
        card_number: 카드번호 (카드 결제 시)
        
    Returns:
        성공 여부, 메시지, 새로운 결제 수단
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
            
        order.payment_method = payment_method
        db.commit()
        
        return {
            "success": True, 
            "message": "결제 정보가 업데이트되었습니다.", 
            "new_payment_method": payment_method
        }
    except Exception as e:
        db.rollback()
        return {"error": f"결제 정보 수정 실패: {str(e)}"}
    finally:
        db.close()