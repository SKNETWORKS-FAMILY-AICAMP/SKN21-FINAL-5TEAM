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
    """DB 세션 생성 (generator)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================
# Helper Functions (Internal Use)
# ============================================

def _get_order_with_auth(db: Session, order_id: str, user_id: int) -> tuple[Order | None, dict | None]:
    """
    주문을 조회하고 권한을 체크합니다.
    
    Args:
        db: DB 세션
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        
    Returns:
        (Order 객체, None) 성공 시
        (None, error dict) 실패 시
    """
    order = db.query(Order).filter(Order.order_number == order_id).first()
    
    if not order:
        return None, {"error": "주문 정보를 찾을 수 없습니다."}
    
    # [Security] Authorization Check
    if order.user_id != user_id:
        return None, {"error": "PERMISSION_DENIED: 본인의 주문만 접근할 수 있습니다."}
    
    return order, None



def _get_order_actions(order: Order) -> dict:
    """
    주문의 가능한 액션(취소/반품/교환)을 판단합니다.
    
    Args:
        order: Order 객체
        
    Returns:
        취소/반품/교환 가능 여부 및 사유
    """
    actions = {
        "can_cancel": False,
        "can_return": False,
        "can_exchange": False,
        "cancel_reason": None,
        "return_reason": None,
        "exchange_reason": None,
        "exchange_type": None  # pre_shipment / post_shipment
    }
    
    # 1. 취소 가능 여부 (배송 전)
    if order.status in [OrderStatus.PENDING, OrderStatus.PAID]:
        actions["can_cancel"] = True
    else:
        actions["cancel_reason"] = f"현재 상태({order.status.value})에서는 취소가 불가능합니다. (배송 시작됨)"
    
    # 2. 반품 가능 여부 (배송 후)
    if order.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
        # 배송완료 상태인 경우 7일 제한 확인
        if order.status == OrderStatus.DELIVERED and order.shipping_info:
            is_valid, error_msg = _check_return_period(order.shipping_info.delivered_at)
            if is_valid:
                actions["can_return"] = True
            else:
                actions["return_reason"] = error_msg
        else:
            # SHIPPED 상태에서는 반품 접수 가능 (단, 배송완료 후 수거)
            actions["can_return"] = True
    else:
        actions["return_reason"] = f"현재 상태({order.status.value})에서는 반품이 불가능합니다. (배송 전)"
    
    # 3. 교환 가능 여부 (배송 전/후)
    if order.status not in [OrderStatus.CANCELLED, OrderStatus.REFUNDED]:
        if order.status in [OrderStatus.PENDING, OrderStatus.PAID]:
            actions["can_exchange"] = True
            actions["exchange_type"] = "pre_shipment"
        elif order.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            if order.status == OrderStatus.DELIVERED and order.shipping_info:
                is_valid, error_msg = _check_return_period(order.shipping_info.delivered_at)
                if is_valid:
                    actions["can_exchange"] = True
                    actions["exchange_type"] = "post_shipment"
                else:
                    actions["exchange_reason"] = error_msg
            else:
                actions["can_exchange"] = True
                actions["exchange_type"] = "post_shipment"
    else:
        actions["exchange_reason"] = f"현재 상태({order.status.value})에서는 교환이 불가능합니다."
    
    return actions

@tool
def get_order_details(order_id: str, user_id: int) -> dict:
    """
    주문 상세 정보를 조회합니다.
    
    Args:
        order_id: 주문번호 (예: ORD-20240209-0001)
        user_id: 요청자 사용자 ID (본인 확인용)
        
    Returns:
        주문 상태, 상품 목록, 금액, 취소/반품/교환 가능 여부 등
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
        
        items = []
        for item in order.items:
            items.append({
                "product_id": item.product_option_id,
                "quantity": item.quantity,
                "subtotal": float(item.subtotal)
            })
        
        # 가능한 액션 판단
        actions = _get_order_actions(order)

        return {
            "order_id": order.order_number,
            "status": order.status.value,
            "total_amount": float(order.total_amount),
            "items": items,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "shipping_address": getattr(order.shipping_address, "address1", "N/A"),
            "delivered_at": order.shipping_info.delivered_at.strftime("%Y-%m-%d %H:%M:%S") if order.shipping_info and order.shipping_info.delivered_at else None,
            **actions
        }
    except Exception as e:
        return {"error": f"조회 중 오류 발생: {str(e)}"}
    finally:
        db.close()


