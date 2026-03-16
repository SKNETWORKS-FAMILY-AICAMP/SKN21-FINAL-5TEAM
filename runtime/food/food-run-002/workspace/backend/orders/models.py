from django.conf import settings
from django.db import models


class Order(models.Model):
    class Status(models.TextChoices):
        PREPARING = "preparing", "상품 준비 중"
        SHIPPING = "shipping", "배송 중"
        DELIVERED = "delivered", "배송 완료"
        CANCELLED = "cancelled", "주문 취소"
        REFUNDED = "refunded", "환불 완료"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "결제 대기"
        PAID = "paid", "결제 완료"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True
    )
    product = models.ForeignKey(
        "products.Product", on_delete=models.PROTECT, related_name="orders"
    )
    quantity = models.PositiveIntegerField(default=1)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PREPARING
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders_order"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} - {self.product} [{self.status}]"
