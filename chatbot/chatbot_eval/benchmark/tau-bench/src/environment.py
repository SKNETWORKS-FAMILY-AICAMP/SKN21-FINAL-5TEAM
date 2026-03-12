"""
environment.py

tau-bench 태스크 환경 관리 모듈.
각 태스크의 DB 초기 상태를 설정하고, 도구 호출에 따른 상태 전이를 시뮬레이션합니다.
"""

import json
import copy
from typing import Any


class TaskEnvironment:
    """
    이커머스 태스크 환경.
    태스크 초기 상태를 로드하고, 도구 호출 결과를 시뮬레이션하며 최종 상태를 검증합니다.
    """

    def __init__(self, task: dict):
        self.task_id: str = task["task_id"]
        self.category: str = task["category"]
        self.success_criteria: dict = task["success_criteria"]
        self.db_state: dict = copy.deepcopy(task.get("initial_db_state", {}))
        self.called_tools: list[str] = []
        self.tool_call_log: list[dict] = []

    def reset(self, task: dict) -> None:
        """환경을 태스크 초기 상태로 리셋합니다."""
        self.db_state = copy.deepcopy(task.get("initial_db_state", {}))
        self.called_tools = []
        self.tool_call_log = []

    def apply_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict:
        """
        도구 호출을 환경에 적용하고 시뮬레이션된 결과를 반환합니다.

        Parameters:
            tool_name: 호출할 도구 이름
            arguments: 도구 인자 딕셔너리

        Returns:
            시뮬레이션된 도구 실행 결과
        """
        self.called_tools.append(tool_name)
        self.tool_call_log.append({"tool": tool_name, "arguments": arguments})

        result = self._simulate_tool(tool_name, arguments)
        self._update_db_state(tool_name, arguments, result)
        return result

    def _simulate_tool(self, tool_name: str, args: dict) -> dict:
        """도구별 시뮬레이션 결과를 반환합니다."""
        order_id = args.get("order_id", "")
        user_id = args.get("user_id", 1)

        if tool_name == "cancel_order":
            return {
                "status": "success",
                "message": f"주문({order_id})이 취소되었습니다. 환불은 영업일 기준 3~5일 내 처리됩니다."
            }

        if tool_name == "get_user_orders":
            orders = self.db_state.get("orders", [])
            return {"orders": orders, "message": "최근 주문 목록입니다."}

        if tool_name == "get_order_details":
            orders = self.db_state.get("orders", [])
            order = next((o for o in orders if o.get("order_id") == order_id), {})
            return order if order else {"error": f"주문({order_id})을 찾을 수 없습니다."}

        if tool_name == "check_refund_eligibility":
            return {
                "eligible": True,
                "final_refund_amount": 49000,
                "message": "환불 가능합니다. 배송 완료 후 7일 이내이며 상품 상태 양호."
            }

        if tool_name == "register_return_request":
            return {
                "status": "success",
                "message": f"반품 접수가 완료되었습니다. 수거 예정일: 2026-03-08",
                "pickup_address": args.get("pickup_address", "")
            }

        if tool_name == "check_exchange_eligibility":
            return {
                "eligible": True,
                "type": "post_shipment",
                "exchange_fee": 6000,
                "message": "교환 가능합니다. 왕복 배송비 6,000원이 발생합니다."
            }

        if tool_name == "register_exchange_request":
            return {
                "status": "success",
                "message": f"교환 접수가 완료되었습니다. 수거 예정일: 2026-03-09"
            }

        if tool_name == "search_products_vector":
            return {
                "message": "검색 결과입니다.",
                "ui_action": "show_product_list",
                "ui_data": [
                    {"id": 15001, "name": "Puma Men Blue Casual T-shirt", "price": 30000},
                    {"id": 15002, "name": "Nike Men Sky Blue Sports Tee", "price": 35000},
                    {"id": 15003, "name": "Adidas Men Light Blue Short Sleeve", "price": 32000}
                ],
                "requires_selection": False
            }

        if tool_name == "recommend_clothes":
            return {
                "success": True,
                "message": "조건에 맞는 옷 3개를 추천해드릴게요!",
                "ui_action": "show_product_list",
                "ui_data": [
                    {"id": 22001, "name": "Levis Men Black Slim Fit Jeans", "price": 59000},
                    {"id": 22002, "name": "Roadster Men Black Regular Trousers", "price": 45000},
                    {"id": 22003, "name": "Tokyo Talkies Women Black Joggers", "price": 39000}
                ]
            }

        if tool_name == "generate_review_draft":
            return {
                "success": True,
                "drafts": {
                    "short": "착용감과 색감이 마음에 쏙 드는 후드집업!",
                    "emotional": "오랜만에 산 옷인데 착용감이 정말 부드럽고, 색감이 사진보다 훨씬 예뻐서 기분이 너무 좋아요.",
                    "detailed": "착용감 좋음. 색감 사진과 동일. 재구매 의사 있음."
                },
                "message": "리뷰 초안이 생성되었습니다."
            }

        if tool_name == "create_review":
            return {
                "success": True,
                "message": "리뷰가 성공적으로 등록되었습니다.",
                "review_id": 999
            }

        if tool_name == "register_used_sale":
            return {
                "success": True,
                "tracking_id": "USED-SIM0001",
                "message": f"'{args.get('item_name', '')}' 중고 판매가 접수되었습니다.",
                "next_steps": "수거 신청(request_pickup)을 진행해주세요."
            }

        if tool_name == "request_pickup":
            return {
                "success": True,
                "message": f"수거 신청 완료: {args.get('pickup_date', '')}에 '{args.get('pickup_address', '')}'으로 방문 예정입니다.",
                "status": "수거 대기중"
            }

        if tool_name == "register_gift_card":
            return {
                "success": True,
                "message": "상품권이 성공적으로 등록되었습니다.",
                "balance": 30000,
                "expires_at": "2026-12-31"
            }

        if tool_name == "get_shipping_details":
            return {
                "order_id": order_id,
                "carrier": "CJ대한통운",
                "tracking_number": "1234567890123",
                "status": "출고완료",
                "estimated_delivery": "2026-03-06",
                "last_update": "2026-03-04 08:00:00"
            }

        if tool_name == "open_address_search":
            return {"ui_action": "show_address_search", "message": "주소 검색 버튼을 눌러주세요."}

        return {"status": "unknown_tool", "tool": tool_name}

    def _update_db_state(self, tool_name: str, args: dict, result: dict) -> None:
        """도구 호출 결과에 따라 DB 상태를 업데이트합니다."""
        order_id = args.get("order_id", "")
        orders = self.db_state.get("orders", [])

        if tool_name == "cancel_order":
            for order in orders:
                if order.get("order_id") == order_id:
                    order["status"] = "CANCELLED"

        elif tool_name == "register_return_request" and result.get("status") == "success":
            for order in orders:
                if order.get("order_id") == order_id:
                    order["status"] = "RETURN_REQUESTED"

        elif tool_name == "register_exchange_request" and result.get("status") == "success":
            for order in orders:
                if order.get("order_id") == order_id:
                    order["status"] = "EXCHANGE_REQUESTED"

        elif tool_name == "create_review" and result.get("success"):
            for order in orders:
                if order.get("order_id") == order_id:
                    order["review_created"] = True

        elif tool_name == "register_used_sale" and result.get("success"):
            self.db_state["used_sale_created"] = True
            self.db_state["used_sale_tracking_id"] = result.get("tracking_id", "")

        elif tool_name == "request_pickup" and result.get("success"):
            self.db_state["pickup_scheduled"] = True

        elif tool_name == "register_gift_card" and result.get("success"):
            gift_cards = self.db_state.setdefault("gift_cards", [])
            gift_cards.append({
                "code": args.get("code", ""),
                "balance": result.get("balance", 0),
                "expires_at": result.get("expires_at", "")
            })
            self.db_state["gift_card_registered"] = True

    def get_state_summary(self) -> dict:
        """현재 환경 상태 요약을 반환합니다."""
        return {
            "task_id": self.task_id,
            "called_tools": self.called_tools,
            "db_state": self.db_state,
            "tool_call_count": len(self.called_tools)
        }
