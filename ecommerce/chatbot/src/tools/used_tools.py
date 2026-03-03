import uuid
from langchain_core.tools import tool


@tool
def register_used_sale(
    category: str,
    item_name: str,
    condition: str,  # 최상, 상, 중 등
    expected_price: int = None,
    user_id: int = 1,
) -> dict:
    """
    유즈드(중고) 판매 신청을 등록합니다.
    사용자로부터 중고 물품의 카테고리, 상품명, 상태(최상/상/중), 희망 가격을 입력받아 접수합니다.
    """

    # 1. Validation
    if not item_name or not condition:
        return {"error": "상품명과 상태(최상/상/중) 정보는 필수입니다."}

    valid_conditions = ["최상", "상", "중", "하"]
    if condition not in valid_conditions:
        return {
            "error": f"상태는 다음 중 하나여야 합니다: {', '.join(valid_conditions)}"
        }

    # 2. Generate tracking ID
    tracking_id = f"USED-{str(uuid.uuid4())[:8].upper()}"

    return {
        "success": True,
        "message": f"'{item_name}' 상품의 중고 판매가 접수되었습니다. (희망가: {expected_price or '미정'})",
        "tracking_id": tracking_id,
        "next_steps": "검수 센터로 상품을 보내주시거나 수거 신청(request_pickup)을 진행해주세요.",
    }


@tool
def request_pickup(
    sale_id: str,  # 판매 신청 ID
    pickup_date: str,
    pickup_address: str,
    user_id: int = 1,
) -> dict:
    """
    중고 판매 물품의 수거를 신청합니다.
    """
    if not sale_id:
        return {"error": "판매 신청 접수 번호(sale_id)가 필요합니다."}

    if not pickup_date or not pickup_address:
        return {"error": "수거 희망 날짜와 주소를 모두 입력해주세요."}

    return {
        "success": True,
        "message": f"수거 신청 완료: {pickup_date}에 '{pickup_address}'(으)로 방문 예정입니다.",
        "sale_id": sale_id,
        "status": "수거 대기중",
    }
