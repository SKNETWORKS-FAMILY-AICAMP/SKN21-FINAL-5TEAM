from datetime import timedelta
import json
import os
import uuid

from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .models import SessionToken

SESSION_TOKEN_COOKIE_NAME = "session_token"
SESSION_TOKEN_EXPIRE_DAYS = 7
COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax")


def _get_request_data(request):
    try:
        return json.loads(request.body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _find_active_session(request):
    token_value = request.COOKIES.get(SESSION_TOKEN_COOKIE_NAME)
    if not token_value:
        return None

    try:
        session = SessionToken.objects.get(token=token_value, is_active=True)
    except SessionToken.DoesNotExist:
        return None

    if session.expires_at <= timezone.now():
        session.mark_inactive()
        return None

    return session


def _build_user_payload(user):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "name": user.get_full_name() or user.username,
    }


def _set_session_cookie(response, token_value, expires_at):
    max_age = int((expires_at - timezone.now()).total_seconds())
    response.set_cookie(
        SESSION_TOKEN_COOKIE_NAME,
        token_value,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=max_age,
        path="/",
    )


def _options_response():
    response = HttpResponse(status=204)
    response["Allow"] = "POST, OPTIONS"
    return response


@csrf_exempt
def login(request):
    if request.method == "OPTIONS":
        return _options_response()

    if request.method != "POST":
        return HttpResponse(status=405)
    data = _get_request_data(request)
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not email or not password:
        return JsonResponse({"detail": "이메일과 비밀번호를 모두 입력해주세요."}, status=400)

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return JsonResponse({"detail": "이메일 또는 비밀번호가 틀렸습니다."}, status=401)

    user = authenticate(request, username=user.username, password=password)
    if not user:
        return JsonResponse({"detail": "이메일 또는 비밀번호가 틀렸습니다."}, status=401)

    expires_at = timezone.now() + timedelta(days=SESSION_TOKEN_EXPIRE_DAYS)
    SessionToken.objects.filter(user=user, is_active=True).update(is_active=False)
    token_value = uuid.uuid4().hex
    session = SessionToken.objects.create(user=user, token=token_value, expires_at=expires_at)

    payload = {
        "ok": True,
        "user": _build_user_payload(user),
    }

    response = JsonResponse(payload)
    _set_session_cookie(response, session.token, expires_at)
    return response


@csrf_exempt
def logout(request):
    if request.method == "OPTIONS":
        return _options_response()

    if request.method != "POST":
        return HttpResponse(status=405)
    session = _find_active_session(request)
    if session:
        session.mark_inactive()

    response = JsonResponse({"ok": True})
    response.delete_cookie(
        SESSION_TOKEN_COOKIE_NAME,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )
    return response


@require_GET
def me(request):
    session = _find_active_session(request)
    if not session:
        return JsonResponse({"authenticated": False})

    return JsonResponse(
        {
            "authenticated": True,
            "user": _build_user_payload(session.user),
        }
    )
