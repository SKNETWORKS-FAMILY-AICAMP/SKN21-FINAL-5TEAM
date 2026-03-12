"""
generate_task_completion_rate_tasks.py

[목적]
사용자의 변심(Intent Change) 또는 긴 대화 과정 속에서도
최종 비즈니스 목적지(Final Business Destination)에 도달했는가를 평가하기 위한
데이터셋을 생성합니다.
eval_data.jsonl의 각 user row를 기반으로 DB에서 실제 주문/사용자 정보를 조회하여
user row별로 전체 태스크를 동적으로 생성합니다.
(해당 user에 없는 action type의 태스크는 스킵)

[평가 핵심]
1) 대화 중 사용자가 의도를 변경해도 챗봇이 새 목표를 인식하고 정확히 안내하는지
2) 긴 대화 과정에서 맥락을 유지하며 최종 목표까지 완수하는지
3) 중간에 포기된 목표(intermediate_goals)가 아닌, 최종 목표(final_goal)를 기준으로 성공/실패를 판단

[비즈니스 목적지 도달률 vs Task Completion Rate]
- Task Completion Rate  : 단일 의도로 슬롯 수집 → 툴 호출 → 상태 변경 완수
- 비즈니스 목적지 도달률 : 변심·긴 대화 속에서도 최종 사용자 목표 달성 여부 측정

[데이터 소스]
A. eval_data.jsonl → user row별 action(주문번호, 사용자 이메일)
B. DB 조회 → 사용자 ID, 주문 상세(상품명, 가격, 상태 등)

[11개 시나리오]
- GBD_TASK_001: 취소 요청 → 교환으로 변심                → 최종 교환 신청 완료      (교환 action 필요)
- GBD_TASK_002: 환불 요청 → 취소로 변심                  → 최종 주문 취소 완료      (주문취소 action 필요)
- GBD_TASK_003: 교환 요청 → 환불로 변심                  → 최종 환불 신청 완료      (환불 action 필요)
- GBD_TASK_004: 상품 추천(A카테고리) → B카테고리로 변경  → 최종 추천 완료           (action 불필요)
- GBD_TASK_005: 이미지 검색 → 키워드 검색으로 변경        → 최종 상품 발견           (action 불필요)
- GBD_TASK_006: 리뷰 대상 상품 변경 후 최종 리뷰 등록                               (환불+교환 action 필요)
- GBD_TASK_007: 중고 판매 조건 변경 후 최종 판매 신청 완료                           (action 불필요)
- GBD_TASK_008: 상품권 코드 오류 재입력 → 최종 등록 완료                             (action 불필요)
- GBD_TASK_009: 주문 조회 중 취소로 의도 전환 → 최종 취소 완료                       (주문취소 action 필요)
- GBD_TASK_010: 여러 주제 전환 후 최종 교환 신청 완료    (긴 대화)                   (교환 action 필요)
- GBD_TASK_011: 두 번 변심(취소→환불→교환) 후 최종 교환 완료                        (교환 action 필요)

[실행 방법]
    python data/generate_task_completion_rate_tasks.py
    python run.py --tasks_file data/task_completion_rate_tasks.jsonl
    python run.py --tasks_file data/task_completion_rate_tasks.jsonl --task_ids GBD_TASK_001 GBD_TASK_011
"""

import json
import sys
from pathlib import Path
from typing import Any

# ─── 경로 설정 ───────────────────────────────────────────────────────────────
_THIS_DIR   = Path(__file__).resolve().parent   # tau-bench/data/
_BENCH_ROOT = _THIS_DIR.parent                  # tau-bench/

OUTPUT_PATH = _THIS_DIR / "task_completion_rate_tasks.jsonl"
EVAL_DATA_PATH = _BENCH_ROOT.parent / "eval_data.jsonl"


def find_project_root(current_path: Path, marker: str = ".env") -> Path:
    """현재 경로에서 위로 올라가며 marker 파일이 있는 디렉토리를 프로젝트 루트로 반환합니다."""
    for parent in [current_path] + list(current_path.parents):
        if (parent / marker).exists():
            return parent
    return current_path.parents[4]


PROJECT_ROOT = find_project_root(_BENCH_ROOT)

