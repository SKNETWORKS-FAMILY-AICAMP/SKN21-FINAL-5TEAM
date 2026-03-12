from flask import Blueprint, request, jsonify, session
from functools import wraps

from models.order import get_orders_by_user

order_bp = Blueprint("order", __name__)


def login_required(f):
    """세션 인증 데코레이터"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "로그인이 필요합니다."}), 401

        request.user_id = session["user_id"]
        return f(*args, **kwargs)
    return decorated


@order_bp.route("", methods=["GET"])
@login_required
def list_orders():
    """내 주문 목록 조회 API"""
    orders = get_orders_by_user(request.user_id)
    return jsonify({"orders": orders}), 200
