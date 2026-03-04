"""
generate_tool_chaining_tasks.py

[목적]
FunctionChat-Bench의 generate_tool_chaining_success_rate_dialog_dataset.py 시나리오를
tau-bench 실행 포맷(tasks.jsonl)으로 변환하여 저장합니다.

[평가 핵심]
1) 한 툴의 출력(결과)이 다음 툴의 입력(인자)으로 연결되는 연쇄 호출 패턴 평가
2) 챗봇이 올바른 순서로 툴을 호출하는지 평가
3) 이전 툴 결과에서 올바른 값을 추출해 다음 툴 인자로 넘기는지 평가

[9개 시나리오 — FunctionChat-Bench Dialog → tau-bench Task 변환]
- TC_TASK_001: 환불 신청 체인 (2-chain) — check_refund_eligibility → register_return_request
- TC_TASK_002: 교환 신청 체인 (2-chain) — check_exchange_eligibility → register_exchange_request
- TC_TASK_003: 주문 상세 확인 후 취소 (2-chain) — get_order_details → cancel_order
- TC_TASK_004: 중고 판매 후 수거 신청 (2-chain) — register_used_sale → request_pickup
- TC_TASK_005: 리뷰 초안 작성 후 등록 (2-chain) — generate_review_draft → create_review
- TC_TASK_006: 주문 상세 조회 후 배송 현황 확인 (2-chain) — get_order_details → get_shipping_details
- TC_TASK_007: 주문 상세 조회 후 환불 자격 확인 (2-chain) — get_order_details → check_refund_eligibility
- TC_TASK_008: 교환 자격 확인 후 교환 신청 (2-chain) — check_exchange_eligibility → register_exchange_request
- TC_TASK_009: 주문 상세 → 리뷰 초안 → 등록 (3-chain) — get_order_details → generate_review_draft → create_review

[실행 방법]
    python data/generate_tool_chaining_tasks.py
    python run.py --model gpt-4o-mini --tasks_file data/tool_chaining_tasks.jsonl
    python run.py --model gpt-4o-mini --tasks_file data/tool_chaining_tasks.jsonl --task_ids TC_TASK_003 TC_TASK_009
"""

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent / "tool_chaining_tasks.jsonl"

# ─── 태스크 정의 ──────────────────────────────────────────────────────────────