# 프로젝트 루트를 sys.path에 추가 (backend 모듈 import용)
sys.path.insert(0, str(PROJECT_ROOT))


# ─── 헬퍼 함수 ───────────────────────────────────────────────────────────────
def load_eval_data(path):
    """eval_data.jsonl에서 user row별 데이터를 리스트로 반환합니다.
    반환 형태: [{"user_email": "...", "actions": {"주문취소": {"order_number": "..."}, ...}}, ...]
    각 user row 하나당 전체 태스크를 한 번 생성하며,
    해당 user에 없는 action type의 태스크는 스킵합니다.
    """
    users = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("type") != "user":
                continue
            user_email = entry["data"]["user_email"]
            actions = {}
            for action in entry.get("action", []):
                type_key = action["type"]
                actions[type_key] = action.get("data", {})
            users.append({"user_email": user_email, "actions": actions})
    return users


# DB 주문 상태 → 태스크 상태 매핑
STATUS_MAP = {
    "pending": "PENDING",
    "paid": "PAYMENT_DONE",
    "preparing": "PREPARING",
    "shipped": "SHIPPED",
    "delivered": "DELIVERED",
    "cancelled": "CANCELLED",
    "refunded": "REFUNDED",
}


def build_item_name(item_dict):
    """enriched order item에서 표시용 상품명을 구성합니다."""
    parts = [item_dict.get("product_name", "상품")]
    if item_dict.get("product_color"):
        parts.append(item_dict["product_color"])
    if item_dict.get("product_size"):
        parts.append(item_dict["product_size"])
    return " ".join(parts)


def extract_order_info(order_detail):
    """enriched order dict에서 태스크에 필요한 상세 정보를 추출합니다."""
    status = order_detail.get("status", "pending")
    items = order_detail.get("items", [])
    first_item = items[0] if items else {}

    return {
        "order_id": order_detail["order_number"],
        "status_raw": status,
        "status": STATUS_MAP.get(status, status.upper()),
        "item_name": build_item_name(first_item),
        "product_name": first_item.get("product_name", "상품"),
        "amount": int(float(order_detail.get("total_amount", 0))),
        "is_cancellable": status in ("paid", "preparing"),
        "is_refundable": status in ("shipped", "delivered"),
        "is_exchangeable": status == "delivered",
        "created_at": order_detail.get("created_at", ""),
        "updated_at": order_detail.get("updated_at", ""),
    }


# ─── eval_data.jsonl + DB 조회 ──────────────────────────────────────────────
print("[1] eval_data.jsonl 및 DB 데이터 로드 중...")

user_rows = load_eval_data(EVAL_DATA_PATH)
print(f"  • eval_data 로드: {len(user_rows)}명의 사용자")

from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.router.users.crud import get_user_by_email
from ecommerce.platform.backend.app.router.orders.crud import (
    get_order_by_order_number,
    get_orders_by_user_id,
    enrich_order_with_product_names,
)
# User/Order 모델의 relationship 참조를 해결하기 위해 관련 모델 전부 import
import ecommerce.platform.backend.app.router.shipping.models
import ecommerce.platform.backend.app.router.carts.models
import ecommerce.platform.backend.app.router.orders.models
import ecommerce.platform.backend.app.router.products.models
import ecommerce.platform.backend.app.router.points.models
import ecommerce.platform.backend.app.router.reviews.models
import ecommerce.platform.backend.app.router.user_history.models
import ecommerce.platform.backend.app.router.payments.models

db = SessionLocal()
try:
    for u_row in user_rows:
        email = u_row["user_email"]
        user = get_user_by_email(db, email)
        if not user:
            print(f"  ✗ 사용자를 찾을 수 없습니다: {email}")
            sys.exit(1)
        u_row["user_id"] = user.id
        print(f"  • 사용자 조회 완료: {email} → user_id={user.id}")

        for action_type, action_data in u_row["actions"].items():
            order_number = action_data.get("order_number")
            if not order_number:
                continue
            obj = get_order_by_order_number(db, order_number)
            if not obj:
                print(f"  ✗ {action_type} 주문을 찾을 수 없습니다: {order_number}")
                sys.exit(1)
            info = extract_order_info(enrich_order_with_product_names(db, obj))
            info["user_id"] = user.id
            action_data["order_info"] = info
            print(f"  • {action_type}: {info['order_id']} ({info['status']}) - {info['item_name']} {info['amount']}원 (user_id={user.id})")

        # action 타입별 존재 여부 출력 (없는 타입은 해당 태스크 스킵)
        for at in ["주문취소", "환불", "교환"]:
            if at not in u_row["actions"]:
                print(f"  ⚠ '{at}' action이 없습니다. 관련 태스크를 스킵합니다.")

