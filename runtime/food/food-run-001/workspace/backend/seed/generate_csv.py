import os
import csv
import random

BASE_DIR = r"food/backend/media/products"
OUTPUT_FILE = r"food/backend/seed/products.csv"

prefix_list = ["국내산", "프리미엄", "유기농", "신선한", "고당도"]
weight_list = ["500g", "1kg"]

name_map = {
    "apple": "사과",
    "banana": "바나나",
    "beetroot": "비트",
    "bell_pepper": "피망",
    "cabbage": "양배추",
    "capsicum": "파프리카",
    "carrot": "당근",
    "cauliflower": "콜리플라워",
    "chilli_pepper": "고추",
    "corn": "옥수수",
    "cucumber": "오이",
    "eggplant": "가지",
    "garlic": "마늘",
    "ginger": "생강",
    "grapes": "포도",
    "jalepeno": "할라피뇨",
    "kiwi": "키위",
    "lemon": "레몬",
    "lettuce": "상추",
    "mango": "망고",
    "onion": "양파",
    "orange": "오렌지",
    "paprika": "파프리카",
    "pear": "배",
    "peas": "완두콩",
    "pineapple": "파인애플",
    "pomegranate": "석류",
    "potato": "감자",
    "raddish": "무",
    "soy_beans": "대두",
    "spinach": "시금치",
    "sweetcorn": "옥수수",
    "sweetpotato": "고구마",
    "tomato": "토마토",
    "turnip": "순무",
    "watermelon": "수박"
}

data = []
product_id = 1

# 폴더 정렬 → CSV 항상 동일하게 생성
for product in sorted(os.listdir(BASE_DIR)):

    product_path = os.path.join(BASE_DIR, product)

    if not os.path.isdir(product_path):
        continue

    images = [
        f for f in os.listdir(product_path)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    images.sort()

    korean_name = name_map.get(product, product)

    # prefix 중복 방지용
    used_prefix = []

    for image in images:

        # prefix 겹치지 않게
        prefix = random.choice(prefix_list)
        while prefix in used_prefix:
            prefix = random.choice(prefix_list)

        used_prefix.append(prefix)

        weight = random.choice(weight_list)

        name = f"{prefix} {korean_name} {weight}"

        description = f"{korean_name} 신선 식품"

        price = random.randint(2000, 6000)

        image_path = f"products/{product}/{image}"

        stock = 100

        data.append([
            product_id,
            name,
            description,
            price,
            image_path,
            stock
        ])

        product_id += 1


with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:

    writer = csv.writer(f)

    writer.writerow(["id", "name", "description", "price", "image", "stock"])

    writer.writerows(data)

print("products.csv 생성 완료")