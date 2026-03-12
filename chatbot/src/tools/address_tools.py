from langchain_core.tools import tool

from ecommerce.backend.app.database import SessionLocal
from ecommerce.backend.app.models import ShippingAddress, User

@tool
def open_address_search() -> dict:
    """
    [CRITICAL] 사용자로부터 주소를 입력받아야 할 때 사용하는 도구입니다.
    사용자에게 텍스트로 주소를 묻는 대신, 반드시 이 도구를 호출하여 주소 검색 팝업을 띄워야 합니다.
    반품 수거지, 배송지 변경 등 주소가 필요한 모든 상황에서 즉시 호출하세요.
    
    Returns:
        UI Action payload forcing the frontend to open the address search popup.
    """
    return {
        "ui_action": "show_address_search",
        "message": "주소 검색 버튼을 눌러주세요."
    }


@tool
def save_shipping_address_from_ui(
    user_id: int,
    road_address: str | None = None,
    jibun_address: str | None = None,
    post_code: str | None = None,
    detail_address: str | None = None,
    recipient_name: str | None = None,
    phone: str | None = None,
    is_default: bool = False,
) -> dict:
    """
    주소 검색 UI에서 선택한 주소(도로명/지번/우편번호)와 상세주소를 저장합니다.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"error": "사용자 정보를 찾을 수 없습니다."}

        base_address = (road_address or "").strip() or (jibun_address or "").strip()
        if not base_address:
            return {"error": "주소 정보가 비어 있습니다. 도로명 또는 지번 주소가 필요합니다."}

        resolved_recipient = (recipient_name or user.name or "수령인").strip()
        resolved_phone = (phone or user.phone or "010-0000-0000").strip()
        resolved_post_code = (post_code or "00000").strip()
        resolved_detail = (detail_address or "").strip() or None

        if is_default:
            db.query(ShippingAddress).filter(
                ShippingAddress.user_id == user_id,
                ShippingAddress.is_default.is_(True),
                ShippingAddress.deleted_at.is_(None),
            ).update({"is_default": False})

        new_address = ShippingAddress(
            user_id=user_id,
            recipient_name=resolved_recipient[:100],
            address1=base_address[:255],
            address2=resolved_detail[:255] if resolved_detail else None,
            post_code=resolved_post_code[:10],
            phone=resolved_phone[:20],
            is_default=is_default,
        )

        db.add(new_address)
        db.commit()
        db.refresh(new_address)

        full_address = f"{base_address} {resolved_detail}".strip() if resolved_detail else base_address

        return {
            "success": True,
            "message": "주소가 저장되었습니다.",
            "address_id": new_address.id,
            "address": {
                "road_address": (road_address or None),
                "jibun_address": (jibun_address or None),
                "post_code": resolved_post_code,
                "detail_address": resolved_detail,
                "full_address": full_address,
            },
        }
    except Exception as e:
        db.rollback()
        return {"error": f"주소 저장 중 오류가 발생했습니다: {str(e)}"}
    finally:
        db.close()
