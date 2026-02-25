
import json
import os

def create_case(num, query, gt_name, gt_args, tools_def):
    return {
        "function_num": num,
        "function_name": gt_name,
        "query": [{"serial_num": num, "content": query}],
        "ground_truth": [{"serial_num": num, "content": json.dumps({"name": gt_name, "arguments": gt_args}, ensure_ascii=False)}],
        "tools": [{"type": "exact", "content": tools_def}],
        "function_info": {"required_parameters_count": len(gt_args), "optional_parameters_count": 0, "parameter_type": [], "extraction_type": "단순추출"},
        "acceptable_arguments": [{"serial_num": num, "content": None}]
    }

def main():
    base_dir = os.path.dirname(__file__)
    with open(os.path.join(base_dir, "tools.json"), "r", encoding="utf-8") as f:
        tools_def = json.load(f)

    today_str = "20260219"
    sc_data = [
        # 1-20
        ("내 최근 주문 목록 보여줘", "get_user_orders", {"limit": 5, "user_id": 1}),
        (f"ORD-{today_str}-0001 이거 주문 상세 보여줘", "get_order_details", {"order_id": f"ORD-{today_str}-0001", "user_id": 1}),
        (f"배송 언제 와? ORD-{today_str}-0001", "get_shipping_details", {"order_id": f"ORD-{today_str}-0001", "user_id": 1}),
        (f"ORD-{today_str}-0001 취소해줘 단순변심이야", "cancel_order", {"order_id": f"ORD-{today_str}-0001", "reason": "단순변심", "user_id": 1}),
        (f"ORD-{today_str}-0002 환불 할 수 있어? 사유는 색상이 맘에 안 들어", "check_refund_eligibility", {"order_id": f"ORD-{today_str}-0002", "reason": "색상이 맘에 안 들어", "user_id": 1}),
        (f"ORD-{today_str}-0003 결제수단 신용카드로 바꿀래", "update_payment_method", {"order_id": f"ORD-{today_str}-0003", "payment_method": "신용카드", "user_id": 1}),
        ("상품 ID 505 리뷰 쓴 거 보여줘", "get_reviews", {"product_id": "505"}),
        (f"ORD-{today_str}-0001에서 신발 사이즈 270(ID 10)으로 변경 가능한가요?", "change_product_option", {"order_id": f"ORD-{today_str}-0001", "new_option_id": 10, "user_id": 1}),
        ("금액권 등록할래 번호는 GIFT-999-888이야", "register_gift_card", {"code": "GIFT-999-888", "user_id": 1}),
        (f"ORD-{today_str}-0002 반품 접수해줘 주소는 서울시 강남구 삼성동 100번지야", "register_return_request", {"order_id": f"ORD-{today_str}-0002", "pickup_address": "서울시 강남구 삼성동 100번지", "user_id": 1, "confirmed": True}),
        (f"교환 신청하려는데 ORD-{today_str}-0003, 사이즈가 너무 작아서 280으로 바꾸고 싶어", "check_exchange_eligibility", {"order_id": f"ORD-{today_str}-0003", "reason": "사이즈가 너무 작음", "user_id": 1}),
        ("주문내역 확인 좀", "get_user_orders", {"user_id": 1}),
        ("반품 정책이 어떻게 돼?", "search_knowledge_base", {"query": "반품 정책", "category": "취소/반품/교환"}),
        ("배송지 변경할래", "open_address_search", {}),
        ("쿠폰 등록하는 법 알려줘", "search_knowledge_base", {"query": "쿠폰 등록하는 법", "category": "기타"}),
        ("비회원 주문 조회는 어떻게 해?", "search_knowledge_base", {"query": "비회원 주문 조회", "category": "주문/결제"}),
        ("포인트 사용 한도가 있어?", "search_knowledge_base", {"query": "포인트 사용 한도", "category": "기타"}),
        ("배송 기간 보통 얼마나 걸려?", "search_knowledge_base", {"query": "배송 기간", "category": "배송"}),
        (f"주문번호 ORD-{today_str}-0001 상세 보기", "get_order_details", {"order_id": f"ORD-{today_str}-0001", "user_id": 1}),
        ("결제 오류가 나는데 어떡해?", "search_knowledge_base", {"query": "결제 오류", "category": "주문/결제"}),
        # 21-40
        (f"재질이 생각보다 별로라서 ORD-{today_str}-0002 환불하려고 해. 절차 알려주고 신청 가능할까?", "check_refund_eligibility", {"order_id": f"ORD-{today_str}-0002", "reason": "재질이 생각보다 별로", "user_id": 1}),
        (f"어제 주문한 반팔 티셔츠(ORD-{today_str}-0003) 언제쯤 도착할까?", "get_shipping_details", {"order_id": f"ORD-{today_str}-0003", "user_id": 1}),
        ("환불하려는데 내가 산 물건들 좀 보여줘", "get_user_orders", {"requires_selection": True, "action_context": "refund", "user_id": 1}),
        (f"잘못 샀어 ORD-{today_str}-0001 빨리 취소해줘!", "cancel_order", {"order_id": f"ORD-{today_str}-0001", "reason": "잘못 구매", "user_id": 1}),
        (f"ORD-{today_str}-0002 결제 수단을 카드로 바꾸고 싶은데 어떻게 하지?", "update_payment_method", {"order_id": f"ORD-{today_str}-0002", "payment_method": "카드", "user_id": 1}),
        (f"사이즈 교환하고 싶은데, 주문번호 ORD-{today_str}-0003고, 사이즈는 M에서 L(105번)로 바꾸고 싶어", "check_exchange_eligibility", {"order_id": f"ORD-{today_str}-0003", "reason": "사이즈 교환", "new_option_id": 105, "user_id": 1}),
        ("배송 주소가 잘못됐어 새로 입력할래", "open_address_search", {}),
        ("선물 받은 상품권 번호 'abc-123' 등록 부탁해", "register_gift_card", {"code": "abc-123", "user_id": 1}),
        ("내가 리뷰 쓴 상품들 보여줘", "get_reviews", {}),
        (f"이거 반품할건데 ORD-{today_str}-0001, 수거 주소는 경기도 성남시 야탑동 123-1이야", "register_return_request", {"order_id": f"ORD-{today_str}-0001", "pickup_address": "경기도 성남시 야탑동 123-1", "user_id": 1, "confirmed": True}),
        (f"리뷰 남길래! ORD-{today_str}-0002 상품 101번에 별 4개 주고 '배송 빠르네요'라고 써줘", "get_user_orders", {"requires_selection": True, "action_context": "create_review", "user_id": 1}),
        ("현금영수증 발행되나?", "search_knowledge_base", {"query": "현금영수증 발행", "category": "기타"}),
        ("주문 내역 다 지워줘(개인정보 보호 관련)", "search_knowledge_base", {"query": "주문 내역 삭제", "category": "기타"}),
        ("해외 배송 서비스도 하나요?", "search_knowledge_base", {"query": "해외 배송", "category": "배송"}),
        ("카드 무이자 할부 혜택 궁금해", "search_knowledge_base", {"query": "카드 무이자 할부", "category": "주문/결제"}),
        ("교환 배송비는 누가 내?", "search_knowledge_base", {"query": "교환 배송비", "category": "취소/반품/교환"}),
        (f"파손된 제품을 받았어 ORD-{today_str}-0003", "check_refund_eligibility", {"order_id": f"ORD-{today_str}-0003", "reason": "제품 파손", "user_id": 1, "is_seller_fault": True}),
        ("옵션 변경하려는데 주문내역 좀", "get_user_orders", {"requires_selection": True, "action_context": "change_option", "user_id": 1}),
        ("배송 조회할 수 있는 주문들 보여줘", "get_user_orders", {"requires_selection": True, "action_context": "shipping", "user_id": 1}),
        ("회원 탈퇴하고 싶어", "search_knowledge_base", {"query": "회원 탈퇴", "category": "기타"}),
        # 41-60
        ("나 환불할래", "get_user_orders", {"requires_selection": True, "action_context": "refund", "user_id": 1}),
        ("취소하고 싶어", "get_user_orders", {"requires_selection": True, "action_context": "cancel", "user_id": 1}),
        ("교환 신청하자", "get_user_orders", {"requires_selection": True, "action_context": "exchange", "user_id": 1}),
        ("결제 수단 좀 바꿔줘", "get_user_orders", {"requires_selection": True, "action_context": "payment_update", "user_id": 1}),
        ("방금 산 거 옵션 바꿀래", "get_user_orders", {"requires_selection": True, "action_context": "change_option", "user_id": 1}),
        ("이거 리뷰 평점 5점 줄게", "get_user_orders", {"requires_selection": True, "action_context": "create_review", "user_id": 1}),
        ("배송 상태 알려주세요", "get_user_orders", {"requires_selection": True, "action_context": "shipping", "user_id": 1}),
        ("반품 접수 도와줘", "get_user_orders", {"requires_selection": True, "action_context": "refund", "user_id": 1}),
        ("어디까지 왔니?", "get_user_orders", {"requires_selection": True, "action_context": "shipping", "user_id": 1}),
        ("잘못 시켰어", "get_user_orders", {"requires_selection": True, "action_context": "cancel", "user_id": 1}),
        ("리뷰 조회해줘", "search_knowledge_base", {"query": "리뷰 조회 방법", "category": "기타"}),
        ("주문 내역이 안 보여", "search_knowledge_base", {"query": "주문 내역 확인 불가", "category": "주문/결제"}),
        ("상품권 코드가 안 먹혀요", "search_knowledge_base", {"query": "상품권 코드 오류", "category": "기타"}),
        ("주소 찾기 띄워봐", "open_address_search", {}),
        ("반품은 공짜인가?", "search_knowledge_base", {"query": "반품 배송비", "category": "취소/반품/교환"}),
        ("입금했는데 확인이 안 돼", "search_knowledge_base", {"query": "입금 확인 지연", "category": "주문/결제"}),
        ("배송 지연 보상 있어?", "search_knowledge_base", {"query": "배송 지연 보상", "category": "배송"}),
        ("교환하려는데 물건이 품절이면?", "search_knowledge_base", {"query": "교환 품절 시 처리", "category": "취소/반품/교환"}),
        ("내 주문들 중 취소할 수 있는 거", "get_user_orders", {"requires_selection": True, "action_context": "cancel", "user_id": 1}),
        ("결제 방식 변경 방법", "search_knowledge_base", {"query": "결제 수단 변경 방법", "category": "주문/결제"}),
        # 61-80
        ("안녕 반가워", "no_tool_call", {}),
        ("너는 누구니?", "no_tool_call", {}),
        ("비트코인 시세 알려줘", "no_tool_call", {}),
        ("맛있는 점심 메뉴 추천해줘", "no_tool_call", {}),
        ("파이썬 코딩하는 법 알려줘", "no_tool_call", {}),
        ("내일 축구 경기 몇 시야?", "no_tool_call", {}),
        ("노래 불러줘", "no_tool_call", {}),
        ("농담 하나만 해봐", "no_tool_call", {}),
        ("미국 수도가 어디야?", "no_tool_call", {}),
        ("심심해", "no_tool_call", {}),
        ("사랑해", "no_tool_call", {}),
        ("너 이름이 뭐야?", "no_tool_call", {}),
        ("독도는 누구 땅?", "no_tool_call", {}),
        ("라면 맛있게 끓이는 법", "no_tool_call", {}),
        ("오늘 날씨 최고 기온이 얼마야?", "no_tool_call", {}),
        ("넷플릭스 영화 추천", "no_tool_call", {}),
        ("아이폰 16 언제 나와?", "no_tool_call", {}),
        ("손흥민 골 넣었어?", "no_tool_call", {}),
        ("지하철 막차 시간 알려줘", "no_tool_call", {}),
        ("로또 당첨 번호", "no_tool_call", {}),
        # 81-100
        (f"주문번호 오알디-{today_str}-0001 상세히", "get_order_details", {"order_id": f"ORD-{today_str}-0001", "user_id": 1}),
        (f"캔슬할래요 ord-{today_str}-0002. 단순변심임다", "cancel_order", {"order_id": f"ORD-{today_str}-0002", "reason": "단순변심", "user_id": 1}),
        (f"배송상태 'ORD-{today_str}-0003' 좀 봐줘", "get_shipping_details", {"order_id": f"ORD-{today_str}-0003", "user_id": 1}),
        ("반품수거지는 강남구 대치동 444-4번지로 등록 고", "get_user_orders", {"requires_selection": True, "action_context": "refund", "user_id": 1}),
        ("상품권 번호 ABCD 1234 EFGH 가즈아", "register_gift_card", {"code": "ABCD 1234 EFGH", "user_id": 1}),
        (f"환불 환불 환불! ORD-{today_str}-0001!", "check_refund_eligibility", {"order_id": f"ORD-{today_str}-0001", "user_id": 1}),
        ("배송 주소를... 서울시 중구... 10번지로... 바꾸고 싶은데", "open_address_search", {}),
        (f"옷 사이즈 95(10번)에서 105(30번)로 ORD-{today_str}-0002", "change_product_option", {"order_id": f"ORD-{today_str}-0002", "new_option_id": 30, "user_id": 1}),
        ("리뷰를 써보고 싶은데요. 상품 555번에 대해서요.", "get_user_orders", {"requires_selection": True, "action_context": "create_review", "user_id": 1}),
        ("어떤 주문을 취소할 수 있는지 볼래요.", "get_user_orders", {"requires_selection": True, "action_context": "cancel", "user_id": 1}),
        ("배송비 얼마임?", "search_knowledge_base", {"query": "배송비 안내", "category": "배송"}),
        ("기프티콘도 되나요?", "search_knowledge_base", {"query": "기프티콘 사용 여부", "category": "주문/결제"}),
        (f"주문번호 0RD_{today_str}_0003 (필기체 오타)", "get_order_details", {"order_id": f"ORD-{today_str}-0003", "user_id": 1}),
        (f"주문 ORD-{today_str}-0001에 대해 카드 번호 9999-0000으로 결제 변경", "update_payment_method", {"order_id": f"ORD-{today_str}-0001", "payment_method": "카드", "card_number": "9999-0000", "user_id": 1}),
        (f"리뷰 별 다섯 개 드립니다. 상품 111번 ORD-{today_str}-0002", "get_user_orders", {"requires_selection": True, "action_context": "create_review", "user_id": 1}),
        ("배송지... 알려줄게", "open_address_search", {}),
        (f"교환 배송비 확인용 ORD-{today_str}-0003", "check_exchange_eligibility", {"order_id": f"ORD-{today_str}-0003", "user_id": 1}),
        ("반품 신청 할게요 오알디 007 수거 주소는 성동구 입니다", "get_user_orders", {"requires_selection": True, "action_context": "refund", "user_id": 1}),
        ("아무거나 추천해줘", "no_tool_call", {}),
        ("잘 있어 잘가", "no_tool_call", {}),
    ]

    output_file = os.path.join(base_dir, "my_eval_dataset_100.jsonl")
    with open(output_file, "w", encoding="utf-8") as f:
        for i, (query, gt_name, gt_args) in enumerate(sc_data, 1):
            case = create_case(i, query, gt_name, gt_args, tools_def)
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"Generated 100 cases to {output_file}")

if __name__ == "__main__":
    main()
