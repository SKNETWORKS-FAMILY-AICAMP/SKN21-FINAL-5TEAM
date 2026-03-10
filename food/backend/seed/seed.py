import csv
from decimal import Decimal
from pathlib import Path
import os
import sys
import django

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "foodshop.settings")
    django.setup()

    from products.models import Product

    csv_path = BASE_DIR / "seed" / "products.csv"

    if not csv_path.exists():
        print(f"{csv_path} not found")
        return

    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            price = Decimal(row.get("price", "0"))

            defaults = {
                "price": price,
                "stock": int(row.get("stock", "50")),
                "image": row.get("image", ""),
            }

            obj, created = Product.objects.update_or_create(
                name=row.get("name", "Unnamed Product"),
                defaults=defaults,
            )

            status = "created" if created else "updated"
            print(f"{status}: {obj.name}")

if __name__ == "__main__":
    main()