def _check_return_period(delivered_at: datetime | None) -> tuple[bool, str | None]:
    """
    배송완료일로부터 7일 이내인지 검증합니다.
    
    Args:
        delivered_at: 배송완료 일시
        
    Returns:
        (검증 성공 여부, 에러 메시지)
    """
    if not delivered_at:
        return False, "배송완료 정보가 없습니다. 배송 완료 후 환불/교환이 가능합니다."
    
    from datetime import timedelta
    days_since_delivery = (datetime.now() - delivered_at).days
    
    if days_since_delivery > 7:
        return False, f"배송완료일로부터 7일이 경과하여 환불/교환이 불가능합니다. (배송완료: {delivered_at.strftime('%Y-%m-%d')}, 경과일: {days_since_delivery}일)"
    
    return True, None


@tool
def check_cancellation(order_id: str, user_id: int) -> dict:
    """
    취소 가능 여부와 환불 예정 금액을 확인합니다 (배송 전 전용).
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        
    Returns:
        취소 가능 여부, 환불 예정 금액(전액), 안내 메시지
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
        
        # 배송 전 상태 확인
        if order.status not in [OrderStatus.PENDING, OrderStatus.PAID]:
            return {
                "error": f"현재 주문 상태({order.status.value})에서는 취소가 불가능합니다. 배송이 시작된 경우 반품을 이용해주세요."
            }
        
        return {
            "eligible": True,
            "order_id": order_id,
            "current_status": order.status.value,
            "refund_amount": float(order.total_amount),
            "message": (
                f"취소 가능 여부 확인 완료\n"
                f"주문 금액 {float(order.total_amount):,.0f}원이 전액 환불됩니다.\n"
                f"정말 취소하시겠습니까?"
            ),
            "requires_confirmation": True
        }
    except Exception as e:
        return {"error": f"취소 가능 여부 확인 실패: {str(e)}"}
    finally:
        db.close()


@tool
def cancel_order(order_id: str, user_id: int, reason: str, confirmed: bool = True) -> dict:
    """
    주문을 취소합니다 (배송 전, 즉시 실행).
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 취소 사유
        confirmed: 사용자 확인 여부
        
    Returns:
        취소 처리 결과
    """
    db = SessionLocal()
    try:
        if not confirmed:
            return {"success": False, "message": "주문 취소가 중단되었습니다."}
            
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
            
        if order.status not in [OrderStatus.PENDING, OrderStatus.PAID]:
            return {"error": "배송이 시작되어 취소할 수 없습니다."}
            
        order.status = OrderStatus.CANCELLED
        order.shipping_request = f"Cancelled by user: {reason}"
        db.commit()
        
        return {
            "success": True,
            "message": f"주문({order_id})이 성공적으로 취소되었습니다.",
            "status": "cancelled",
            "refund_amount": float(order.total_amount)
        }
    except Exception as e:
        db.rollback()
        return {"error": f"주문 취소 실패: {str(e)}"}
    finally:
        db.close()


@tool
def check_return_eligibility(
    order_id: str, 
    user_id: int, 
    reason: str,
    is_seller_fault: bool = False
) -> dict:
    """
    반품(환불) 가능 여부와 배송비를 계산합니다 (배송 후 전용).
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 반품 사유
        is_seller_fault: 판매자 귀책 여부 (True: 판매자 귀책, False: 구매자 귀책)
        
    Returns:
        반품 가능 여부, 배송비 차감 내역, 최종 환불 예정 금액
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
        
        # 배송 후 상태 확인 (배송중/배송완료)
        if order.status not in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
             return {
                "error": f"현재 주문 상태({order.status.value})에서는 반품 처리가 불가능합니다. (배송 전 취소 이용 권장)"
            }
        
        # 배송완료일 기준 7일 이내 검증
        if order.status == OrderStatus.DELIVERED and order.shipping_info:
            is_valid, error_msg = _check_return_period(order.shipping_info.delivered_at)
            if not is_valid:
                return {"error": error_msg}
        
        # 귀책사유에 따른 배송비 계산
        shipping_fee = float(order.shipping_fee)
        return_shipping_fee = 0.0
        
        if is_seller_fault:
            return_shipping_fee = 0.0
            refund_amount = float(order.total_amount)
            responsibility = "판매자"
        else:
            return_shipping_fee = shipping_fee * 2  # 왕복 배송비
            refund_amount = float(order.total_amount) - return_shipping_fee
            responsibility = "구매자"
        
        final_refund = max(0, refund_amount)
        
        return {
            "eligible": True,
            "order_id": order_id,
            "reason": reason,
            "responsibility": responsibility,
            "original_amount": float(order.total_amount),
            "return_shipping_fee": return_shipping_fee,
            "final_refund_amount": final_refund,
            "message": (
                f"반품 가능 여부 확인 완료\n"
                f"- 귀책사유: {responsibility}\n"
                f"- 반품 배송비: {return_shipping_fee:,.0f}원 차감\n"
                f"- 최종 환불 예정 금액: {final_refund:,.0f}원\n\n"
                f"반품 접수를 진행하시겠습니까?"
            ),
            "requires_confirmation": True
        }
    except Exception as e:
        return {"error": f"반품 확인 실패: {str(e)}"}
    finally:
        db.close()


