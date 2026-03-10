from django.conf import settings
from django.shortcuts import resolve_url
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


@api_view(["GET"])
def order_list(request):
    orders = (
        Order.objects.select_related("product")
        .order_by("-created_at")
        .values(
            "id",
            "quantity",
            "total_price",
            "status",
            "payment_status",
            "created_at",
            "product__id",
            "product__name",
            "product__price",
            "product__image",
        )
    )

    payload = []
    for entry in orders:
        payload.append(
            {
                "id": entry["id"],
                "quantity": entry["quantity"],
                "total_price": entry["total_price"],
                "status": entry["status"],
                "payment_status": entry["payment_status"],
                "created_at": entry["created_at"],
                "product": {
                    "id": entry["product__id"],
                    "name": entry["product__name"],
                    "price": entry["product__price"],
                    "image_url": build_product_image_url(request, entry["product__image"]),
                },
            }
        )

    response = Response(payload)
    response["Access-Control-Allow-Origin"] = "*"
    return response
