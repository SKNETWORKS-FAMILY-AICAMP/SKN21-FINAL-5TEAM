"""
evaluator.py

tau-bench 태스크 성공 평가 모듈.
최종 DB 상태와 호출된 도구 목록을 기반으로 태스크 성공 여부를 판단합니다.
"""

import json
from .environment import TaskEnvironment
from .user_simulator import TASK_DONE_TOKEN, TASK_FAILED_TOKEN


class TaskEvaluator:
    """
    태스크 성공 여부를 평가합니다.

    평가 기준 (success_criteria.type):
    - "tool_call"            : 필수 도구가 모두 호출되었는지 확인
    - "tool_call_and_state"  : 도구 호출 + DB 최종 상태 확인
    """

    def evaluate(
        self,
        task: dict,
        env: TaskEnvironment,
        user_done: bool,
        user_failed: bool,
        trajectory: list[dict],
    ) -> dict:
        """
        태스크 성공 여부를 평가합니다.

        Parameters:
            task: 태스크 정의 딕셔너리
            env: 실행 완료된 태스크 환경
            user_done: 유저 시뮬레이터가 TASK_DONE을 발화했는지
            user_failed: 유저 시뮬레이터가 TASK_FAILED를 발화했는지
            trajectory: 전체 대화 이력

        Returns:
            평가 결과 딕셔너리
        """
        criteria = task.get("success_criteria", {})
        criteria_type = criteria.get("type", "tool_call")
        required_tools = criteria.get("required_tool_calls", [])
        excluded_tools = criteria.get("excluded_tool_calls", [])
        final_state_check = criteria.get("final_state_check", {})

        # 호출된 도구 목록
        called_tools = env.called_tools

        # 1. 필수 도구 호출 여부 확인
        tool_call_pass = all(tool in called_tools for tool in required_tools)
        missing_tools = [t for t in required_tools if t not in called_tools]

        # 1-1. 금지 도구 호출 여부 확인
        excluded_tool_pass = not any(tool in called_tools for tool in excluded_tools)
        violated_excluded_tools = [t for t in excluded_tools if t in called_tools]

        # 2. DB 최종 상태 확인 (type이 tool_call_and_state인 경우)
        state_pass = True
        state_details = {}
        if criteria_type == "tool_call_and_state" and final_state_check:
            state_pass, state_details = self._check_final_state(env, final_state_check)

        # 3. 사용자 완료 신호 확인
        user_signal_pass = user_done and not user_failed

        # 종합 판정
        is_success = tool_call_pass and state_pass and excluded_tool_pass and not user_failed

        return {
            "task_id": task["task_id"],
            "success": is_success,
            "tool_call_pass": tool_call_pass,
            "excluded_tool_pass": excluded_tool_pass,
            "state_pass": state_pass,
            "user_done": user_done,
            "user_failed": user_failed,
            "called_tools": called_tools,
            "required_tools": required_tools,
            "missing_tools": missing_tools,
            "excluded_tools": excluded_tools,
            "violated_excluded_tools": violated_excluded_tools,
            "state_details": state_details,
            "turn_count": len([m for m in trajectory if m.get("role") == "user"]),
            "trajectory_length": len(trajectory),
        }

    def _check_final_state(
        self, env: TaskEnvironment, state_check: dict
    ) -> tuple[bool, dict]:
        """DB 최종 상태가 기대 조건을 만족하는지 확인합니다."""
        db = env.db_state
        orders = db.get("orders", [])
        details = {}

        order_id = state_check.get("order_id")
        if order_id:
            order = next((o for o in orders if o.get("order_id") == order_id), None)
            if order is None:
                return False, {"error": f"주문 {order_id}을 찾을 수 없습니다."}

            expected_status = state_check.get("expected_status")
            if expected_status:
                actual = order.get("status", "")
                details["order_status"] = {"expected": expected_status, "actual": actual}
                if actual != expected_status:
                    return False, details

            if state_check.get("review_created"):
                review_created = order.get("review_created", False)
                details["review_created"] = review_created
                if not review_created:
                    return False, details

        if state_check.get("used_sale_created"):
            created = db.get("used_sale_created", False)
            details["used_sale_created"] = created
            if not created:
                return False, details

        if state_check.get("gift_card_registered"):
            registered = db.get("gift_card_registered", False)
            details["gift_card_registered"] = registered
            if not registered:
                return False, details

        return True, details


def format_eval_result(result: dict) -> str:
    """평가 결과를 사람이 읽기 쉬운 문자열로 포맷합니다."""
    status = "✅ 성공" if result["success"] else "❌ 실패"
    lines = [
        f"[{result['task_id']}] {status}",
        f"  - 도구 호출 성공: {result['tool_call_pass']} | 상태 검증: {result['state_pass']}",
        f"  - 유저 완료 신호: {result['user_done']} | 실패 신호: {result['user_failed']}",
        f"  - 호출된 도구: {result['called_tools']}",
        f"  - 대화 턴 수: {result['turn_count']}",
    ]
    if result["missing_tools"]:
        lines.append(f"  - 누락 도구: {result['missing_tools']}")
    if result["state_details"]:
        lines.append(f"  - 상태 상세: {result['state_details']}")
    return "\n".join(lines)