@tool
def register_return_request(
    order_id: str, 
    user_id: int, 
    pickup_address: str, 
    confirmed: bool = True
) -> dict:
    """
    반품을 접수합니다 (배송 후, 수거지 정보 포함).
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        pickup_address: 반품 수거지 주소
        confirmed: 사용자 확인 여부
        
    Returns:
        반품 접수 결과
    """
    db = SessionLocal()
    try:
        if not confirmed:
            return {"success": False, "message": "반품 접수가 취소되었습니다."}
        
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
            
        if order.status not in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            return {"error": "배송이 완료되지 않아 반품을 접수할 수 없습니다."}
        
        # 반품 접수 상태로 변경 (REFUNDED로 바로 가는 것이 아니라, 반품 요청 상태로 둬야 하지만 
        # 현재 모델에는 RETURN_REQUESTED 상태가 없으므로 REFUNDED로 처리하되 메모를 남김)
        order.status = OrderStatus.REFUNDED
        order.shipping_request = f"Return Requested. Pickup: {pickup_address}"
        db.commit()
        
        return {
            "success": True,
            "message": f"반품 접수가 완료되었습니다. 택배기사님이 {pickup_address}로 방문할 예정입니다.",
            "status": "refunded (return requested)",
            "pickup_address": pickup_address
        }
    except Exception as e:
        db.rollback()
        return {"error": f"반품 접수 실패: {str(e)}"}
    finally:
        db.close()


