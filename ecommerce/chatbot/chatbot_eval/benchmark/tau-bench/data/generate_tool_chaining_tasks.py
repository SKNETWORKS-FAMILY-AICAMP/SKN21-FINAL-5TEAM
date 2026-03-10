"""
generate_tool_chaining_tasks.py

[목적]
eval_data.jsonl의 유저 데이터를 기반으로 tool chaining 태스크를 동적 생성합니다.
각 유저 row의 action type(주문취소, 환불, 교환)에 따라 해당 태스크만 생성하고,
action이 없으면 주문번호가 필요한 태스크는 건너뜁니다.

[평가 핵심]
1) 한 툴의 출력(결과)이 다음 툴의 입력(인자)으로 연결되는 연쇄 호출 패턴 평가
2) 챗봇이 올바른 순서로 툴을 호출하는지 평가
3) 이전 툴 결과에서 올바른 값을 추출해 다음 툴 인자로 넘기는지 평가

[action type → 태스크 매핑]
- 주문취소: TC_TASK_003 (주문 상세 확인 후 취소)
- 환불:    TC_TASK_001 (환불 신청 체인), TC_TASK_007 (주문 상세 → 환불 자격 확인)
- 교환:    TC_TASK_002 (교환 신청 체인), TC_TASK_008 (교환 자격 확인 후 교환 신청)
- 항상 생성(주문번호 불필요): TC_TASK_004 (중고 판매 후 수거 신청)
- 항상 생성(주문번호 필요):   TC_TASK_005 (리뷰 초안 → 등록), TC_TASK_006 (주문 → 배송 확인),
                              TC_TASK_009 (주문 → 리뷰 → 등록) — 첫 번째 가용 주문번호 사용

[실행 방법]
    python data/generate_tool_chaining_tasks.py
    python run.py --tasks_file data/tool_chaining_tasks.jsonl
    python run.py --tasks_file data/tool_chaining_tasks.jsonl --task_ids U000_TC_TASK_003 U000_TC_TASK_009
"""

import json
from pathlib import Path
from typing import Callable

EVAL_DATA_PATH = Path(__file__).resolve().parent / "../../eval_data.jsonl"
OUTPUT_PATH = Path(__file__).resolve().parent / "tool_chaining_tasks.jsonl"


# ─── 태스크 템플릿 함수들 ─────────────────────────────────────────────────────

def make_refund_chain_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_001: 환불 신청 체인 (2-chain) — check_refund_eligibility → register_return_request"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "refund_chain",
        "difficulty": "medium",
        "instruction": f"{order_number} 환불 신청할게요. 단순변심이고, 수거지는 서울 강남구 테헤란로 123이에요.",
        "user_goal": f"{order_number} 주문에 대해 환불 자격을 확인하고, 반품 신청을 완료한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "DELIVERED",
                "total_amount": 49000,
                "product_name": "코튼 셔츠 아이보리 S",
                "can_return": True,
                "delivered_at": "2026-02-21"
            }]
        },
        "expected_actions": [
            {
                "tool": "check_refund_eligibility",
                "required_args": {"order_id": order_number, "user_id": user_id, "reason": "단순변심"}
            },
            {
                "tool": "register_return_request",
                "required_args": {
                    "order_id": order_number,
                    "user_id": user_id,
                    "pickup_address": "서울 강남구 테헤란로 123",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["check_refund_eligibility", "register_return_request"],
            "final_state_check": {"order_id": order_number, "expected_status": "RETURN_REQUESTED"}
        },
        "chain_length": 2,
        "chain_pattern": "check_refund_eligibility → register_return_request",
        "slot_filling_required": False
    }


def make_exchange_chain_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_002: 교환 신청 체인 (2-chain) — check_exchange_eligibility → register_exchange_request"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "exchange_chain",
        "difficulty": "medium",
        "instruction": f"{order_number} 교환 신청할게요. 사이즈가 맞지 않아요. 수거지는 서울 마포구 홍익로 20이에요.",
        "user_goal": f"{order_number} 주문에 대해 교환 자격을 확인하고, 교환 신청을 완료한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "슬림핏 데님 팬츠 블루 M",
                "can_exchange": True,
                "delivered_at": "2026-02-22"
            }]
        },
        "expected_actions": [
            {
                "tool": "check_exchange_eligibility",
                "required_args": {"order_id": order_number, "user_id": user_id, "reason": "사이즈가 맞지 않아요"}
            },
            {
                "tool": "register_exchange_request",
                "required_args": {
                    "order_id": order_number,
                    "user_id": user_id,
                    "reason": "사이즈가 맞지 않아요",
                    "pickup_address": "서울 마포구 홍익로 20",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
            "final_state_check": {"order_id": order_number, "expected_status": "EXCHANGE_REQUESTED"}
        },
        "chain_length": 2,
        "chain_pattern": "check_exchange_eligibility → register_exchange_request",
        "slot_filling_required": False
    }


def make_order_cancel_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_003: 주문 상세 확인 후 취소 (2-chain) — get_order_details → cancel_order"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "order_detail_cancel_chain",
        "difficulty": "medium",
        "instruction": f"{order_number} 주문 상세 확인하고 취소해줘. 사유는 단순변심이에요.",
        "user_goal": f"{order_number} 주문 상세를 조회하고, 단순변심 사유로 주문을 취소한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "PAYMENT_DONE",
                "total_amount": 39000,
                "product_name": "오버핏 맨투맨 화이트 L",
                "can_cancel": True
            }]
        },
        "expected_actions": [
            {
                "tool": "get_order_details",
                "required_args": {"order_id": order_number, "user_id": user_id}
            },
            {
                "tool": "cancel_order",
                "required_args": {"order_id": order_number, "user_id": user_id, "reason": "단순변심"}
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["get_order_details", "cancel_order"],
            "final_state_check": {"order_id": order_number, "expected_status": "CANCELLED"}
        },
        "chain_length": 2,
        "chain_pattern": "get_order_details → cancel_order",
        "slot_filling_required": False
    }


