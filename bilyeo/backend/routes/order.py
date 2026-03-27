from flask import Blueprint, jsonify

from chat_auth import get_authenticated_user
from models.order import (
    cancel_order,
    exchange_order,
    get_all_orders,
    get_order_detail,
    get_orders_by_user,
    refund_order,
)

order_bp = Blueprint("order", __name__)


@order_bp.route("", methods=["GET"])
@order_bp.route("/", methods=["GET"])
def list_my_orders():
    """로그인한 사용자의 주문 목록 조회 API"""
    user = get_authenticated_user()
    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    orders = get_orders_by_user(int(user["user_id"]))
    return jsonify({"orders": orders}), 200


@order_bp.route("/all", methods=["GET"])
def list_all_orders():
    """전체 주문 목록 조회 API"""
    orders = get_all_orders()
    return jsonify({"orders": orders}), 200


@order_bp.route("/<int:order_id>", methods=["GET"])
def get_order(order_id):
    """단일 주문 상세 조회 API"""
    user = get_authenticated_user()
    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    order = get_order_detail(order_id)
    if not order:
        return jsonify({"error": "주문을 찾을 수 없습니다."}), 404
    if str(order.get("user_id", "")) not in {"", str(user["user_id"])}:
        return jsonify({"error": "해당 주문에 접근할 수 없습니다."}), 403
    return jsonify({"order": order}), 200


@order_bp.route("/<int:order_id>/cancel", methods=["POST"])
def cancel(order_id):
    """주문 취소 API"""
    user = get_authenticated_user()
    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    result = cancel_order(order_id)
    if "error" in result:
        return jsonify({"error": result["error"]}), result["code"]
    return jsonify(result), 200


@order_bp.route("/<int:order_id>/exchange", methods=["POST"])
def exchange(order_id):
    """교환 접수 API"""
    user = get_authenticated_user()
    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    result = exchange_order(order_id)
    if "error" in result:
        return jsonify({"error": result["error"]}), result["code"]
    return jsonify(result), 200


@order_bp.route("/<int:order_id>/refund", methods=["POST"])
def refund(order_id):
    """환불 처리 API"""
    user = get_authenticated_user()
    if user is None:
        return jsonify({"error": "로그인이 필요합니다."}), 401
    result = refund_order(order_id)
    if "error" in result:
        return jsonify({"error": result["error"]}), result["code"]
    return jsonify(result), 200