@tool
def check_exchange_eligibility(
    order_id: str,
    user_id: int,
    reason: str,
    new_option_id: int = None
) -> dict:
    """
    교환 가능 재고 확인 및 배송비를 계산합니다.
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 교환 사유
        new_option_id: 교환할 새로운 옵션 ID
        
    Returns:
        교환 가능 여부, 추천 Action Tool (배송 전: change_product_option, 배송 후: register_exchange_request)
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
        
        # 교환 불가 상태
        if order.status in [OrderStatus.CANCELLED, OrderStatus.REFUNDED]:
            return {"error": "취소/환불된 주문은 교환할 수 없습니다."}
            
        # 1. 배송 전 -> 단순 옵션 변경
        if order.status in [OrderStatus.PENDING, OrderStatus.PAID]:
            return {
                "eligible": True,
                "type": "pre_shipment",
                "recommended_tool": "change_product_option",
                "message": (
                    f"교환 가능 여부 확인 완료 (배송 전 교환)\n"
                    f"- 교환 사유: {reason}\n"
                    f"배송 전 상태입니다. 무료로 옵션을 변경할 수 있습니다.\n"
                    f"변경할 옵션 ID: {new_option_id if new_option_id else '미지정'}"
                ),
                "additional_fee": 0
            }
            
        # 2. 배송 후 -> 반품 후 재배송
        if order.status in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
            if order.status == OrderStatus.DELIVERED and order.shipping_info:
                is_valid, error_msg = _check_return_period(order.shipping_info.delivered_at)
                if not is_valid:
                    return {"error": error_msg}
            
            shipping_fee = float(order.shipping_fee)
            exchange_fee = shipping_fee * 2
            
            return {
                "eligible": True,
                "type": "post_shipment",
                "recommended_tool": "register_exchange_request",
                "message": (
                    f"교환 가능 여부 확인 완료 (배송 후 교환)\n"
                    f"- 교환 사유: {reason}\n"
                    f"배송이 시작된 상태입니다. 맞교환으로 진행됩니다.\n"
                    f"왕복 배송비 {exchange_fee:,.0f}원이 발생합니다."
                ),
                "exchange_fee": exchange_fee
            }
            
        return {"error": "알 수 없는 주문 상태입니다."}
    except Exception as e:
        return {"error": f"교환 확인 실패: {str(e)}"}
    finally:
        db.close()


@tool
def change_product_option(order_id: str, user_id: int, new_option_id: int) -> dict:
    """
    주문 옵션을 변경합니다 (배송 전 전용).
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        new_option_id: 변경할 옵션 ID
        
    Returns:
        변경 결과
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
            
        if order.status not in [OrderStatus.PENDING, OrderStatus.PAID]:
            return {"error": "배송이 시작되어 옵션을 변경할 수 없습니다. 교환 신청을 이용해주세요."}
            
        # 실제로는 여기서 재고 확인 및 OrderItem 업데이트 로직이 들어가야 함
        # 현재는 Mock 처리
        order.shipping_request = f"Option changed to {new_option_id}"
        db.commit()
        
        return {
            "success": True,
            "message": f"주문 옵션이 ID {new_option_id}(으)로 변경되었습니다.",
            "status": "updated"
        }
    except Exception as e:
        db.rollback()
        return {"error": f"옵션 변경 실패: {str(e)}"}
    finally:
        db.close()


@tool
def register_exchange_request(
    order_id: str,
    user_id: int,
    reason: str,
    pickup_address: str,
    new_option_id: int = None,
    confirmed: bool = True
) -> dict:
    """
    교환을 접수합니다 (배송 후, 회수/재배송).
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        reason: 교환 사유
        pickup_address: 반품 수거지 주소
        new_option_id: 교환할 새로운 옵션 ID
        confirmed: 사용자 확인 여부
        
    Returns:
        교환 접수 결과
    """
    db = SessionLocal()
    try:
        if not confirmed:
            return {"success": False, "message": "교환 접수가 취소되었습니다."}
            
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
            
        if order.status not in [OrderStatus.SHIPPED, OrderStatus.DELIVERED]:
             return {"error": "배송 전입니다. 옵션 변경 기능을 이용해주세요."}
             
        # 상태 변경
        previous_status = order.status
        order.status = OrderStatus.PROCESSING
        order.shipping_request = (
            f"Exchange Requested. Reason: {reason}, "
            f"Pickup: {pickup_address}, New Option: {new_option_id}"
        )
        db.commit()
        
        return {
            "success": True,
            "message": "교환 접수가 완료되었습니다. 수거 및 재배송이 진행됩니다.",
            "previous_status": previous_status.value,
            "current_status": "processing (exchange)",
            "pickup_address": pickup_address
        }
    except Exception as e:
        db.rollback()
        return {"error": f"교환 접수 실패: {str(e)}"}
    finally:
        db.close()


