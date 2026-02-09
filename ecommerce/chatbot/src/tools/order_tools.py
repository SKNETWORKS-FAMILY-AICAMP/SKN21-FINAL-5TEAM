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
def get_order_details(order_id: str) -> dict:
    """
    주문 상세 정보를 조회합니다.
    
    Args:
        order_id: 주문번호 (예: ORD-20240209-0001)
        
    Returns:
        주문 상태, 상품 목록, 금액, 환불 가능 여부 등
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
        
        items = []
        for item in order.items:
            # item.product_option_id allows finding product name if needed, 
            # but usually getting option details requires joining ProductOption & Product.
            # For simplicity, returning basic info.
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
            "shipping_address": getattr(order.shipping_address, "address1", "N/A")
        }
    except Exception as e:
        return {"error": f"조회 중 오류 발생: {str(e)}"}
    finally:
        db.close()


@tool
def request_refund(order_id: str, reason: str) -> dict:
    """
    환불을 요청합니다.
    
    Args:
        order_id: 주문번호
        reason: 환불 사유
        
    Returns:
        환불 요청 결과 (성공 여부, 환불 금액 등)
    """
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.order_number == order_id).first()
        if not order:
            return {"error": "주문 정보를 찾을 수 없습니다."}
        
        # Simple Logic: Update status directly
        # In real world, might need a RefundRequest model
        order.status = OrderStatus.REFUNDED
        order.shipping_request = f"Refund Requested: {reason}" # Storing reason in notes for now
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
def get_delivery_status(order_id: str) -> dict:
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