import argparse
import json
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.append(str(current_dir))

from paths import DATA_DIR

# 다변화 템플릿 (valid_and_diversify_dataset.py와 동일)
QUERIES_DICT = {
    "shipping": [
        "배송 조회 좀 부탁드릴게요. {o_id} 이거 지금 어디쯤인가요?",
        "주문번호 {o_id} 배송 상태 확인하고 싶어요. 언제 도착할까요?",
        "{o_id} 택배사 조회해보니 안 뜨는데, 현재 위치 좀 알려주세요."
    ],
    "exchange": [
        "{o_id} 주문건, 사이즈가 너무 커서 다른 사이즈로 교환하고 싶습니다.",
        "옷 색상이 화면이랑 너무 다르네요. {o_id} 다른 색상으로 교환 처리 부탁드립니다.",
        "{o_id} 상품 교환하고 싶은데 절차가 어떻게 되나요? 사이즈를 잘못 주문했어요."
    ],
    "refund": [
        "배송받은 {o_id} 상품이 파손되어 있어서 환불 신청하려고 합니다.",
        "생각했던 느낌이랑 너무 달라서 {o_id} 반품하고 환불받고 싶어요.",
        "{o_id} 반품 신청 부탁드려요. 제품에 하자가 있어서 더 이상 필요 없습니다."
    ],
    "cancel": [
        "방금 결제한 {o_id} 주문 취소하고 싶어요. 마음이 바뀌었습니다.",
        "{o_id} 아직 배송 전이면 취소 부탁드릴게요. 실수로 잘못 주문했어요.",
        "주문번호 {o_id} 취소해주세요. 다른 상품으로 다시 주문하려고요."
    ],
    "get_user_orders": [
        "최근 주문한 내역 좀 보여주세요. 주문번호를 모르겠네요.",
        "내 주문 목록 확인하고 싶어요. 배송 상태 보려고 하는데 목록 좀 띄워주세요.",
        "지금까지 주문한 거 리스트업 부탁합니다. 취소할 게 있는데 번호를 몰라요."
    ]
}

DEFAULT_INPUT_CANDIDATES = [
    DATA_DIR / "intermediate_queries.json"
]


def resolve_default_input() -> Path:
    for candidate in DEFAULT_INPUT_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_INPUT_CANDIDATES[0]


def resolve_default_output(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_verified.jsonl")


def convert_v6_to_v4_verified(input_path: Path, output_path: Path):
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

        # order_id 보정 logic
        if not o_id or o_id == "None":
            o_id = f"ORD-eval_dataset-{u_id * 3 - 2:04d}"
        if o_id == "ORD-eval_dataset--002":
            o_id = "ORD-eval_dataset-0001"

        # 질문 다변화 (템플릿 적용)
        if action in QUERIES_DICT:
            q_idx = counters[action] % len(QUERIES_DICT[action])
            final_query = QUERIES_DICT[action][q_idx].replace("{o_id}", o_id)
            counters[action] += 1
        else:
            final_query = item.get("user_query", "")

        # v4_verified 형식에 맞춰 meta 제외하고 구성
        out_item = {
            "scenario": item["scenario"],
            "order": item.get("order", {"order_id": o_id}),
            "user_id": u_id,
            "user_email": item.get("user_email", "test@example.com"),
            "user_query": final_query,
        }
        results.append(out_item)

    # JSONL 형식으로 저장 (한 줄에 객체 하나씩)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[출력] {output_path.name} ({len(results)}건)")
    print("✅ 변환 완료! _verified와 동일한 JSONL 형식으로 저장되었습니다.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", dest="input_path", type=Path, default=None)
    parser.add_argument("--output", dest="output_path", type=Path, default=None)
    args = parser.parse_args()

    input_path = args.input_path or resolve_default_input()
    output_path = args.output_path or resolve_default_output(input_path)
    convert_v6_to_v4_verified(input_path, output_path)
