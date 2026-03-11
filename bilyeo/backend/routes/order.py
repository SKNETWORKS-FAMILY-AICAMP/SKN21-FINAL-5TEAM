from flask import Blueprint, request, jsonify
from functools import wraps
import jwt

from config import SECRET_KEY
from models.order import get_orders_by_user

order_bp = Blueprint("order", __name__)


def login_required(f):
    """JWT 토큰 인증 데코레이터"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization")
        if not token:
            return jsonify({"error": "로그인이 필요합니다."}), 401

        # "Bearer <token>" 형식에서 토큰 추출
        if token.startswith("Bearer "):
            token = token[7:]

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            request.user_id = payload["user_id"]
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "토큰이 만료되었습니다."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "유효하지 않은 토큰입니다."}), 401

        return f(*args, **kwargs)
    return decorated


@order_bp.route("", methods=["GET"])
@login_required
def list_orders():
    """내 주문 목록 조회 API"""
    orders = get_orders_by_user(request.user_id)
    return jsonify({"orders": orders}), 200
