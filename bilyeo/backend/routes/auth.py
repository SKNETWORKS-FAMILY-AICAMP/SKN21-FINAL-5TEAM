from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash

from models.user import find_user_by_email

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["POST"])
def login():
    """로그인 API"""
    data = request.get_json()

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "이메일과 비밀번호를 입력해주세요."}), 400

    user = find_user_by_email(email)
    if not user:
        return jsonify({"error": "등록되지 않은 이메일입니다."}), 401

    if not check_password_hash(user["password"], password):
        return jsonify({"error": "비밀번호가 일치하지 않습니다."}), 401

    # 세션에 사용자 정보 저장
    session["user_id"] = user["user_id"]
    session["email"] = user["email"]
    session["name"] = user["name"]

    return jsonify({
        "message": "로그인 성공",
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "name": user["name"]
        }
    }), 200


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """로그아웃 API"""
    session.clear()
    return jsonify({"message": "로그아웃 성공"}), 200
