from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Product
from .image_utils import build_product_image_url

@api_view(["GET"])
def product_list(request):
    products = []
    for product in Product.objects.all():
        products.append(
            {
                "id": product.id,
                "name": product.name,
                "price": product.price,
                "image": build_product_image_url(request, product.image),
                "stock": product.stock,
            }
        )
    return Response(products)
