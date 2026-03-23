from flask import Blueprint, jsonify

from models.order import get_all_orders, get_order_detail, cancel_order, exchange_order, refund_order

order_bp = Blueprint("order", __name__)


@order_bp.route("/all", methods=["GET"])
def list_all_orders():
    """전체 주문 목록 조회 API"""
    orders = get_all_orders()
    return jsonify({"orders": orders}), 200


@order_bp.route("/<int:order_id>", methods=["GET"])
def get_order(order_id):
    """단건 주문 상세 조회 API"""
    order = get_order_detail(order_id)
    if not order:
        return jsonify({"error": "주문을 찾을 수 없습니다."}), 404
    return jsonify({"order": order}), 200


@order_bp.route("/<int:order_id>/cancel", methods=["POST"])
def cancel(order_id):
    """주문 취소 API (주문상태 변경 + 결제취소 + 재고 복구)"""
    result = cancel_order(order_id)
    if "error" in result:
        return jsonify({"error": result["error"]}), result["code"]
    return jsonify(result), 200


@order_bp.route("/<int:order_id>/exchange", methods=["POST"])
def exchange(order_id):
    """교환 접수 API"""
    result = exchange_order(order_id)
    if "error" in result:
        return jsonify({"error": result["error"]}), result["code"]
    return jsonify(result), 200


@order_bp.route("/<int:order_id>/refund", methods=["POST"])
def refund(order_id):
    """환불 처리 API (주문상태 변경 + 결제환불 + 재고 복구)"""
    result = refund_order(order_id)
    if "error" in result:
        return jsonify({"error": result["error"]}), result["code"]
    return jsonify(result), 200
