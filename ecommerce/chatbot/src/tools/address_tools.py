from langchain_core.tools import tool

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