@tool
def get_shipping_details(order_id: str, user_id: int) -> dict:
    """
    주문의 배송 현황과 택배사 정보를 통합 조회합니다.
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        
    Returns:
        배송 상태, 현재 위치, 예상 도착일, 택배사 정보(이름/전화번호) 등
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
            
        shipping_info = order.shipping_info
        if not shipping_info:
            return {"status": "배송 준비 중", "message": "아직 배송 정보가 등록되지 않았습니다."}
            
        # Mock contact info based on courier name
        courier = shipping_info.courier_company
        courier_phone = "Unknown"
        courier_website = "Unknown"
        
        if courier == "FastDelivery":
            courier_phone = "1588-0000"
            courier_website = "www.fastdelivery.com"
            
        return {
            "status": "배송 중" if order.status == OrderStatus.SHIPPED else order.status.value,
            "tracking_number": shipping_info.tracking_number,
            "shipped_at": shipping_info.shipped_at.strftime("%Y-%m-%d") if shipping_info.shipped_at else None,
            "courier_name": courier,
            "courier_phone": courier_phone,
            "courier_website": courier_website,
            "current_location": "대전 Hub (가상)",  # Mock Data
            "estimated_delivery": "내일 도착 예정"   # Mock Data
        }
    except Exception as e:
        return {"error": f"배송 정보 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def get_user_orders(user_id: int = 1, limit: int = 5, days: int = 30) -> dict:
    """
    사용자의 최근 주문 목록을 조회합니다 (UI 렌더링용).
    
    Args:
        user_id: 사용자 ID (기본값 1)
        limit: 조회할 주문 개수
        days: 조회 기간 (기본값 30일)
        
    Returns:
        주문 목록 및 각 주문별 환불/교환/취소 가능 여부 (UI 데이터)
    """
    from datetime import timedelta
    
    db = SessionLocal()
    try:
        # 최근 N일 이내 주문 조회
        cutoff_date = datetime.now() - timedelta(days=days)
        orders = (
            db.query(Order)
            .filter(Order.user_id == user_id)
            .filter(Order.created_at >= cutoff_date)
            .order_by(Order.created_at.desc())
            .limit(limit)
            .all()
        )
        
        ui_data = []
        for order in orders:
            # 가능한 액션 판단
            order_actions = _get_order_actions(order)
            
            # Get main product name
            product_name = "상품 정보 없음"
            if order.items:
                first_item = order.items[0]
                product_name = f"상품 {first_item.product_option_id} 등 {len(order.items)}건"

            ui_data.append({
                "order_id": order.order_number,
                "date": order.created_at.strftime("%Y-%m-%d"),
                "status": order.status.value,
                "product_name": product_name,
                "amount": float(order.total_amount),
                "delivered_at": order.shipping_info.delivered_at.strftime("%Y-%m-%d") if order.shipping_info and order.shipping_info.delivered_at else None,
                **order_actions  # 환불/교환/취소 가능 여부 포함
            })
            
        return {
            "ui_action": "show_order_list",
            "message": f"최근 {days}일 이내 주문 내역입니다. 원하시는 주문을 선택해주세요.",
            "total_orders": len(ui_data),
            "ui_data": ui_data
        }
    except Exception as e:
        return {"error": f"주문 목록 조회 실패: {str(e)}"}
    finally:
        db.close()


@tool
def update_payment_method(order_id: str, user_id: int, payment_method: str, card_number: str = None) -> dict:
    """
    주문의 결제 정보를 변경합니다.
    
    Args:
        order_id: 주문번호
        user_id: 요청자 사용자 ID
        payment_method: 결제 수단 (카드/계좌이체/무통장입금)
        card_number: 카드번호 (카드 결제 시, 마스킹 처리 권장)
        
    Returns:
        성공 여부, 메시지, 새로운 결제 수단
    """
    db = SessionLocal()
    try:
        order, error = _get_order_with_auth(db, order_id, user_id)
        if error:
            return error
            
        order.payment_method = payment_method
        if card_number:
            order.card_number = card_number
        db.commit()
        
        return {
            "success": True, 
            "message": "결제 정보가 업데이트되었습니다.", 
            "new_payment_method": payment_method,
            "card_number_updated": card_number is not None
        }
    except Exception as e:
        db.rollback()
        return {"error": f"결제 정보 수정 실패: {str(e)}"}
    finally:
        db.close()