tasks = [

    # ── TC_TASK_001 ─────────────────────────────────────────────────────────────
    # 환불 신청 체인 (2-chain) | Dialog #1
    # check_refund_eligibility → register_return_request
    # 체이닝 포인트: eligible 확인 후 반품 신청 — order_id·수거지는 사용자 발화에 포함
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_001",
        "domain": "retail",
        "category": "refund_chain",
        "difficulty": "medium",
        "instruction": "ORD-20260219-0005 환불 신청할게요. 단순변심이고, 수거지는 서울 강남구 테헤란로 123이에요.",
        "user_goal": "ORD-20260219-0005 주문에 대해 환불 자격을 확인하고, 반품 신청을 완료한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0005",
                "user_id": 1,
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
                "required_args": {"order_id": "ORD-20260219-0005", "user_id": 1, "reason": "단순변심"}
            },
            {
                "tool": "register_return_request",
                "required_args": {
                    "order_id": "ORD-20260219-0005",
                    "user_id": 1,
                    "pickup_address": "서울 강남구 테헤란로 123",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["check_refund_eligibility", "register_return_request"],
            "final_state_check": {"order_id": "ORD-20260219-0005", "expected_status": "RETURN_REQUESTED"}
        },
        "chain_length": 2,
        "chain_pattern": "check_refund_eligibility → register_return_request",
        "slot_filling_required": False
    },

    # ── TC_TASK_002 ─────────────────────────────────────────────────────────────
    # 교환 신청 체인 (2-chain) | Dialog #2
    # check_exchange_eligibility → register_exchange_request
    # 체이닝 포인트: eligible 확인 후 교환 신청 — order_id·수거지는 사용자 발화에 포함
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_002",
        "domain": "retail",
        "category": "exchange_chain",
        "difficulty": "medium",
        "instruction": "ORD-20260219-0006 교환 신청할게요. 사이즈가 맞지 않아요. 수거지는 서울 마포구 홍익로 20이에요.",
        "user_goal": "ORD-20260219-0006 주문에 대해 교환 자격을 확인하고, 교환 신청을 완료한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0006",
                "user_id": 1,
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
                "required_args": {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈가 맞지 않아요"}
            },
            {
                "tool": "register_exchange_request",
                "required_args": {
                    "order_id": "ORD-20260219-0006",
                    "user_id": 1,
                    "reason": "사이즈가 맞지 않아요",
                    "pickup_address": "서울 마포구 홍익로 20",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
            "final_state_check": {"order_id": "ORD-20260219-0006", "expected_status": "EXCHANGE_REQUESTED"}
        },
        "chain_length": 2,
        "chain_pattern": "check_exchange_eligibility → register_exchange_request",
        "slot_filling_required": False
    },

    # ── TC_TASK_003 ─────────────────────────────────────────────────────────────
    # 주문 상세 확인 후 취소 (2-chain) | Dialog #3
    # get_order_details → cancel_order
    # 체이닝 포인트: can_cancel 확인 후 취소 — order_id는 사용자 발화에 포함
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_003",
        "domain": "retail",
        "category": "order_detail_cancel_chain",
        "difficulty": "medium",
        "instruction": "ORD-20260301-0002 주문 상세 확인하고 취소해줘. 사유는 단순변심이에요.",
        "user_goal": "ORD-20260301-0002 주문 상세를 조회하고, 단순변심 사유로 주문을 취소한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260301-0002",
                "user_id": 1,
                "status": "PAYMENT_DONE",
                "total_amount": 39000,
                "product_name": "오버핏 맨투맨 화이트 L",
                "can_cancel": True
            }]
        },
        "expected_actions": [
            {
                "tool": "get_order_details",
                "required_args": {"order_id": "ORD-20260301-0002", "user_id": 1}
            },
            {
                "tool": "cancel_order",
                "required_args": {"order_id": "ORD-20260301-0002", "user_id": 1, "reason": "단순변심"}
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["get_order_details", "cancel_order"],
            "final_state_check": {"order_id": "ORD-20260301-0002", "expected_status": "CANCELLED"}
        },
        "chain_length": 2,
        "chain_pattern": "get_order_details → cancel_order",
        "slot_filling_required": False
    },

    # ── TC_TASK_004 ─────────────────────────────────────────────────────────────
    # 중고 판매 후 수거 신청 (2-chain) | Dialog #4
    # register_used_sale → request_pickup
    # 체이닝 포인트: tracking_id(sale_id) 전달 — 수거지·날짜는 사용자 발화에 포함
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_004",
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
                    "user_id": 1
                }
            },
            {
                "tool": "request_pickup",
                "required_args": {
                    "pickup_date": "2026-03-15",
                    "pickup_address": "서울 서초구 방배로 88",
                    "user_id": 1
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
    },

    # ── TC_TASK_005 ─────────────────────────────────────────────────────────────
    # 리뷰 초안 작성 후 등록 (2-chain) | Dialog #5
    # generate_review_draft → create_review
    # 체이닝 포인트: 초안 내용(emotional 버전)을 content 인자로 전달
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_005",
        "domain": "retail",
        "category": "review_draft_chain",
        "difficulty": "medium",
        "instruction": "ORD-20260219-0003에서 산 오버핏 후드집업 리뷰 써줘. 만족도 높음, 착용감이랑 색감이 좋았어. 감성적인 버전으로 별점 5점으로 바로 등록해줘.",
        "user_goal": "오버핏 후드집업 리뷰 초안을 생성하고, 감성적인 버전으로 별점 5점 리뷰를 등록한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0003",
                "user_id": 1,
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
                "required_args": {"order_id": "ORD-20260219-0003", "user_id": 1, "rating": 5}
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["generate_review_draft", "create_review"],
            "final_state_check": {"order_id": "ORD-20260219-0003", "review_created": True}
        },
        "chain_length": 2,
        "chain_pattern": "generate_review_draft → create_review",
        "slot_filling_required": False
    },

    # ── TC_TASK_006 ─────────────────────────────────────────────────────────────
    # 주문 상세 조회 후 배송 현황 확인 (2-chain) | Dialog #6
    # get_order_details → get_shipping_details
    # 체이닝 포인트: order_id를 그대로 배송 조회에 전달
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_006",
        "domain": "retail",
        "category": "order_shipping_chain",
        "difficulty": "easy",
        "instruction": "ORD-20260225-0009 주문 상세 보고 배송 현황도 확인해줘.",
        "user_goal": "ORD-20260225-0009 주문 상세 정보를 조회하고, 배송 현황을 확인한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260225-0009",
                "user_id": 1,
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
                "required_args": {"order_id": "ORD-20260225-0009", "user_id": 1}
            },
            {
                "tool": "get_shipping_details",
                "required_args": {"order_id": "ORD-20260225-0009", "user_id": 1}
            }
        ],
        "success_criteria": {
            "type": "tool_call",
            "required_tool_calls": ["get_order_details", "get_shipping_details"]
        },
        "chain_length": 2,
        "chain_pattern": "get_order_details → get_shipping_details",
        "slot_filling_required": False
    },

    # ── TC_TASK_007 ─────────────────────────────────────────────────────────────
    # 주문 상세 조회 후 환불 자격 확인 (2-chain) | Dialog #8
    # get_order_details → check_refund_eligibility
    # 체이닝 포인트: order_id + status 확인 후 환불 가능 여부 조회
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_007",
        "domain": "retail",
        "category": "order_refund_check_chain",
        "difficulty": "medium",
        "instruction": "ORD-20260219-0005 코튼 셔츠 주문 상세 확인하고 환불 가능한지 알려줘.",
        "user_goal": "ORD-20260219-0005 주문 상세를 조회하고, 환불 가능 여부를 확인한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0005",
                "user_id": 1,
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
                "required_args": {"order_id": "ORD-20260219-0005", "user_id": 1}
            },
            {
                "tool": "check_refund_eligibility",
                "required_args": {"order_id": "ORD-20260219-0005", "user_id": 1, "reason": "단순변심"}
            }
        ],
        "success_criteria": {
            "type": "tool_call",
            "required_tool_calls": ["get_order_details", "check_refund_eligibility"]
        },
        "chain_length": 2,
        "chain_pattern": "get_order_details → check_refund_eligibility",
        "slot_filling_required": False
    },

    # ── TC_TASK_008 ─────────────────────────────────────────────────────────────
    # 교환 자격 확인 후 교환 신청 (2-chain) | Dialog #9
    # check_exchange_eligibility → register_exchange_request
    # 체이닝 포인트: eligible 확인 후 즉시 교환 신청 (다른 수거지 시나리오)
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_008",
        "domain": "retail",
        "category": "exchange_eligibility_chain",
        "difficulty": "medium",
        "instruction": "ORD-20260219-0006 교환 가능한지 확인하고, 가능하면 바로 신청해줘. 사이즈 교환이고 수거지는 서울 용산구 이태원로 55야.",
        "user_goal": "ORD-20260219-0006 교환 가능 여부를 확인하고, 가능하면 교환 신청을 완료한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0006",
                "user_id": 1,
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
                "required_args": {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈 교환"}
            },
            {
                "tool": "register_exchange_request",
                "required_args": {
                    "order_id": "ORD-20260219-0006",
                    "user_id": 1,
                    "reason": "사이즈 교환",
                    "pickup_address": "서울 용산구 이태원로 55",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
            "final_state_check": {"order_id": "ORD-20260219-0006", "expected_status": "EXCHANGE_REQUESTED"}
        },
        "chain_length": 2,
        "chain_pattern": "check_exchange_eligibility → register_exchange_request",
        "slot_filling_required": False
    },

    # ── TC_TASK_009 ─────────────────────────────────────────────────────────────
    # 주문 상세 → 리뷰 초안 → 등록 (3-chain, 크로스 도메인) | Dialog #10
    # get_order_details → generate_review_draft → create_review
    # 체이닝 포인트: product_name(→2단계), draft_content(→3단계)
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "TC_TASK_009",
        "domain": "retail",
        "category": "order_review_3chain",
        "difficulty": "hard",
        "instruction": "ORD-20260219-0003 주문 상품 이름 확인하고 리뷰 써줘. 만족도 높음, 품질이 좋았어. 무뚝뚝한 버전으로 별점 4점 등록해줘.",
        "user_goal": "ORD-20260219-0003 주문 상품 이름을 확인하고, 리뷰 초안을 생성한 뒤 별점 4점으로 등록한다.",
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0003",
                "user_id": 1,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "오버핏 후드집업 그레이 L",
                "delivered_at": "2026-02-21"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_order_details",
                "required_args": {"order_id": "ORD-20260219-0003", "user_id": 1}
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
                "required_args": {"order_id": "ORD-20260219-0003", "user_id": 1, "rating": 4}
            }
        ],
        "success_criteria": {
            "type": "tool_call_and_state",
            "required_tool_calls": ["get_order_details", "generate_review_draft", "create_review"],
            "final_state_check": {"order_id": "ORD-20260219-0003", "review_created": True}
        },
        "chain_length": 3,
        "chain_pattern": "get_order_details → generate_review_draft → create_review",
        "slot_filling_required": False
    },

]

# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
print(f"[1] Tool Chaining 태스크 {len(tasks)}개 생성 중...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for task in tasks:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")

chain_dist: dict[int, int] = {}
for t in tasks:
    cl = t["chain_length"]
    chain_dist[cl] = chain_dist.get(cl, 0) + 1

print(f"  ✓ {len(tasks)}개 태스크 저장 완료 → {OUTPUT_PATH}")
print(f"  • 체인 길이 분포: {', '.join(f'{k}-chain {v}개' for k, v in sorted(chain_dist.items()))}")
print(f"\n[실행 방법]")
print(f"  전체 실행  : python run.py --model gpt-4o-mini --tasks_file data/tool_chaining_tasks.jsonl")
print(f"  일부 실행  : python run.py --model gpt-4o-mini --tasks_file data/tool_chaining_tasks.jsonl --task_ids TC_TASK_003 TC_TASK_009")
print(f"  디버그 모드: python run.py --model gpt-4o-mini --tasks_file data/tool_chaining_tasks.jsonl --debug")
