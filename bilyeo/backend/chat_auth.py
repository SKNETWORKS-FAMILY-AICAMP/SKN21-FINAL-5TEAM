from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from models.user import find_user_by_id

chat_auth_bp = Blueprint("chat_auth", __name__)
_SITE_ID = "site-b"


def _parse_bearer_token(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = raw.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def resolve_authenticated_user_id() -> int | None:
    bearer_token = _parse_bearer_token(request.headers.get("Authorization"))
    if bearer_token.isdigit():
        return int(bearer_token)

    session_user_id = session.get("user_id")
    if session_user_id is None:
        return None
    try:
        return int(session_user_id)
    except (TypeError, ValueError):
        return None


def get_authenticated_user() -> dict | None:
    user_id = resolve_authenticated_user_id()
    if user_id is None:
        return None
    return find_user_by_id(user_id)


def _unauthenticated_payload() -> dict:
    return {
        "authenticated": False,
        "site_id": _SITE_ID,
        "access_token": "",
        "user_id": "",
        "user": None,
        "error": "login required",
    }


@chat_auth_bp.route("/chat/auth-token", methods=["POST"])
def chat_auth_token():
    user = get_authenticated_user()
    if user is None:
        return jsonify(_unauthenticated_payload()), 401

    user_id = str(user["user_id"])
    payload = {
        "authenticated": True,
        "site_id": _SITE_ID,
        "access_token": user_id,
        "user_id": user_id,
        "user": {
            "id": user_id,
            "email": user.get("email", ""),
            "name": user.get("name", ""),
        },
    }
    return jsonify(payload), 200
