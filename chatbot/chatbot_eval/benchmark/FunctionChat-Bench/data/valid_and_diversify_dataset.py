"""
valid_and_diversify_dataset.py
[목적]
intermediate_queries_v4.json을 읽어,
1) 질문을 다변화 템플릿으로 교체
2) 입력 JSON 원본 형식(scenario, order, user_id, user_email, user_query) 그대로 유지
3) ground_truth는 생성하지 않음
4) JSONL로 저장 → intermediate_queries_v4_verified.jsonl
"""

import json
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR

INPUT_PATH = DATA_DIR / "intermediate_queries_v4.json"
OUTPUT_PATH = DATA_DIR / "intermediate_queries_v4_verified.jsonl"

# ==========================================
# 다변화 템플릿
# ==========================================
QUERIES_DICT = {
    "cancel": [
        "주문번호 {o_id} 배송이 너무 느려서 취소하려고 합니다. 처리해주세요.",
        "저기요, {o_id} 주문건 아직도 상품준비중이던데 그냥 취소할래요. 배송 지연되어서요.",
        "수고하십니다. {o_id} 결제한거 취소 부탁드립니다. 딴데서 샀어요. 배송이 늦어져서요."
    ],
    "refund": [
        "받은 {o_id} 상품이 완전히 파손되어 있어서 환불 신청합니다. 판매자 책임입니다.",
        "이거 {o_id} 배송받아서 까봤는데 불량품이네요;; 환불해주세요.",
        "상품 상태가 영 아니네요. 찢어져서 왔습니다. {o_id} 환불 처리 부탁드려요."
    ],
    "exchange": [
        "{o_id} 주문건, 사이즈가 너무 커서 교환할게요.",
        "옷이 저한테 안 맞네요 ㅠㅠ {o_id} 사이즈 불일치로 교환하고 싶습니다.",
        "{o_id} 교환 신청합니다. 생각보다 너무 작게 나왔네요."
    ],
    "shipping_no_id": [
        "방금 주문한 내역의 배송 상태를 알고 싶은데 주문번호는 까먹었어요.",
        "저 주문내역 확인좀요. 결제는 했는데 주문번호를 안적어놨네요.",
        "배송조회 하고싶은데 주문번호 없이도 되나요? 언제 오는지 알고싶어요."
    ],
    "shipping_with_id": [
        "{o_id} 주문 도대체 언제 도착하는지 배송 조회 좀 해주세요.",
        "주문번호 {o_id} 배송 언제 시작하나요? 조회 부탁합니다.",
        "{o_id} 이거 택배 어디쯤 왔는지 궁금해요."
    ],
    "search_by_text_clip": [
        "여름에 입기 좋은 시원한 반팔 티셔츠 찾아줘.",
        "요즘 유행하는 와이드 팬츠 검색 좀 해줄래요?",
        "캐주얼하게 입기 편한 오버핏 맨투맨 있나요?"
    ],
    "recommend_clothes": [
        "결혼식 하객으로 입고 갈만한 깔끔한 정장 세트 추천해줄래?",
        "이번 주말에 데이트가 있는데 입을만한 예쁜 원피스 추천 좀요.",
        "운동할 때 입기 좋은 기능성 트레이닝복 상하의 찾아줘."
    ],
    "search_by_image": [
        "[System: User uploaded an image] 이 사진에 있는 가방이랑 비슷한 거 찾아주세요.",
        "[System: User uploaded an image] 연예인이 입은 이 옷이랑 비슷한 스타일 있을까요?",
        "[System: User uploaded an image] 여기 코디된 신발 느낌의 상품 찾아줘."
    ],
    "used_sale": [
        "제가 입던 원피스를 중고로 팔려고 하는데 폼 좀 열어주세요.",
        "안 입는 패딩 중고 판매 등록하고 싶어요. 어떻게 하나요?",
        "사이즈 미스난 신발 당근처럼 중고판매 가능하죠? 신청서 띄워주세요."
    ],
    "review": [
        "주문한 {o_id} 상품 너무 마음에 들어요! 별점 5점 줄게요.",
        "{o_id} 받아보니 가성비 대박이네요 ㅋㅋㅋ 리뷰 5점으로 남겨주세요.",
        "배송도 빠르고 재질도 좋네요~ {o_id} 건에 대해 5점 리뷰 작성할게요."
    ],
    "register_gift_card": [
        "친구가 준 상품권 등록할게요. 코드는 GIFT-9988 입니다.",
        "선물받은 기프트카드 포인트로 전환할게요. 번호는 GIFT-1234 예요.",
        "이벤트로 받은 쿠폰 번호 DISCOUNT-7777 인데 기프트카드로 등록해주세요."
    ]
}


def process_dataset(input_path: Path, output_path: Path):
    """
    intermediate_queries_v4.json → intermediate_queries_v4_verified.jsonl
    입력 JSON의 원본 구조를 유지하면서 질문만 다변화 템플릿으로 교체합니다.
    ground_truth는 만들지 않습니다.
    """
    if not input_path.exists():
        print(f"Error: {input_path} 파일을 찾을 수 없습니다.")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    print(f"[입력] {input_path.name} ({len(dataset)}건)")

    counters = {k: 0 for k in QUERIES_DICT}
    results = []

    for item in dataset:
        action = item["scenario"]["action"]
        o_id = item.get("order", {}).get("order_id", "") or ""
        u_id = item.get("user_id", 1)

        # order_id 보정
        if not o_id or o_id == "None":
            o_id = f"ORD-eval_dataset-{u_id * 3 - 2:04d}"
        if o_id == "ORD-eval_dataset--002":
            o_id = "ORD-eval_dataset-0001"

        # 질문 다변화
        if action in QUERIES_DICT:
            q_idx = counters[action] % len(QUERIES_DICT[action])
            final_query = QUERIES_DICT[action][q_idx].replace("{o_id}", o_id)
            counters[action] += 1
        else:
            final_query = item.get("user_query", "")

        # 원본 JSON 구조 그대로 유지하며 user_query만 교체
        out_item = {
            "scenario": item["scenario"],
            "order": item.get("order", {"order_id": o_id}),
            "user_id": u_id,
            "user_email": item.get("user_email", "test@example.com"),
            "user_query": final_query,
        }
        results.append(out_item)

    # JSONL 저장
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[출력] {output_path.name} ({len(results)}건)")
    print("✅ 완료! ground_truth 없이 원본 형식 그대로 JSONL 변환되었습니다.")


if __name__ == "__main__":
    process_dataset(INPUT_PATH, OUTPUT_PATH)
