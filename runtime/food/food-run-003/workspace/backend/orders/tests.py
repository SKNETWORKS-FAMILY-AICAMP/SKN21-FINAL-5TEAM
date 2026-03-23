import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from products.models import Product
from users.models import SessionToken

from .models import Order


class OrderApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="food-user",
            email="food@example.com",
            password="password1234",
        )
        self.other_user = User.objects.create_user(
            username="other-user",
            email="other@example.com",
            password="password1234",
        )
        self.product = Product.objects.create(
            name="김치볶음밥",
            price="12000.00",
            image="https://example.com/image.jpg",
            stock=10,
        )
        self.my_order = Order.objects.create(
            user=self.user,
            product=self.product,
            quantity=1,
            total_price="12000.00",
            status=Order.Status.DELIVERED,
            payment_status=Order.PaymentStatus.PAID,
        )
        self.cancel_order = Order.objects.create(
            user=self.user,
            product=self.product,
            quantity=1,
            total_price="12000.00",
            status=Order.Status.PREPARING,
            payment_status=Order.PaymentStatus.PAID,
        )
        self.shipping_order = Order.objects.create(
            user=self.user,
            product=self.product,
            quantity=1,
            total_price="12000.00",
            status=Order.Status.SHIPPING,
            payment_status=Order.PaymentStatus.PAID,
        )
        self.other_order = Order.objects.create(
            user=self.other_user,
            product=self.product,
            quantity=2,
            total_price="24000.00",
            status=Order.Status.PREPARING,
            payment_status=Order.PaymentStatus.PAID,
        )

        session = SessionToken.objects.create(
            user=self.user,
            token="session-token-for-tests",
            expires_at=timezone.now() + timedelta(days=1),
        )
        self.client.cookies["session_token"] = session.token

    def test_order_list_requires_authentication(self):
        unauthenticated_client = Client()

        response = unauthenticated_client.get("/api/orders/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "로그인이 필요합니다.")

    def test_order_list_returns_only_authenticated_users_orders(self):
        response = self.client.get("/api/orders/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(len(payload), 3)
        returned_ids = {item["id"] for item in payload}
        self.assertEqual(
            returned_ids,
            {self.my_order.id, self.cancel_order.id, self.shipping_order.id},
        )
        self.assertTrue(all(item["user_id"] == self.user.id for item in payload))
        delivered_order = next(item for item in payload if item["id"] == self.my_order.id)
        self.assertTrue(delivered_order["available_actions"]["can_exchange"])

    def test_exchange_action_updates_order_status(self):
        response = self.client.post(
            f"/api/orders/{self.my_order.id}/actions/",
            data=json.dumps({"action": "exchange", "reason": "상품 교환"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.my_order.refresh_from_db()
        self.assertEqual(self.my_order.status, Order.Status.EXCHANGE_REQUESTED)
        self.assertEqual(response.json()["order"]["status"], Order.Status.EXCHANGE_REQUESTED)

    def test_cancel_action_updates_order_status(self):
        response = self.client.post(
            f"/api/orders/{self.cancel_order.id}/actions/",
            data=json.dumps({"action": "cancel", "reason": "단순 변심"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.cancel_order.refresh_from_db()
        self.assertEqual(self.cancel_order.status, Order.Status.CANCELLED)
        self.assertEqual(
            self.cancel_order.payment_status,
            Order.PaymentStatus.PENDING,
        )

    def test_refund_action_updates_order_status(self):
        response = self.client.post(
            f"/api/orders/{self.shipping_order.id}/actions/",
            data=json.dumps({"action": "refund", "reason": "환불 요청"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.shipping_order.refresh_from_db()
        self.assertEqual(self.shipping_order.status, Order.Status.REFUNDED)
        self.assertEqual(
            self.shipping_order.payment_status,
            Order.PaymentStatus.PENDING,
        )

    def test_order_detail_returns_available_actions_for_owner(self):
        response = self.client.get(f"/api/orders/{self.cancel_order.id}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], self.cancel_order.id)
        self.assertTrue("available_actions" in payload)
        self.assertTrue(payload["available_actions"]["can_lookup"])

    def test_order_detail_cannot_access_another_users_order(self):
        response = self.client.get(f"/api/orders/{self.other_order.id}/")

        self.assertEqual(response.status_code, 404)
