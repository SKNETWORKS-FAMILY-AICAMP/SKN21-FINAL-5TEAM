# used_tools.py (신규 생성)

@tool
def register_used_sale(
    user_id: int,
    category: str,
    item_name: str,
    condition: str, # 최상, 상, 중 등
    expected_price: int = None
) -> dict:
    """
    유즈드(중고) 판매 신청을 등록합니다.
    기획안 10번: 판매정보 입력 요청 -> DB 저장
    """
    pass

@tool
def request_pickup(
    sale_id: str, # 판매 신청 ID
    user_id: int,
    pickup_date: str,
    pickup_address: str
) -> dict:
    """
    중고 판매 물품의 수거를 신청합니다.
    기획안 11번: 판매 등록 여부 확인 -> 수거 신청
    """
    pass