finally:
    db.close()


# ─── delivered_at 계산 ───────────────────────────────────────────────────────
# 교환/환불 주문의 배송 완료일: updated_at 사용, 없으면 created_at 기반
def get_delivered_at(info):
    """주문 정보에서 배송 완료일을 추출합니다."""
    dt = info.get("updated_at") or info.get("created_at") or ""
    if dt:
        return str(dt)[:10]  # YYYY-MM-DD 형식으로 자르기
    return "2026-02-22"


def make_user_task_id(base_id: str, u_idx: int, total_users: int) -> str:
    """복수 사용자일 때 태스크 ID에 사용자 접미사를 붙입니다. 단수면 원본 ID 그대로."""
    if total_users <= 1:
        return base_id
    return f"{base_id}_U{u_idx + 1:03d}"


# ─── 태스크 정의 (user row별 동적 생성) ──────────────────────────────────────
print("\n[2] 비즈니스 목적지 도달률 태스크 생성 중...")

tasks: list[dict[str, Any]] = []
total_users = len(user_rows)

for u_idx, u_row in enumerate(user_rows):
    user_id = u_row["user_id"]
    cancel_info = u_row["actions"].get("주문취소", {}).get("order_info")
    refund_info = u_row["actions"].get("환불", {}).get("order_info")
    exchange_info = u_row["actions"].get("교환", {}).get("order_info")

    print(f"\n  ── 사용자 {u_idx + 1}/{total_users}: {u_row['user_email']} (user_id={user_id}) ──")

    # ── GBD_TASK_001 ─────────────────────────────────────────────────────────
    # 취소 요청 → 교환으로 변심 (교환 action 필요)
    # 배송 완료 상태라 취소가 불가함을 챗봇이 안내 → 사용자가 교환으로 목표 변경
    # 최종 목적지: 교환 신청 완료
    # ─────────────────────────────────────────────────────────────────────────
    if exchange_info:
        _ei = exchange_info
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_001", u_idx, total_users),
            "domain": "retail",
            "category": "intent_change",
            "difficulty": "hard",
            "instruction": "주문 취소하고 싶어요.",
            "user_goal": (
                f"처음에 주문 취소를 요청했으나 챗봇이 '배송 완료 상태라 취소 불가, "
                f"교환은 가능하다'고 안내하면서 "
                f"{_ei['order_id']} {_ei['item_name']}"
                f"을 사이즈 불만족 사유로 교환 신청으로 목표를 변경하여 수거지(서울 마포구 홍익로 20)를 등록하고 최종 완료한다."
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
                "orders": [
                    {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "status": _ei["status"],
                        "total_amount": _ei["amount"],
                        "product_name": _ei["item_name"],
                        "can_cancel": False,
                        "can_exchange": True,
                        "delivered_at": get_delivered_at(_ei)
                    }
                ]
            },
            "expected_actions": [
                {
                    "tool": "get_user_orders",
                    "required_args": {"user_id": _ei["user_id"], "requires_selection": True, "action_context": "exchange"}
                },
                {
                    "tool": "check_exchange_eligibility",
                    "required_args": {"order_id": _ei["order_id"], "user_id": _ei["user_id"], "reason": "사이즈가 맞지 않아요"}
                },
                {
                    "tool": "open_address_search",
                    "required_args": {}
                },
                {
                    "tool": "register_exchange_request",
                    "required_args": {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "reason": "사이즈가 맞지 않아요",
                        "pickup_address": "서울 마포구 홍익로 20",
                        "confirmed": True
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": "exchange_request",
                "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
                "excluded_tool_calls": ["cancel_order"],
                "final_state_check": [
                    {"order_id": _ei["order_id"], "expected_status": "EXCHANGE_REQUESTED"}
                ]
            },
            "chain_length": 4,
            "intent_change_count": 1
        })
        print(f"    ✓ GBD_TASK_001 생성 (교환: {_ei['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_001 스킵: 교환 action 없음")

    # ── GBD_TASK_002 ─────────────────────────────────────────────────────────
    # 환불 요청 → 취소로 변심 (주문취소 action 필요)
    # 배송 전(PAYMENT_DONE)임을 확인하고 취소가 더 빠름을 안내 → 취소로 변경
    # 최종 목적지: 주문 취소 완료
    # ─────────────────────────────────────────────────────────────────────────
    if cancel_info:
        _ci = cancel_info
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_002", u_idx, total_users),
            "domain": "retail",
            "category": "intent_change",
            "difficulty": "medium",
            "instruction": "환불하고 싶어요.",
            "user_goal": (
                f"처음에 환불을 요청했으나 챗봇이 '아직 배송 전이므로 취소가 더 빠르고 간편하다'고 "
                f"안내한 후 사용자가 동의하여 "
                f"{_ci['order_id']} {_ci['item_name']}"
                f"을 취소로 변경, '단순 변심' 사유로 최종 취소 완료한다."
            ),
            "intent_changes": [
                {
                    "turn": 3,
                    "original_intent": "refund_request",
                    "new_intent": "cancel_order",
                    "trigger": f"챗봇이 {_ci['status']} 상태 확인 후 취소 권유 → 사용자 동의"
                }
            ],
            "intermediate_goals": ["refund_request"],
            "final_goal": "cancel_order",
            "missing_slots": ["order_id", "reason"],
            "slot_filling_required": True,
            "completion_required": True,
            "conversation_turns_estimate": 5,
            "initial_db_state": {
                "orders": [
                    {
                        "order_id": _ci["order_id"],
                        "user_id": _ci["user_id"],
                        "status": _ci["status"],
                        "total_amount": _ci["amount"],
                        "product_name": _ci["item_name"],
                        "can_cancel": True,
                        "can_return": False
                    }
                ]
            },
            "expected_actions": [
                {
                    "tool": "get_user_orders",
                    "required_args": {"user_id": _ci["user_id"], "requires_selection": True}
                },
                {
                    "tool": "cancel_order",
                    "required_args": {
                        "order_id": _ci["order_id"],
                        "user_id": _ci["user_id"],
                        "reason": "단순 변심"
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": "cancel_order",
                "required_tool_calls": ["cancel_order"],
                "excluded_tool_calls": ["register_return_request"],
                "final_state_check": [
                    {"order_id": _ci["order_id"], "expected_status": "CANCELLED"}
                ]
            },
            "chain_length": 2,
            "intent_change_count": 1
        })
        print(f"    ✓ GBD_TASK_002 생성 (취소: {_ci['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_002 스킵: 주문취소 action 없음")

    # ── GBD_TASK_003 ─────────────────────────────────────────────────────────
    # 교환 요청 → 환불로 변심 (환불 action 필요)
    # 교환 자격 미충족(배송 후 8일 초과) 안내 → 환불로 목표 변경
    # 최종 목적지: 환불(반품) 신청 완료
    # ─────────────────────────────────────────────────────────────────────────
    if refund_info:
        _ri = refund_info
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_003", u_idx, total_users),
            "domain": "retail",
            "category": "intent_change",
            "difficulty": "hard",
            "instruction": "교환 신청하고 싶어요.",
            "user_goal": (
                f"처음에 교환을 요청했으나 챗봇이 '교환 가능 기간(7일) 초과로 교환 불가, "
                f"환불은 가능하다'고 안내한 후 "
                f"{_ri['order_id']} {_ri['item_name']}"
                f"에 대해 환불 신청으로 변경하고 수거지(서울 강남구 테헤란로 123)를 등록하여 최종 완료한다."
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
                "orders": [
                    {
                        "order_id": _ri["order_id"],
                        "user_id": _ri["user_id"],
                        "status": _ri["status"],
                        "total_amount": _ri["amount"],
                        "product_name": _ri["item_name"],
                        "can_exchange": False,
                        "can_return": True,
                        "delivered_at": get_delivered_at(_ri)
                    }
                ]
            },
            "expected_actions": [
                {
                    "tool": "get_user_orders",
                    "required_args": {"user_id": _ri["user_id"], "requires_selection": True, "action_context": "refund"}
                },
                {
                    "tool": "check_refund_eligibility",
                    "required_args": {"order_id": _ri["order_id"], "user_id": _ri["user_id"]}
                },
                {
                    "tool": "open_address_search",
                    "required_args": {}
                },
                {
                    "tool": "register_return_request",
                    "required_args": {
                        "order_id": _ri["order_id"],
                        "user_id": _ri["user_id"],
                        "pickup_address": "서울 강남구 테헤란로 123",
                        "confirmed": True
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": "refund_request",
                "required_tool_calls": ["check_refund_eligibility", "register_return_request"],
                "excluded_tool_calls": ["register_exchange_request"],
                "final_state_check": [
                    {"order_id": _ri["order_id"], "expected_status": "RETURN_REQUESTED"}
                ]
            },
            "chain_length": 4,
            "intent_change_count": 1
        })
        print(f"    ✓ GBD_TASK_003 생성 (환불: {_ri['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_003 스킵: 환불 action 없음")

    # ── GBD_TASK_004 ─────────────────────────────────────────────────────────
    # 상품 추천 (Topwear) → 카테고리 변경 (Bottomwear) → 최종 추천 완료
    # 처음에 상의를 요청했다가 대화 중 하의가 더 필요함을 느끼고 변경
    # 최종 목적지: Bottomwear 캐주얼 추천 완료 (action 불필요)
    # ─────────────────────────────────────────────────────────────────────────
    tasks.append({
        "task_id": make_user_task_id("GBD_TASK_004", u_idx, total_users),
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
                    "user_id": user_id
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
    })
    print(f"    ✓ GBD_TASK_004 생성 (상품 추천)")

    # ── GBD_TASK_005 ─────────────────────────────────────────────────────────
    # 이미지 검색 → 키워드 검색으로 변경 (action 불필요)
    # 이미지 URL 제공이 어려워 키워드 검색으로 전환
    # 최종 목적지: 키워드 검색 결과 수신
    # ─────────────────────────────────────────────────────────────────────────
    tasks.append({
        "task_id": make_user_task_id("GBD_TASK_005", u_idx, total_users),
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
    })
    print(f"    ✓ GBD_TASK_005 생성 (이미지→키워드 검색)")

    # ── GBD_TASK_006 ─────────────────────────────────────────────────────────
    # 리뷰 대상 상품 변경 후 최종 리뷰 등록 (환불+교환 action 모두 필요)
    # 처음에 환불 상품 리뷰를 쓰려다가 교환 상품으로 변경
    # 최종 목적지: 변경된 상품의 리뷰 등록 완료
    # ─────────────────────────────────────────────────────────────────────────
    if refund_info and exchange_info:
        _ri = refund_info
        _ei = exchange_info
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_006", u_idx, total_users),
            "domain": "retail",
            "category": "intent_change",
            "difficulty": "hard",
            "instruction": "리뷰 써주세요.",
            "user_goal": (
                f"처음에 {_ri['item_name']} 리뷰를 요청했다가 대화 중 "
                f"{_ei['item_name']}"
                f" 리뷰가 더 쓰고 싶어요'로 변경 → "
                f"{_ei['order_id']} {_ei['item_name']}"
                f"에 대해 만족도 '높음', 착용감·색감 키워드로 리뷰 초안을 생성하고 별점 5점으로 최종 등록한다."
            ),
            "intent_changes": [
                {
                    "turn": 2,
                    "original_intent": f"review_{_ri['product_name']}",
                    "new_intent": f"review_{_ei['product_name']}",
                    "trigger": f"사용자가 리뷰 대상 상품을 '{_ri['item_name']}'에서 '{_ei['item_name']}'으로 변경"
                }
            ],
            "intermediate_goals": [f"review_{_ri['product_name']}"],
            "final_goal": f"review_{_ei['product_name']}",
            "missing_slots": ["satisfaction"],
            "slot_filling_required": True,
            "completion_required": True,
            "conversation_turns_estimate": 6,
            "initial_db_state": {
                "orders": [
                    {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "status": _ei["status"],
                        "total_amount": _ei["amount"],
                        "product_name": _ei["item_name"],
                        "delivered_at": get_delivered_at(_ei)
                    },
                    {
                        "order_id": _ri["order_id"],
                        "user_id": _ri["user_id"],
                        "status": _ri["status"],
                        "total_amount": _ri["amount"],
                        "product_name": _ri["item_name"],
                        "delivered_at": get_delivered_at(_ri)
                    }
                ]
            },
            "expected_actions": [
                {
                    "tool": "generate_review_draft",
                    "required_args": {
                        "product_name": _ei["item_name"],
                        "satisfaction": "높음",
                        "keywords": ["착용감", "색감"]
                    }
                },
                {
                    "tool": "create_review",
                    "required_args": {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "rating": 5
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": f"review_{_ei['product_name']}",
                "required_tool_calls": ["generate_review_draft", "create_review"],
                "required_args_check": {"order_id": _ei["order_id"]},
                "final_state_check": [
                    {"order_id": _ei["order_id"], "review_created": True}
                ]
            },
            "chain_length": 2,
            "intent_change_count": 1
        })
        print(f"    ✓ GBD_TASK_006 생성 (리뷰: {_ri['order_id']} → {_ei['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_006 스킵: 환불+교환 action 모두 필요")

    # ── GBD_TASK_007 ─────────────────────────────────────────────────────────
    # 중고 판매 조건 변경 후 최종 판매 신청 완료 (action 불필요)
    # 가격 조건을 처음과 다르게 수정하고 최종 신청
    # 최종 목적지: 변경된 조건으로 중고 판매 + 수거 신청 완료
    # ─────────────────────────────────────────────────────────────────────────
    tasks.append({
        "task_id": make_user_task_id("GBD_TASK_007", u_idx, total_users),
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
                    "user_id": user_id
                }
            },
            {
                "tool": "request_pickup",
                "required_args": {
                    "pickup_date": "2026-03-10",
                    "pickup_address": "서울 강남구 테헤란로 456",
                    "user_id": user_id
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
    })
    print(f"    ✓ GBD_TASK_007 생성 (중고 판매)")

    # ── GBD_TASK_008 ─────────────────────────────────────────────────────────
    # 상품권 코드 오류 → 올바른 코드 재입력 → 최종 등록 완료 (action 불필요)
    # 의도 변경은 없으나 오류 재시도로 대화 길어짐
    # 최종 목적지: 상품권 등록 완료
    # ─────────────────────────────────────────────────────────────────────────
    tasks.append({
        "task_id": make_user_task_id("GBD_TASK_008", u_idx, total_users),
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
                    "user_id": user_id
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
    })
    print(f"    ✓ GBD_TASK_008 생성 (상품권 등록)")

    # ── GBD_TASK_009 ─────────────────────────────────────────────────────────
    # 주문 내역 조회 → 취소로 의도 전환 (주문취소 action 필요)
    # 조회를 하다가 특정 주문을 취소하기로 결정
    # 최종 목적지: 주문 취소 완료
    # ─────────────────────────────────────────────────────────────────────────
    if cancel_info:
        _ci = cancel_info
        # initial_db_state에 교환 주문도 포함 (주문 목록 조회 맥락)
        _extra_orders = []
        if exchange_info:
            _extra_orders.append({
                "order_id": exchange_info["order_id"],
                "user_id": exchange_info["user_id"],
                "status": exchange_info["status"],
                "total_amount": exchange_info["amount"],
                "product_name": exchange_info["item_name"],
                "can_cancel": False,
                "created_at": exchange_info["created_at"][:10] if exchange_info["created_at"] else ""
            })
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_009", u_idx, total_users),
            "domain": "retail",
            "category": "intent_change",
            "difficulty": "hard",
            "instruction": "주문 내역 조회하고 싶어요.",
            "user_goal": (
                f"주문 목록을 조회하던 중 "
                f"{_ci['order_id']} {_ci['item_name']}"
                f" 상세 정보를 확인하고, '이거 취소할게요'로 의도가 전환되어 '다른 색으로 다시 주문하려고요' 사유로 최종 취소 완료한다."
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
                        "order_id": _ci["order_id"],
                        "user_id": _ci["user_id"],
                        "status": _ci["status"],
                        "total_amount": _ci["amount"],
                        "product_name": _ci["item_name"],
                        "can_cancel": True,
                        "created_at": _ci["created_at"][:10] if _ci["created_at"] else ""
                    }
                ] + _extra_orders
            },
            "expected_actions": [
                {
                    "tool": "get_user_orders",
                    "required_args": {"user_id": _ci["user_id"]}
                },
                {
                    "tool": "get_order_details",
                    "required_args": {"order_id": _ci["order_id"], "user_id": _ci["user_id"]}
                },
                {
                    "tool": "cancel_order",
                    "required_args": {
                        "order_id": _ci["order_id"],
                        "user_id": _ci["user_id"],
                        "reason": "다른 색으로 다시 주문하려고요"
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": "cancel_order",
                "required_tool_calls": ["get_user_orders", "get_order_details", "cancel_order"],
                "final_state_check": [
                    {"order_id": _ci["order_id"], "expected_status": "CANCELLED"}
                ]
            },
            "chain_length": 3,
            "intent_change_count": 1
        })
        print(f"    ✓ GBD_TASK_009 생성 (조회→취소: {_ci['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_009 스킵: 주문취소 action 없음")

    # ── GBD_TASK_010 ─────────────────────────────────────────────────────────
    # 여러 주제 전환 후 최종 교환 신청 (교환 action 필요)
    # 상품 검색 → 주문 조회 → 교환 신청으로 이어지는 긴 대화
    # 최종 목적지: 교환 신청 완료
    # ─────────────────────────────────────────────────────────────────────────
    if exchange_info:
        _ei = exchange_info
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_010", u_idx, total_users),
            "domain": "retail",
            "category": "long_conversation",
            "difficulty": "hard",
            "instruction": "안녕하세요, 몇 가지 물어봐도 될까요?",
            "user_goal": (
                f"상품 검색(여름 반팔티)을 먼저 요청하고, "
                f"이어서 주문 내역을 조회한 뒤, "
                f"마지막으로 "
                f"{_ei['order_id']} {_ei['item_name']}"
                f"을 사이즈 불만족으로 교환 신청하고 수거지(서울 마포구 홍익로 20)를 등록하여 최종 완료한다."
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
                "orders": [
                    {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "status": _ei["status"],
                        "total_amount": _ei["amount"],
                        "product_name": _ei["item_name"],
                        "can_exchange": True,
                        "delivered_at": get_delivered_at(_ei)
                    }
                ]
            },
            "expected_actions": [
                {
                    "tool": "search_products_vector",
                    "required_args": {"query": "여름 반팔티", "limit": 5}
                },
                {
                    "tool": "get_user_orders",
                    "required_args": {"user_id": _ei["user_id"]}
                },
                {
                    "tool": "check_exchange_eligibility",
                    "required_args": {"order_id": _ei["order_id"], "user_id": _ei["user_id"], "reason": "사이즈가 맞지 않아요"}
                },
                {
                    "tool": "open_address_search",
                    "required_args": {}
                },
                {
                    "tool": "register_exchange_request",
                    "required_args": {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "reason": "사이즈가 맞지 않아요",
                        "pickup_address": "서울 마포구 홍익로 20",
                        "confirmed": True
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": "exchange_request",
                "required_tool_calls": ["register_exchange_request"],
                "final_state_check": [
                    {"order_id": _ei["order_id"], "expected_status": "EXCHANGE_REQUESTED"}
                ]
            },
            "chain_length": 5,
            "intent_change_count": 2
        })
        print(f"    ✓ GBD_TASK_010 생성 (긴 대화→교환: {_ei['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_010 스킵: 교환 action 없음")

    # ── GBD_TASK_011 ─────────────────────────────────────────────────────────
    # 두 번 변심: 취소 → 환불 → 교환 (교환 action 필요)
    # 처음엔 취소, 그 다음엔 환불로 바꿨다가 최종적으로 교환으로 결정
    # 최종 목적지: 교환 신청 완료
    # ─────────────────────────────────────────────────────────────────────────
    if exchange_info:
        _ei = exchange_info
        tasks.append({
            "task_id": make_user_task_id("GBD_TASK_011", u_idx, total_users),
            "domain": "retail",
            "category": "intent_change",
            "difficulty": "hard",
            "instruction": "주문 취소할게요.",
            "user_goal": (
                f"처음에 취소를 요청했으나 '이미 배송 완료라 취소 불가'를 듣고 환불로 변경, "
                f"이후 '사실 같은 상품 다른 사이즈가 필요해서 교환하고 싶어요'로 최종 변경 → "
                f"{_ei['order_id']} {_ei['item_name']}"
                f"을 사이즈 불만족 사유로 교환 신청하고 수거지(서울 서초구 반포대로 45)를 등록하여 최종 완료한다."
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
                "orders": [
                    {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "status": _ei["status"],
                        "total_amount": _ei["amount"],
                        "product_name": _ei["item_name"],
                        "can_cancel": False,
                        "can_return": True,
                        "can_exchange": True,
                        "delivered_at": get_delivered_at(_ei)
                    }
                ]
            },
            "expected_actions": [
                {
                    "tool": "get_user_orders",
                    "required_args": {"user_id": _ei["user_id"], "requires_selection": True, "action_context": "exchange"}
                },
                {
                    "tool": "check_exchange_eligibility",
                    "required_args": {"order_id": _ei["order_id"], "user_id": _ei["user_id"], "reason": "사이즈가 맞지 않아요"}
                },
                {
                    "tool": "open_address_search",
                    "required_args": {}
                },
                {
                    "tool": "register_exchange_request",
                    "required_args": {
                        "order_id": _ei["order_id"],
                        "user_id": _ei["user_id"],
                        "reason": "사이즈가 맞지 않아요",
                        "pickup_address": "서울 서초구 반포대로 45",
                        "confirmed": True
                    }
                },
            ],
            "success_criteria": {
                "type": "final_destination",
                "final_goal": "exchange_request",
                "required_tool_calls": ["check_exchange_eligibility", "register_exchange_request"],
                "excluded_tool_calls": ["cancel_order", "register_return_request"],
                "final_state_check": [
                    {"order_id": _ei["order_id"], "expected_status": "EXCHANGE_REQUESTED"}
                ]
            },
            "chain_length": 4,
            "intent_change_count": 2
        })
        print(f"    ✓ GBD_TASK_011 생성 (다중 변심→교환: {_ei['order_id']})")
    else:
        print(f"    ⚠ GBD_TASK_011 스킵: 교환 action 없음")

