from django.conf import settings
from django.db import models
from django.utils import timezone


class SessionToken(models.Model):
    """사용자 세션 토큰(로그인 세션)"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="session_tokens",
    )
    token = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self) -> bool:
        return self.is_active and self.expires_at > timezone.now()

    def mark_inactive(self) -> None:
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])

    @property
    def remaining_seconds(self) -> int:
        delta = self.expires_at - timezone.now()
        return max(int(delta.total_seconds()), 0)
