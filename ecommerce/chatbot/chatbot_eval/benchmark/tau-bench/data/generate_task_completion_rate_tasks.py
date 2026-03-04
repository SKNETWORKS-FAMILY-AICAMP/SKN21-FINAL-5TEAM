"""
generate_task_completion_rate_tasks.py

[목적]
사용자의 변심(Intent Change) 또는 긴 대화 과정 속에서도
최종 비즈니스 목적지(Final Business Destination)에 도달했는가를 평가하기 위한
데이터셋을 생성합니다.

[평가 핵심]
1) 대화 중 사용자가 의도를 변경해도 챗봇이 새 목표를 인식하고 정확히 안내하는지
2) 긴 대화 과정에서 맥락을 유지하며 최종 목표까지 완수하는지
3) 중간에 포기된 목표(intermediate_goals)가 아닌, 최종 목표(final_goal)를 기준으로 성공/실패를 판단

[비즈니스 목적지 도달률 vs Task Completion Rate]
- Task Completion Rate  : 단일 의도로 슬롯 수집 → 툴 호출 → 상태 변경 완수
- 비즈니스 목적지 도달률 : 변심·긴 대화 속에서도 최종 사용자 목표 달성 여부 측정

[11개 시나리오]
- GBD_TASK_001: 취소 요청 → 교환으로 변심                → 최종 교환 신청 완료
- GBD_TASK_002: 환불 요청 → 취소로 변심                  → 최종 주문 취소 완료
- GBD_TASK_003: 교환 요청 → 환불로 변심                  → 최종 환불 신청 완료
- GBD_TASK_004: 상품 추천(A카테고리) → B카테고리로 변경  → 최종 추천 완료
- GBD_TASK_005: 이미지 검색 → 키워드 검색으로 변경        → 최종 상품 발견
- GBD_TASK_006: 리뷰 대상 상품 변경 후 최종 리뷰 등록
- GBD_TASK_007: 중고 판매 조건 변경 후 최종 판매 신청 완료
- GBD_TASK_008: 상품권 코드 오류 재입력 → 최종 등록 완료
- GBD_TASK_009: 주문 조회 중 취소로 의도 전환 → 최종 취소 완료
- GBD_TASK_010: 여러 주제 전환 후 최종 교환 신청 완료    (긴 대화)
- GBD_TASK_011: 두 번 변심(취소→환불→교환) 후 최종 교환 완료

[실행 방법]
    python data/generate_task_completion_rate_tasks.py
    python run.py --model gpt-4o-mini --tasks_file data/task_completion_rate_tasks.jsonl
    python run.py --model gpt-4o-mini --tasks_file data/task_completion_rate_tasks.jsonl --task_ids GBD_TASK_001 GBD_TASK_011
"""

import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent / "task_completion_rate_tasks.jsonl"

# ─── 태스크 정의 ──────────────────────────────────────────────────────────────