# ─── JSONL 저장 ───────────────────────────────────────────────────────────────
print(f"\n[3] JSONL 저장 → {OUTPUT_PATH}")
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
if OUTPUT_PATH.exists():
    OUTPUT_PATH.unlink()
    print(f"  • 기존 데이터 초기화 완료: {OUTPUT_PATH.name}")
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
print(f"  - 사용자 수: {total_users}명")
print(f"  - 변심 포함 태스크: {intent_change_tasks}개 | 긴 대화(변심 없음): {long_conv_tasks}개")
print(f"  - 다중 변심(2회 이상): {multi_change_tasks}개")
print(f"  - 난이도 분포: {', '.join(f'{k} {v}개' for k, v in sorted(difficulty_dist.items()))}")
print(f"  - 체인 길이 분포: {', '.join(f'{k}-chain {v}개' for k, v in sorted(chain_dist.items()))}")
print(f"\n  사용된 데이터 (사용자별):")
for u_idx, u_row in enumerate(user_rows):
    print(f"  ── 사용자 {u_idx + 1}: {u_row['user_email']} (user_id={u_row['user_id']}) ──")
    for action_type in ["교환", "주문취소", "환불"]:
        info = u_row["actions"].get(action_type, {}).get("order_info")
        if info:
            print(f"    - {action_type}: {info['order_id']} ({info['item_name']})")
        else:
            print(f"    - {action_type}: 없음")
print("\n[실행 방법]")
print("  전체 실행  : python run.py --tasks_file data/task_completion_rate_tasks.jsonl")
print("  일부 실행  : python run.py --tasks_file data/task_completion_rate_tasks.jsonl --task_ids GBD_TASK_001 GBD_TASK_011")
print("  디버그 모드: python run.py --tasks_file data/task_completion_rate_tasks.jsonl --debug")
