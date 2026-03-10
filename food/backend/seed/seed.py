import csv
from decimal import Decimal
from pathlib import Path
import os
import sys
import django
import random

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "foodshop.settings")
django.setup()

from django.contrib.auth.models import User
from products.models import Product
from orders.models import Order


# -------------------------
# 상품 생성
# -------------------------
def seed_products():

    csv_path = BASE_DIR / "seed" / "products.csv"

    if not csv_path.exists():
        print(f"{csv_path} not found")
        return

    count = 0

    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)

        for row in reader:

            price = Decimal(row.get("price", "0"))

            defaults = {
                "price": price,
                "stock": int(row.get("stock", "50")),
                "image": row.get("image", ""),
            }

            Product.objects.update_or_create(
                name=row.get("name", "Unnamed Product"),
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