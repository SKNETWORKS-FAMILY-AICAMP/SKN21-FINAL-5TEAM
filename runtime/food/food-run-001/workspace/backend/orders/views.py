from django.conf import settings
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Order


def build_product_image_url(request, image_path):
    if not image_path:
        return None
    if image_path.startswith("http://") or image_path.startswith("https://"):
        return image_path
    base = request.build_absolute_uri(settings.MEDIA_URL)
    return base.rstrip("/") + "/" + image_path.lstrip("/")


def add_cors_headers(response):
    response["Access-Control-Allow-Origin"] = "*"
    return response


def serialize_order(order, request):
    product = order.product
    return {
        "id": order.id,
        "quantity": order.quantity,
        "total_price": order.total_price,
        "status": order.status,
        "payment_status": order.payment_status,
        "created_at": order.created_at,
        "product": {
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "image_url": build_product_image_url(request, product.image),
        },
    }


@api_view(["GET"])
def order_list(request):
    orders = Order.objects.select_related("product").order_by("-created_at")
    payload = [serialize_order(order, request) for order in orders]
    return add_cors_headers(Response(payload))


@api_view(["GET"])
def order_detail(request, order_id):
    order = get_object_or_404(Order.objects.select_related("product"), pk=order_id)
    return add_cors_headers(Response(serialize_order(order, request)))


@api_view(["POST"])
def order_action(request, order_id):
    order = get_object_or_404(Order.objects.select_related("product"), pk=order_id)
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
    if order.status in (Order.Status.CANCELLED, Order.Status.REFUNDED):
        return add_cors_headers(
            Response(
                {"detail": "이미 취소되었거나 환불된 주문입니다."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        )
    if order.status == Order.Status.DELIVERED:
        return add_cors_headers(
            Response(
                {"detail": "배송 완료된 주문은 취소할 수 없습니다."},
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
    if order.status != Order.Status.DELIVERED:
        return add_cors_headers(
            Response(
                {"detail": "배송 완료된 주문만 환불이 가능합니다."},
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
