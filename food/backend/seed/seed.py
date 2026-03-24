import csv
import os
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import django
from django.utils import timezone

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "foodshop.settings")
django.setup()

from django.contrib.auth.models import User
from orders.models import Order
from products.models import Product
from users.models import SessionToken


def normalize_image_value(raw_value: str) -> str:
    image_value = (raw_value or "").strip()
    if not image_value:
        return ""

    if image_value.startswith(("http://", "https://")):
        return image_value

    image_base_url = os.getenv("FOOD_IMAGE_BASE_URL", "").strip().rstrip("/")
    if image_base_url:
        return f"{image_base_url}/{image_value.lstrip('/')}"

    return image_value


# -------------------------
# 상품 생성
# -------------------------
def seed_products():
    csv_override = os.getenv("FOOD_PRODUCTS_CSV", "").strip()
    csv_path = Path(csv_override) if csv_override else BASE_DIR / "seed" / "products.csv"

    if not csv_path.exists():
        print(f"{csv_path} not found")
        return

    count = 0
    print(f"using products csv : {csv_path}")

    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)

        for row in reader:
            product_id = (row.get("id") or "").strip()
            product_name = row.get("name", "Unnamed Product")

            price = Decimal(row.get("price", "0"))

            defaults = {
                "name": product_name,
                "price": price,
                "stock": int(row.get("stock", "50")),
                "image": normalize_image_value(row.get("image", "")),
            }

            if product_id:
                Product.objects.update_or_create(
                    id=int(product_id),
                    defaults=defaults,
                )
            else:
                Product.objects.update_or_create(
                    name=product_name,
                    defaults=defaults,
                )

            count += 1

    print(f"products created : {count}")

# -------------------------
# 테스트 유저 생성
# -------------------------
def seed_users():

    users = [
        {
            "username": "test1",
            "email": "test1@example.com",
            "password": "password123"
        },
        {
            "username": "test2",
            "email": "test2@example.com",
            "password": "password123"
        },
    ]

    for user in users:

        if not User.objects.filter(username=user["username"]).exists():

            User.objects.create_user(
                username=user["username"],
                email=user["email"],
                password=user["password"]
            )

            print(f"user created : {user['username']}")

        else:
            print(f"user exists : {user['username']}")

        user_obj = User.objects.get(username=user["username"])
        SessionToken.objects.filter(user=user_obj, is_active=True).update(is_active=False)
        SessionToken.objects.create(
            user=user_obj,
            token=uuid.uuid4().hex,
            expires_at=timezone.now() + timedelta(days=7),
        )


# -------------------------
# 주문 생성
# -------------------------
def seed_orders():

    user = User.objects.filter(username="test1").first()

    if not user:
        print("user not found")
        return

    products = Product.objects.all()[:3]

    if len(products) < 3:
        print("not enough products")
        return

    statuses = [
        "preparing",
        "shipping",
        "delivered"
    ]

    for product, status in zip(products, statuses):

        Order.objects.create(
            user=user,
            product=product,
            quantity=1,
            total_price=product.price,
            status=status
        )

    print("orders created : 3")


# -------------------------
# 실행
# -------------------------
def main():

    seed_products()
    seed_users()
    seed_orders()


if __name__ == "__main__":
    main()
