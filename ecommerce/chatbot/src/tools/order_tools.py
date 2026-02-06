from langchain_core.tools import tool

@tool
def check_order_status(order_id: str):
    """주문 번호로 배송 상태를 조회합니다."""
    # 실제 DB 조회 로직
    return {"status": "배송중", "location": "대전HUB"}