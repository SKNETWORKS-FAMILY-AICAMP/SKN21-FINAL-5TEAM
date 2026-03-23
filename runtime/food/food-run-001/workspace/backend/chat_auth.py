from django.http import JsonResponse
from django.views.decorators.http import require_POST

from chatbot.src.auth.chat_token import issue_chat_token
from users.models import SessionToken


@require_POST
def chat_auth_token(request):
    session_token = request.COOKIES.get("session_token")
    if not session_token:
        return JsonResponse({"authenticated": False, "detail": "login required"}, status=401)

    session = (
        SessionToken.objects.select_related("user")
        .filter(token=session_token, is_active=True)
        .first()
    )
    if not session:
        return JsonResponse({"authenticated": False, "detail": "invalid session"}, status=401)

    user = session.user
    token = issue_chat_token(
        user_id=str(user.id),
        site_id="site-a",
        secret="CHANGE_ME",
        name=user.get_full_name() or user.username,
        email=user.email,
        scopes=["chat"],
        expires_in_seconds=600,
    )
    return JsonResponse(
        {
            "authenticated": True,
            "site_id": "site-a",
            "access_token": token,
        }
    )