def make_used_sale_pickup_task(task_id: str, user_id: int) -> dict:
    """TC_TASK_004: 중고 판매 후 수거 신청 (2-chain) — register_used_sale → request_pickup"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "used_sale_pickup_chain",
        "difficulty": "hard",
        "instruction": "나이키 에어포스 운동화 중고로 팔고 싶어요. 상태는 '상'이고 희망가는 70,000원이에요. 3월 15일 서울 서초구 방배로 88로 수거 신청도 같이 해주세요.",
        "user_goal": "나이키 에어포스 운동화 중고 판매를 접수하고, 접수 번호(tracking_id)를 이용해 수거 신청을 완료한다.",
        "initial_db_state": {},
        "expected_actions": [
            {
                "tool": "register_used_sale",
                "required_args": {
                    "category": "신발",
                    "item_name": "나이키 에어포스 운동화",
                    "condition": "상",
                    "expected_price": 70000,
                    "user_id": user_id
                }
            },
            {
                "tool": "request_pickup",
                "required_args": {
                    "pickup_date": "2026-03-15",
                    "pickup_address": "서울 서초구 방배로 88",
                    "user_id": user_id
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["register_used_sale", "request_pickup"],
            "final_state_check": {"used_sale_created": True, "pickup_scheduled": True}
        },
        "chain_length": 2,
        "chain_pattern": "register_used_sale → request_pickup",
        "slot_filling_required": False
    }


def make_review_draft_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_005: 리뷰 초안 작성 후 등록 (2-chain) — generate_review_draft → create_review"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "review_draft_chain",
        "difficulty": "medium",
        "instruction": f"{order_number}에서 산 오버핏 후드집업 리뷰 써줘. 만족도 높음, 착용감이랑 색감이 좋았어. 감성적인 버전으로 별점 5점으로 바로 등록해줘.",
        "user_goal": "오버핏 후드집업 리뷰 초안을 생성하고, 감성적인 버전으로 별점 5점 리뷰를 등록한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "오버핏 후드집업 그레이 L",
                "delivered_at": "2026-02-21"
            }]
        },
        "expected_actions": [
            {
                "tool": "generate_review_draft",
                "required_args": {
                    "product_name": "오버핏 후드집업 그레이 L",
                    "satisfaction": "높음",
                    "keywords": ["착용감", "색감"]
                }
            },
            {
                "tool": "create_review",
                "required_args": {"order_id": order_number, "user_id": user_id, "rating": 5}
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["generate_review_draft", "create_review"],
            "final_state_check": {"order_id": order_number, "review_created": True}
        },
        "chain_length": 2,
        "chain_pattern": "generate_review_draft → create_review",
        "slot_filling_required": False
    }


def make_order_shipping_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_006: 주문 상세 조회 후 배송 현황 확인 (2-chain) — get_order_details → get_shipping_details"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "order_shipping_chain",
        "difficulty": "easy",
        "instruction": f"{order_number} 주문 상세 보고 배송 현황도 확인해줘.",
        "user_goal": f"{order_number} 주문 상세 정보를 조회하고, 배송 현황을 확인한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "SHIPPED",
                "total_amount": 55000,
                "product_name": "울 블렌드 코트 카멜 M",
                "carrier": "CJ대한통운",
                "tracking_number": "1234567890123"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_order_details",
                "required_args": {"order_id": order_number, "user_id": user_id}
            },
            {
                "tool": "get_shipping_details",
                "required_args": {"order_id": order_number, "user_id": user_id}
            }
        ],
        "success_criteria": {
            "type": "tool_call",
            "required_tool_calls": ["get_order_details", "get_shipping_details"]
        },
        "chain_length": 2,
        "chain_pattern": "get_order_details → get_shipping_details",
        "slot_filling_required": False
    }


def make_order_refund_check_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_007: 주문 상세 조회 후 환불 자격 확인 (2-chain) — get_order_details → check_refund_eligibility"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "order_refund_check_chain",
        "difficulty": "medium",
        "instruction": f"{order_number} 코튼 셔츠 주문 상세 확인하고 환불 가능한지 알려줘.",
        "user_goal": f"{order_number} 주문 상세를 조회하고, 환불 가능 여부를 확인한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "DELIVERED",
                "total_amount": 49000,
                "product_name": "코튼 셔츠 아이보리 S",
                "can_return": True,
                "delivered_at": "2026-02-21"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_order_details",
                "required_args": {"order_id": order_number, "user_id": user_id}
            },
            {
                "tool": "check_refund_eligibility",
                "required_args": {"order_id": order_number, "user_id": user_id, "reason": "단순변심"}
            }
        ],
        "success_criteria": {
            "type": "tool_call",
            "required_tool_calls": ["get_order_details", "check_refund_eligibility"]
        },
        "chain_length": 2,
        "chain_pattern": "get_order_details → check_refund_eligibility",
        "slot_filling_required": False
    }


def make_exchange_eligibility_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_008: 교환 자격 확인 후 교환 신청 (2-chain) — check_exchange_eligibility → register_exchange_request"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "exchange_eligibility_chain",
        "difficulty": "medium",
        "instruction": f"{order_number} 교환 가능한지 확인하고, 가능하면 바로 신청해줘. 사이즈 교환이고 수거지는 서울 용산구 이태원로 55야.",
        "user_goal": f"{order_number} 교환 가능 여부를 확인하고, 가능하면 교환 신청을 완료한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "슬림핏 데님 팬츠 블루 M",
                "can_exchange": True,
                "delivered_at": "2026-02-22"
            }]
        },
        "expected_actions": [
            {
                "tool": "check_exchange_eligibility",
                "required_args": {"order_id": order_number, "user_id": user_id, "reason": "사이즈 교환"}
            },
            {
                "tool": "register_exchange_request",
                "required_args": {
                    "order_id": order_number,
                    "user_id": user_id,
                    "reason": "사이즈 교환",
                    "pickup_address": "서울 용산구 이태원로 55",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
            "final_state_check": {"order_id": order_number, "expected_status": "EXCHANGE_REQUESTED"}
        },
        "chain_length": 2,
        "chain_pattern": "check_exchange_eligibility → register_exchange_request",
        "slot_filling_required": False
    }


def make_order_review_3chain_task(task_id: str, order_number: str, user_id: int) -> dict:
    """TC_TASK_009: 주문 상세 → 리뷰 초안 → 등록 (3-chain) — get_order_details → generate_review_draft → create_review"""
    return {
        "task_id": task_id,
        "domain": "retail",
        "category": "order_review_3chain",
        "difficulty": "hard",
        "instruction": f"{order_number} 주문 상품 이름 확인하고 리뷰 써줘. 만족도 높음, 품질이 좋았어. 무뚝뚝한 버전으로 별점 4점 등록해줘.",
        "user_goal": f"{order_number} 주문 상품 이름을 확인하고, 리뷰 초안을 생성한 뒤 별점 4점으로 등록한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": order_number,
                "user_id": user_id,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "오버핏 후드집업 그레이 L",
                "delivered_at": "2026-02-21"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_order_details",
                "required_args": {"order_id": order_number, "user_id": user_id}
            },
            {
                "tool": "generate_review_draft",
                "required_args": {
                    "product_name": "오버핏 후드집업 그레이 L",
                    "satisfaction": "높음",
                    "keywords": ["품질"]
                }
            },
            {
                "tool": "create_review",
                "required_args": {"order_id": order_number, "user_id": user_id, "rating": 4}
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["get_order_details", "generate_review_draft", "create_review"],
            "final_state_check": {"order_id": order_number, "review_created": True}
        },
        "chain_length": 3,
        "chain_pattern": "get_order_details → generate_review_draft → create_review",
        "slot_filling_required": False
    }


# ─── action type → 태스크 생성 함수 매핑 ─────────────────────────────────────
# key: action type, value: (템플릿명, 생성함수) 리스트
ACTION_TYPE_TASK_MAP: dict[str, list[tuple[str, Callable]]] = {
    "주문취소": [
        ("TC_TASK_003", make_order_cancel_task),
    ],
    "환불": [
        ("TC_TASK_001", make_refund_chain_task),
        ("TC_TASK_007", make_order_refund_check_task),
    ],
    "교환": [
        ("TC_TASK_002", make_exchange_chain_task),
        ("TC_TASK_008", make_exchange_eligibility_task),
    ],
}

# 주문번호가 필요하지 않은 태스크 (항상 생성)
NO_ORDER_TASKS: list[tuple[str, Callable]] = [
    ("TC_TASK_004", make_used_sale_pickup_task),
]

# 주문번호가 필요하지만 특정 action type에 종속되지 않는 태스크
# (action이 하나라도 있으면 첫 번째 가용 주문번호로 생성)
GENERIC_ORDER_TASKS: list[tuple[str, Callable]] = [
    ("TC_TASK_005", make_review_draft_task),
    ("TC_TASK_006", make_order_shipping_task),
    ("TC_TASK_009", make_order_review_3chain_task),
]


# ─── eval_data.jsonl 읽기 및 태스크 생성 ─────────────────────────────────────

def main():
    print(f"[1] eval_data.jsonl 로딩 중... ({EVAL_DATA_PATH})")

    user_rows: list[dict] = []
    with open(EVAL_DATA_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("type") == "user":
                user_rows.append(row)

    print(f"  ✓ 유저 {len(user_rows)}명 로드 완료")

    all_tasks: list[dict] = []

    for user_idx, user_row in enumerate(user_rows):
        user_email = user_row["data"]["user_email"]
        user_id = user_idx + 1
        actions = user_row.get("action", [])

        # action type → order_number 매핑
        action_map: dict[str, str] = {}
        for action in actions:
            action_type = action["type"]
            order_number = action["data"]["order_number"]
            action_map[action_type] = order_number

        prefix = f"U{user_idx:03d}"
        task_count = 0

        # 1) action type별 태스크 생성 — 해당 action이 없으면 건너뜀
        for action_type, task_templates in ACTION_TYPE_TASK_MAP.items():
            if action_type not in action_map:
                continue
            order_number = action_map[action_type]
            for template_name, make_func in task_templates:
                task_id = f"{prefix}_{template_name}"
                task = make_func(task_id, order_number, user_id)
                all_tasks.append(task)
                task_count += 1

        # 2) 주문번호 불필요 태스크 (항상 생성)
        for template_name, make_func in NO_ORDER_TASKS:
            task_id = f"{prefix}_{template_name}"
            task = make_func(task_id, user_id)
            all_tasks.append(task)
            task_count += 1

        # 3) 범용 주문번호 태스크 (action이 하나라도 있으면 첫 번째 주문번호 사용)
        if action_map:
            first_order = list(action_map.values())[0]
            for template_name, make_func in GENERIC_ORDER_TASKS:
                task_id = f"{prefix}_{template_name}"
                task = make_func(task_id, first_order, user_id)
                all_tasks.append(task)
                task_count += 1

        print(f"  • 유저 {user_idx} ({user_email}): {task_count}개 태스크 생성 "
              f"(action types: {list(action_map.keys())})")

    # ─── JSONL 저장 ───────────────────────────────────────────────────────────
    print(f"\n[2] Tool Chaining 태스크 {len(all_tasks)}개 저장 중...")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for task in all_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")

    chain_dist: dict[int, int] = {}
    for t in all_tasks:
        cl = t["chain_length"]
        chain_dist[cl] = chain_dist.get(cl, 0) + 1

    print(f"  ✓ {len(all_tasks)}개 태스크 저장 완료 → {OUTPUT_PATH}")
    print(f"  • 체인 길이 분포: {', '.join(f'{k}-chain {v}개' for k, v in sorted(chain_dist.items()))}")
    print(f"\n[실행 방법]")
    print(f"  전체 실행  : python run.py --tasks_file data/tool_chaining_tasks.jsonl")
    print(f"  일부 실행  : python run.py --tasks_file data/tool_chaining_tasks.jsonl --task_ids U000_TC_TASK_003 U000_TC_TASK_009")
    print(f"  디버그 모드: python run.py --tasks_file data/tool_chaining_tasks.jsonl --debug")


if __name__ == "__main__":
    main()
