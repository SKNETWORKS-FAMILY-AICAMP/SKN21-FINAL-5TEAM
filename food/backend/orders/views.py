from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Order
from products.image_utils import build_product_image_url
from users.models import SessionToken


def add_cors_headers(response):
    return response


def get_authenticated_user(request):
    token_value = request.COOKIES.get("session_token")
    if not token_value:
        return None

    try:
        session = SessionToken.objects.select_related("user").get(
            token=token_value,
            is_active=True,
        )
    except SessionToken.DoesNotExist:
        return None

    if session.expires_at <= timezone.now():
        session.mark_inactive()
        return None

    return session.user


def require_authenticated_user(request):
    user = get_authenticated_user(request)
    if user is None:
        return None, add_cors_headers(
            Response(
                {"detail": "로그인이 필요합니다."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        )
    return user, None


def get_available_actions(order):
    is_paid = order.payment_status == Order.PaymentStatus.PAID
    status_value = order.status
    return {
        "can_pay": (
            order.payment_status == Order.PaymentStatus.PENDING
            and status_value not in (Order.Status.CANCELLED, Order.Status.REFUNDED)
        ),
        "can_cancel": (
            status_value == Order.Status.PREPARING
            and status_value not in (Order.Status.CANCELLED, Order.Status.REFUNDED)
        ),
        "can_refund": (
            is_paid and status_value in (Order.Status.SHIPPING, Order.Status.DELIVERED)
        ),
        "can_exchange": (
            is_paid and status_value in (Order.Status.SHIPPING, Order.Status.DELIVERED)
        ),
        "can_lookup": True,
    }


def serialize_order(order, request):
    product = order.product
    return {
        "id": order.id,
        "user_id": order.user_id,
        "quantity": order.quantity,
        "total_price": order.total_price,
        "status": order.status,
        "payment_status": order.payment_status,
        "created_at": order.created_at,
        "available_actions": get_available_actions(order),
        "product": {
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "image_url": build_product_image_url(request, product.image),
        },
    }


@api_view(["GET"])
def order_list(request):
    user, error_response = require_authenticated_user(request)
    if error_response:
        return error_response

    orders = (
        Order.objects.select_related("product")
        .filter(user=user)
        .order_by("-created_at")
    )
    payload = [serialize_order(order, request) for order in orders]
    return add_cors_headers(Response(payload))


@api_view(["GET"])
def order_detail(request, order_id):
    user, error_response = require_authenticated_user(request)
    if error_response:
        return error_response

    order = get_object_or_404(
        Order.objects.select_related("product"),
        pk=order_id,
        user=user,
    )
    return add_cors_headers(Response(serialize_order(order, request)))


@api_view(["POST"])
def order_action(request, order_id):
    user, error_response = require_authenticated_user(request)
    if error_response:
        return error_response

    order = get_object_or_404(
        Order.objects.select_related("product"),
        pk=order_id,
        user=user,
    )
    action = (request.data.get("action") or "").strip().lower()
    if not action:
        return add_cors_headers(
            Response(
                {"detail": "action 값을 보내주세요."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )

    if action == "pay":
        return _handle_payment(order, request)
    if action == "cancel":
        return _handle_cancel(order, request)
    if action == "refund":
        return _handle_refund(order, request)
    if action == "exchange":
        return _handle_exchange(order, request)
    if action == "status":
        return _handle_status(order, request)

    return add_cors_headers(
        Response(
            {"detail": f"지원하지 않는 action: {action}"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    )


def _handle_payment(order, request):
    if order.payment_status == Order.PaymentStatus.PAID:
        return add_cors_headers(
            Response(
                {"detail": "이미 결제된 주문입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status in (Order.Status.CANCELLED, Order.Status.REFUNDED):
        return add_cors_headers(
            Response(
                {"detail": "취소 또는 환불된 주문은 결제할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )

    order.payment_status = Order.PaymentStatus.PAID
    order.status = Order.Status.PREPARING
    order.save(update_fields=["payment_status", "status"])

    return add_cors_headers(
        Response(
            {
                "message": "결제가 완료되었습니다.",
                "order": serialize_order(order, request),
            }
        )
    )


def _handle_cancel(order, request):
    if order.status in (
        Order.Status.CANCELLED,
        Order.Status.REFUNDED,
        Order.Status.EXCHANGE_REQUESTED,
    ):
        return add_cors_headers(
            Response(
                {"detail": "이미 취소/환불되었거나 교환 접수된 주문입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status in (Order.Status.SHIPPING, Order.Status.DELIVERED):
        return add_cors_headers(
            Response(
                {"detail": "배송이 시작된 주문은 취소할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )

    order.status = Order.Status.CANCELLED
    order.payment_status = Order.PaymentStatus.PENDING
    order.save(update_fields=["status", "payment_status"])

    return add_cors_headers(
        Response(
            {
                "message": "주문이 취소되었습니다.",
                "order": serialize_order(order, request),
            }
        )
    )


def _handle_refund(order, request):
    if order.payment_status != Order.PaymentStatus.PAID:
        return add_cors_headers(
            Response(
                {"detail": "결제된 주문만 환불할 수 있습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status == Order.Status.REFUNDED:
        return add_cors_headers(
            Response(
                {"detail": "이미 환불된 주문입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status == Order.Status.EXCHANGE_REQUESTED:
        return add_cors_headers(
            Response(
                {"detail": "교환 접수된 주문은 환불할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status not in (Order.Status.SHIPPING, Order.Status.DELIVERED):
        return add_cors_headers(
            Response(
                {"detail": "배송 중이거나 배송 완료된 주문만 환불이 가능합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )

    order.status = Order.Status.REFUNDED
    order.payment_status = Order.PaymentStatus.PENDING
    order.save(update_fields=["status", "payment_status"])

    return add_cors_headers(
        Response(
            {
                "message": "환불이 완료되었습니다.",
                "order": serialize_order(order, request),
            }
        )
    )


def _handle_exchange(order, request):
    if order.payment_status != Order.PaymentStatus.PAID:
        return add_cors_headers(
            Response(
                {"detail": "결제된 주문만 교환을 요청할 수 있습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status == Order.Status.EXCHANGE_REQUESTED:
        return add_cors_headers(
            Response(
                {"detail": "이미 교환 접수된 주문입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status in (Order.Status.CANCELLED, Order.Status.REFUNDED):
        return add_cors_headers(
            Response(
                {"detail": "취소되었거나 환불된 주문은 교환할 수 없습니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status not in (Order.Status.SHIPPING, Order.Status.DELIVERED):
        return add_cors_headers(
            Response(
                {"detail": "배송 중이거나 배송 완료된 주문만 교환 접수가 가능합니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )

    order.status = Order.Status.EXCHANGE_REQUESTED
    order.save(update_fields=["status"])

    return add_cors_headers(
        Response(
            {
                "message": "교환이 접수되었습니다.",
                "order": serialize_order(order, request),
            }
        )
    )


def _handle_status(order, request):
    return add_cors_headers(
        Response(
            {
                "message": (
                    f"주문 {order.id}은 "
                    f"{order.get_status_display()} 상태이며, "
                    f"{order.get_payment_status_display()}입니다."
                ),
                "order": serialize_order(order, request),
            }
        )
    )