tasks = [

    # ── GBD_TASK_001 ─────────────────────────────────────────────────────────────
    # 취소 요청 → 교환으로 변심
    # 배송 완료 상태라 취소가 불가함을 챗봇이 안내 → 사용자가 교환으로 목표 변경
    # 최종 목적지: 교환 신청 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_001",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "hard",
        "instruction": "주문 취소하고 싶어요.",
        "user_goal": (
            "처음에 주문 취소를 요청했으나 챗봇이 '배송 완료 상태라 취소 불가, "
            "교환은 가능하다'고 안내하면서 ORD-20260219-0006 슬림핏 데님 팬츠를 "
            "사이즈 불만족 사유로 교환 신청으로 목표를 변경하여 수거지(서울 마포구 홍익로 20)를 등록하고 최종 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 2,
                "original_intent": "cancel_order",
                "new_intent": "exchange_request",
                "trigger": "챗봇이 배송 완료 후 취소 불가를 안내하고 교환 옵션 제안 → 사용자 동의"
            }
        ],
        "intermediate_goals": ["cancel_order"],
        "final_goal": "exchange_request",
        "missing_slots": ["order_id", "pickup_address"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 7,
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0006",
                "user_id": 1,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "슬림핏 데님 팬츠 블루 M",
                "can_cancel": False,
                "can_exchange": True,
                "delivered_at": "2026-02-22"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_user_orders",
                "required_args": {"user_id": 1, "requires_selection": True, "action_context": "exchange"}
            },
            {
                "tool": "check_exchange_eligibility",
                "required_args": {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈가 맞지 않아요"}
            },
            {
                "tool": "open_address_search",
                "required_args": {}
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
            "type": "final_destination",
            "final_goal": "exchange_request",
            "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
            "excluded_tool_calls": ["cancel_order"],
            "final_state_check": {
                "order_id": "ORD-20260219-0006",
                "expected_status": "EXCHANGE_REQUESTED"
            }
        },
        "chain_length": 4,
        "intent_change_count": 1
    },

    # ── GBD_TASK_002 ─────────────────────────────────────────────────────────────
    # 환불 요청 → 취소로 변심
    # 배송 전(PAYMENT_DONE)임을 확인하고 취소가 더 빠름을 안내 → 취소로 변경
    # 최종 목적지: 주문 취소 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_002",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "medium",
        "instruction": "환불하고 싶어요.",
        "user_goal": (
            "처음에 환불을 요청했으나 챗봇이 '아직 배송 전이므로 취소가 더 빠르고 간편하다'고 "
            "안내한 후 사용자가 동의하여 ORD-20260219-0004 크루넥 스웨터를 취소로 변경, "
            "'단순 변심' 사유로 최종 취소 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 3,
                "original_intent": "refund_request",
                "new_intent": "cancel_order",
                "trigger": "챗봇이 PAYMENT_DONE 상태 확인 후 취소 권유 → 사용자 동의"
            }
        ],
        "intermediate_goals": ["refund_request"],
        "final_goal": "cancel_order",
        "missing_slots": ["order_id", "reason"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 5,
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0004",
                "user_id": 1,
                "status": "PAYMENT_DONE",
                "total_amount": 39000,
                "product_name": "크루넥 스웨터 네이비 M",
                "can_cancel": True,
                "can_return": False
            }]
        },
        "expected_actions": [
            {
                "tool": "get_user_orders",
                "required_args": {"user_id": 1, "requires_selection": True}
            },
            {
                "tool": "cancel_order",
                "required_args": {
                    "order_id": "ORD-20260219-0004",
                    "user_id": 1,
                    "reason": "단순 변심"
                }
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "cancel_order",
            "required_tool_calls": ["cancel_order"],
            "excluded_tool_calls": ["register_return_request"],
            "final_state_check": {
                "order_id": "ORD-20260219-0004",
                "expected_status": "CANCELLED"
            }
        },
        "chain_length": 2,
        "intent_change_count": 1
    },

    # ── GBD_TASK_003 ─────────────────────────────────────────────────────────────
    # 교환 요청 → 환불로 변심
    # 교환 자격 미충족(배송 후 8일 초과) 안내 → 환불로 목표 변경
    # 최종 목적지: 환불(반품) 신청 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_003",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "hard",
        "instruction": "교환 신청하고 싶어요.",
        "user_goal": (
            "처음에 교환을 요청했으나 챗봇이 '교환 가능 기간(7일) 초과로 교환 불가, "
            "환불은 가능하다'고 안내한 후 ORD-20260219-0005 코튼 셔츠에 대해 "
            "환불 신청으로 변경하고 수거지(서울 강남구 테헤란로 123)를 등록하여 최종 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 3,
                "original_intent": "exchange_request",
                "new_intent": "refund_request",
                "trigger": "챗봇이 교환 기간 초과 안내 + 환불 가능 안내 → 사용자가 환불로 변경"
            }
        ],
        "intermediate_goals": ["exchange_request"],
        "final_goal": "refund_request",
        "missing_slots": ["order_id", "pickup_address"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 7,
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0005",
                "user_id": 1,
                "status": "DELIVERED",
                "total_amount": 49000,
                "product_name": "코튼 셔츠 아이보리 S",
                "can_exchange": False,
                "can_return": True,
                "delivered_at": "2026-02-10"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_user_orders",
                "required_args": {"user_id": 1, "requires_selection": True, "action_context": "refund"}
            },
            {
                "tool": "check_refund_eligibility",
                "required_args": {"order_id": "ORD-20260219-0005", "user_id": 1}
            },
            {
                "tool": "open_address_search",
                "required_args": {}
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
            "type": "final_destination",
            "final_goal": "refund_request",
            "required_tool_calls": ["check_refund_eligibility", "register_return_request"],
            "excluded_tool_calls": ["register_exchange_request"],
            "final_state_check": {
                "order_id": "ORD-20260219-0005",
                "expected_status": "RETURN_REQUESTED"
            }
        },
        "chain_length": 4,
        "intent_change_count": 1
    },

    # ── GBD_TASK_004 ─────────────────────────────────────────────────────────────
    # 상품 추천 (Topwear) → 카테고리 변경 (Bottomwear) → 최종 추천 완료
    # 처음에 상의를 요청했다가 대화 중 하의가 더 필요함을 느끼고 변경
    # 최종 목적지: Bottomwear 캐주얼 추천 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_004",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "medium",
        "instruction": "옷 추천해줘. 상의 캐주얼로.",
        "user_goal": (
            "처음에 상의(Topwear) 캐주얼을 요청했다가, 챗봇이 슬롯 확인 중 "
            "'실은 하의가 더 필요한 것 같아요'로 변경 → "
            "최종적으로 캐주얼 검정 하의(Bottomwear, Black, Casual) 추천 결과를 받는다."
        ),
        "intent_changes": [
            {
                "turn": 2,
                "original_intent": "recommend_topwear",
                "new_intent": "recommend_bottomwear",
                "trigger": "사용자가 '아, 사실 하의가 더 필요해요'로 발언하며 카테고리 변경"
            }
        ],
        "intermediate_goals": ["recommend_topwear"],
        "final_goal": "recommend_bottomwear",
        "missing_slots": ["color", "usage"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 5,
        "initial_db_state": {},
        "expected_actions": [
            {
                "tool": "recommend_clothes",
                "required_args": {
                    "category": "Bottomwear",
                    "color": "Black",
                    "usage": "Casual",
                    "user_id": 1
                }
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "recommend_bottomwear",
            "required_tool_calls": ["recommend_clothes"],
            "required_args_check": {"category": "Bottomwear"},
            "final_state_check": {}
        },
        "chain_length": 1,
        "intent_change_count": 1
    },

    # ── GBD_TASK_005 ─────────────────────────────────────────────────────────────
    # 이미지 검색 → 키워드 검색으로 변경
    # 이미지 URL 제공이 어려워 키워드 검색으로 전환
    # 최종 목적지: 키워드 검색 결과 수신
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_005",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "medium",
        "instruction": "이 사진이랑 비슷한 옷 찾아줘.",
        "user_goal": (
            "처음에 이미지 검색을 요청했으나, 이미지 URL을 제공하기 어렵다고 판단하여 "
            "'그냥 오버핏 자켓 키워드로 찾아줘'로 변경 → "
            "최종적으로 키워드 기반 벡터 검색 결과를 받는다."
        ),
        "intent_changes": [
            {
                "turn": 2,
                "original_intent": "image_search",
                "new_intent": "keyword_search",
                "trigger": "챗봇이 이미지 URL 요청 → 사용자 '이미지는 없고, 오버핏 자켓으로 검색해줘'"
            }
        ],
        "intermediate_goals": ["image_search"],
        "final_goal": "keyword_search",
        "missing_slots": ["query"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 4,
        "initial_db_state": {},
        "expected_actions": [
            {
                "tool": "search_products_vector",
                "required_args": {"query": "오버핏 자켓", "limit": 5}
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "keyword_search",
            "required_tool_calls": ["search_products_vector"],
            "excluded_tool_calls": ["search_by_image"],
            "final_state_check": {}
        },
        "chain_length": 1,
        "intent_change_count": 1
    },

    # ── GBD_TASK_006 ─────────────────────────────────────────────────────────────
    # 리뷰 대상 상품 변경 후 최종 리뷰 등록
    # 처음에 A 상품 리뷰를 쓰려다가 B 상품으로 변경
    # 최종 목적지: 변경된 상품(오버핏 후드집업)의 리뷰 등록 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_006",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "hard",
        "instruction": "리뷰 써주세요.",
        "user_goal": (
            "처음에 크루넥 니트 리뷰를 요청했다가 대화 중 '아, 그것보다 후드집업 리뷰가 더 쓰고 싶어요'로 변경 → "
            "ORD-20260219-0003 오버핏 후드집업 그레이 L에 대해 만족도 '높음', "
            "착용감·색감 키워드로 리뷰 초안을 생성하고 별점 5점으로 최종 등록한다."
        ),
        "intent_changes": [
            {
                "turn": 2,
                "original_intent": "review_knit",
                "new_intent": "review_hoodie",
                "trigger": "사용자가 리뷰 대상 상품을 '크루넥 니트'에서 '오버핏 후드집업'으로 변경"
            }
        ],
        "intermediate_goals": ["review_knit"],
        "final_goal": "review_hoodie",
        "missing_slots": ["satisfaction"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 6,
        "initial_db_state": {
            "orders": [
                {
                    "order_id": "ORD-20260219-0003",
                    "user_id": 1,
                    "status": "DELIVERED",
                    "total_amount": 59000,
                    "product_name": "오버핏 후드집업 그레이 L",
                    "delivered_at": "2026-02-21"
                },
                {
                    "order_id": "ORD-20260210-0001",
                    "user_id": 1,
                    "status": "DELIVERED",
                    "total_amount": 45000,
                    "product_name": "크루넥 니트 베이지 M",
                    "delivered_at": "2026-02-14"
                }
            ]
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
                "required_args": {
                    "order_id": "ORD-20260219-0003",
                    "user_id": 1,
                    "rating": 5
                }
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "review_hoodie",
            "required_tool_calls": ["generate_review_draft", "create_review"],
            "required_args_check": {"order_id": "ORD-20260219-0003"},
            "final_state_check": {
                "order_id": "ORD-20260219-0003",
                "review_created": True
            }
        },
        "chain_length": 2,
        "intent_change_count": 1
    },

    # ── GBD_TASK_007 ─────────────────────────────────────────────────────────────
    # 중고 판매 조건 변경 후 최종 판매 신청 완료
    # 가격 조건을 처음과 다르게 수정하고 최종 신청
    # 최종 목적지: 변경된 조건으로 중고 판매 + 수거 신청 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_007",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "hard",
        "instruction": "나이키 운동화 중고로 팔고 싶어요.",
        "user_goal": (
            "처음에 희망가 80,000원으로 요청했다가 '시세를 보니 너무 비싼 것 같아, "
            "50,000원으로 낮출게요'로 변경 → "
            "최종 상태 '상', 희망가 50,000원으로 중고 판매 신청하고, "
            "2026-03-10 서울 강남구 테헤란로 456으로 수거까지 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 3,
                "original_intent": "used_sale_80000",
                "new_intent": "used_sale_50000",
                "trigger": "사용자가 '희망가 80,000원 → 50,000원으로 변경'을 요청"
            }
        ],
        "intermediate_goals": ["used_sale_80000"],
        "final_goal": "used_sale_50000",
        "missing_slots": ["condition", "expected_price"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 6,
        "initial_db_state": {},
        "expected_actions": [
            {
                "tool": "register_used_sale",
                "required_args": {
                    "category": "신발",
                    "item_name": "나이키 운동화",
                    "condition": "상",
                    "expected_price": 50000,
                    "user_id": 1
                }
            },
            {
                "tool": "request_pickup",
                "required_args": {
                    "pickup_date": "2026-03-10",
                    "pickup_address": "서울 강남구 테헤란로 456",
                    "user_id": 1
                }
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "used_sale_50000",
            "required_tool_calls": ["register_used_sale", "request_pickup"],
            "required_args_check": {"expected_price": 50000},
            "final_state_check": {
                "used_sale_created": True,
                "pickup_scheduled": True
            }
        },
        "chain_length": 2,
        "intent_change_count": 1
    },

    # ── GBD_TASK_008 ─────────────────────────────────────────────────────────────
    # 상품권 코드 오류 → 올바른 코드 재입력 → 최종 등록 완료  (긴 대화)
    # 의도 변경은 없으나 오류 재시도로 대화 길어짐
    # 최종 목적지: 상품권 등록 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_008",
        "domain": "retail",
        "category": "long_conversation",
        "difficulty": "medium",
        "instruction": "상품권 등록하고 싶어요.",
        "user_goal": (
            "처음에 잘못된 코드 'GIFT-XXXX-0000'을 입력하여 오류 발생 → "
            "챗봇 안내로 올바른 코드 'GIFT-ABCD-1234'를 재입력하여 최종 계정에 등록하고 잔액 안내를 받는다."
        ),
        "intent_changes": [],
        "intermediate_goals": [],
        "final_goal": "gift_card_register",
        "missing_slots": ["code"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 5,
        "initial_db_state": {
            "gift_cards": []
        },
        "expected_actions": [
            {
                "tool": "register_gift_card",
                "required_args": {
                    "code": "GIFT-ABCD-1234",
                    "user_id": 1
                },
                "note": "첫 시도(GIFT-XXXX-0000)는 실패하고, 올바른 코드로 재시도하여 성공해야 함"
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "gift_card_register",
            "required_tool_calls": ["register_gift_card"],
            "required_args_check": {"code": "GIFT-ABCD-1234"},
            "final_state_check": {
                "gift_card_registered": True,
                "code": "GIFT-ABCD-1234"
            }
        },
        "chain_length": 1,
        "intent_change_count": 0
    },

    # ── GBD_TASK_009 ─────────────────────────────────────────────────────────────
    # 주문 내역 조회 → 취소로 의도 전환  (긴 대화)
    # 조회를 하다가 특정 주문을 취소하기로 결정
    # 최종 목적지: 주문 취소 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_009",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "hard",
        "instruction": "주문 내역 조회하고 싶어요.",
        "user_goal": (
            "주문 목록을 조회하던 중 ORD-20260219-0004 크루넥 스웨터 상세 정보를 확인하고, "
            "'이거 취소할게요'로 의도가 전환되어 '다른 색으로 다시 주문하려고요' 사유로 최종 취소 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 4,
                "original_intent": "order_inquiry",
                "new_intent": "cancel_order",
                "trigger": "주문 상세 확인 후 사용자가 '이거 취소할게요'로 의도 전환"
            }
        ],
        "intermediate_goals": ["order_inquiry"],
        "final_goal": "cancel_order",
        "missing_slots": ["reason"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 7,
        "initial_db_state": {
            "orders": [
                {
                    "order_id": "ORD-20260219-0004",
                    "user_id": 1,
                    "status": "PAYMENT_DONE",
                    "total_amount": 39000,
                    "product_name": "크루넥 스웨터 네이비 M",
                    "can_cancel": True,
                    "created_at": "2026-02-19"
                },
                {
                    "order_id": "ORD-20260219-0003",
                    "user_id": 1,
                    "status": "DELIVERED",
                    "total_amount": 59000,
                    "product_name": "오버핏 후드집업 그레이 L",
                    "can_cancel": False,
                    "created_at": "2026-02-19"
                }
            ]
        },
        "expected_actions": [
            {
                "tool": "get_user_orders",
                "required_args": {"user_id": 1}
            },
            {
                "tool": "get_order_details",
                "required_args": {"order_id": "ORD-20260219-0004", "user_id": 1}
            },
            {
                "tool": "cancel_order",
                "required_args": {
                    "order_id": "ORD-20260219-0004",
                    "user_id": 1,
                    "reason": "다른 색으로 다시 주문하려고요"
                }
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "cancel_order",
            "required_tool_calls": ["get_user_orders", "get_order_details", "cancel_order"],
            "final_state_check": {
                "order_id": "ORD-20260219-0004",
                "expected_status": "CANCELLED"
            }
        },
        "chain_length": 3,
        "intent_change_count": 1
    },

    # ── GBD_TASK_010 ─────────────────────────────────────────────────────────────
    # 여러 주제 전환 후 최종 교환 신청  (긴 대화 + 1회 변심)
    # 상품 검색 → 주문 조회 → 교환 신청으로 이어지는 긴 대화
    # 최종 목적지: 교환 신청 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_010",
        "domain": "retail",
        "category": "long_conversation",
        "difficulty": "hard",
        "instruction": "안녕하세요, 몇 가지 물어봐도 될까요?",
        "user_goal": (
            "상품 검색(여름 반팔티)을 먼저 요청하고, "
            "이어서 주문 내역을 조회한 뒤, "
            "마지막으로 ORD-20260219-0006 슬림핏 데님 팬츠를 사이즈 불만족으로 교환 신청하고 "
            "수거지(서울 마포구 홍익로 20)를 등록하여 최종 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 2,
                "original_intent": "product_search",
                "new_intent": "order_inquiry",
                "trigger": "상품 검색 결과 확인 후 주문 내역 조회로 전환"
            },
            {
                "turn": 5,
                "original_intent": "order_inquiry",
                "new_intent": "exchange_request",
                "trigger": "주문 내역 확인 후 교환 신청으로 전환"
            }
        ],
        "intermediate_goals": ["product_search", "order_inquiry"],
        "final_goal": "exchange_request",
        "missing_slots": ["pickup_address"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 10,
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
                "tool": "search_products_vector",
                "required_args": {"query": "여름 반팔티", "limit": 5}
            },
            {
                "tool": "get_user_orders",
                "required_args": {"user_id": 1}
            },
            {
                "tool": "check_exchange_eligibility",
                "required_args": {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈가 맞지 않아요"}
            },
            {
                "tool": "open_address_search",
                "required_args": {}
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
            "type": "final_destination",
            "final_goal": "exchange_request",
            "required_tool_calls": ["register_exchange_request"],
            "final_state_check": {
                "order_id": "ORD-20260219-0006",
                "expected_status": "EXCHANGE_REQUESTED"
            }
        },
        "chain_length": 5,
        "intent_change_count": 2
    },

    # ── GBD_TASK_011 ─────────────────────────────────────────────────────────────
    # 두 번 변심: 취소 → 환불 → 교환  (다중 변심)
    # 처음엔 취소, 그 다음엔 환불로 바꿨다가 최종적으로 교환으로 결정
    # 최종 목적지: 교환 신청 완료
    # ─────────────────────────────────────────────────────────────────────────────
    {
        "task_id": "GBD_TASK_011",
        "domain": "retail",
        "category": "intent_change",
        "difficulty": "hard",
        "instruction": "주문 취소할게요.",
        "user_goal": (
            "처음에 취소를 요청했으나 '이미 배송 완료라 취소 불가'를 듣고 환불로 변경, "
            "이후 '사실 같은 상품 다른 사이즈가 필요해서 교환하고 싶어요'로 최종 변경 → "
            "ORD-20260219-0006 슬림핏 데님 팬츠를 사이즈 불만족 사유로 교환 신청하고 "
            "수거지(서울 서초구 반포대로 45)를 등록하여 최종 완료한다."
        ),
        "intent_changes": [
            {
                "turn": 2,
                "original_intent": "cancel_order",
                "new_intent": "refund_request",
                "trigger": "챗봇이 배송 완료 후 취소 불가 안내 → 사용자 환불로 변경"
            },
            {
                "turn": 4,
                "original_intent": "refund_request",
                "new_intent": "exchange_request",
                "trigger": "사용자가 '같은 상품 다른 사이즈 필요해요'로 교환으로 최종 변경"
            }
        ],
        "intermediate_goals": ["cancel_order", "refund_request"],
        "final_goal": "exchange_request",
        "missing_slots": ["pickup_address"],
        "slot_filling_required": True,
        "completion_required": True,
        "conversation_turns_estimate": 9,
        "initial_db_state": {
            "orders": [{
                "order_id": "ORD-20260219-0006",
                "user_id": 1,
                "status": "DELIVERED",
                "total_amount": 59000,
                "product_name": "슬림핏 데님 팬츠 블루 M",
                "can_cancel": False,
                "can_return": True,
                "can_exchange": True,
                "delivered_at": "2026-02-22"
            }]
        },
        "expected_actions": [
            {
                "tool": "get_user_orders",
                "required_args": {"user_id": 1, "requires_selection": True, "action_context": "exchange"}
            },
            {
                "tool": "check_exchange_eligibility",
                "required_args": {"order_id": "ORD-20260219-0006", "user_id": 1, "reason": "사이즈가 맞지 않아요"}
            },
            {
                "tool": "open_address_search",
                "required_args": {}
            },
            {
                "tool": "register_exchange_request",
                "required_args": {
                    "order_id": "ORD-20260219-0006",
                    "user_id": 1,
                    "reason": "사이즈가 맞지 않아요",
                    "pickup_address": "서울 서초구 반포대로 45",
                    "confirmed": True
                }
            }
        ],
        "success_criteria": {
            "type": "final_destination",
            "final_goal": "exchange_request",
            "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
            "excluded_tool_calls": ["cancel_order", "register_return_request"],
            "final_state_check": {
                "order_id": "ORD-20260219-0006",
                "expected_status": "EXCHANGE_REQUESTED"
            }
        },
        "chain_length": 4,
        "intent_change_count": 2
    },

]

# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
print(f"[1] 비즈니스 목적지 도달률 태스크 {len(tasks)}개 생성 중...")
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    for task in tasks:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")

# ─── 통계 출력 ────────────────────────────────────────────────────────────────
intent_change_tasks = sum(1 for t in tasks if int(t["intent_change_count"]) > 0)  # type: ignore[arg-type]
long_conv_tasks     = sum(1 for t in tasks if t["category"] == "long_conversation")
multi_change_tasks  = sum(1 for t in tasks if int(t["intent_change_count"]) >= 2)  # type: ignore[arg-type]

difficulty_dist: dict[str, int] = {}
for t in tasks:
    d = str(t["difficulty"])
    difficulty_dist[d] = difficulty_dist.get(d, 0) + 1

chain_dist: dict[int, int] = {}
for t in tasks:
    cl = int(t["chain_length"])  # type: ignore[arg-type]
    chain_dist[cl] = chain_dist.get(cl, 0) + 1

print(f"  [OK] {len(tasks)}개 태스크 저장 완료 -> {OUTPUT_PATH}")
print(f"  - 변심 포함 태스크: {intent_change_tasks}개 | 긴 대화(변심 없음): {long_conv_tasks}개")
print(f"  - 다중 변심(2회 이상): {multi_change_tasks}개")
print(f"  - 난이도 분포: {', '.join(f'{k} {v}개' for k, v in sorted(difficulty_dist.items()))}")
print(f"  - 체인 길이 분포: {', '.join(f'{k}-chain {v}개' for k, v in sorted(chain_dist.items()))}")
print("\n[실행 방법]")
print("  전체 실행  : python run.py --model gpt-4o-mini --tasks_file data/task_completion_rate_tasks.jsonl")
print("  일부 실행  : python run.py --model gpt-4o-mini --tasks_file data/task_completion_rate_tasks.jsonl --task_ids GBD_TASK_001 GBD_TASK_011")
print("  디버그 모드: python run.py --model gpt-4o-mini --tasks_file data/task_completion_rate_tasks.jsonl --debug")
