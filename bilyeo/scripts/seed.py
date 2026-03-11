"""
더미 데이터 시드 스크립트
사용법: python seed.py
"""
import sys
import os

# backend 디렉토리를 path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from werkzeug.security import generate_password_hash
from models import get_connection, init_db
from faq_crawling import main as faq_crawling_main
from product_crawling import main as product_crawling_main


def run_crawling():
    """FAQ 및 상품 크롤링을 실행합니다."""
    print("=== 크롤링 시작 ===")

    print("\n[FAQ 크롤링]")
    faq_crawling_main()

    print("\n[상품 크롤링]")
    product_crawling_main()

    print("\n=== 크롤링 완료 ===\n")


def seed_db():
    """더미 데이터를 삽입합니다."""
    # 테이블이 없으면 먼저 생성
    init_db()

    # FAQ 및 상품 크롤링을 먼저 실행
    run_crawling()

    conn = get_connection()
    cursor = conn.cursor()

    # ===== users =====
    print("사용자 데이터 삽입 중...")
    users = [
        ("test@example.com", generate_password_hash("password123"), "김테스트", "010-1234-5678", "서울시 강남구 테헤란로 1"),
        ("user1@example.com", generate_password_hash("password123"), "이영희", "010-2345-6789", "서울시 서초구 서초대로 2"),
        ("user2@example.com", generate_password_hash("password123"), "박철수", "010-3456-7890", "서울시 마포구 홍대입구 3"),
        ("admin@example.com", generate_password_hash("admin1234"), "관리자", "010-0000-0000", "서울시 중구 을지로 4"),
    ]
    for email, password, name, phone, address in users:
        cursor.execute(
            """
            MERGE INTO users u
            USING (SELECT :email AS email FROM dual) d
            ON (u.email = d.email)
            WHEN NOT MATCHED THEN
                INSERT (email, password, name, phone, address)
                VALUES (:email, :password, :name, :phone, :address)
            """,
            {"email": email, "password": password, "name": name, "phone": phone, "address": address}
        )
    conn.commit()
    print(f"  {len(users)}명 처리 완료")

    # user_id 조회
    cursor.execute("SELECT user_id, email FROM users ORDER BY user_id")
    user_rows = cursor.fetchall()
    user_map = {row[1]: row[0] for row in user_rows}

    # ===== DB에서 카테고리별 상품 목록 조회 =====
    print("DB에서 상품 목록 조회 중...")
    cursor.execute("SELECT product_id, name, price, category FROM products ORDER BY category, product_id")
    product_rows = cursor.fetchall()

    if not product_rows:
        print("  상품이 없습니다. 주문 데이터를 생성하려면 먼저 상품을 등록하세요.")
        cursor.close()
        conn.close()
        return

    # 카테고리별로 상품 그룹화 (카테고리당 최대 2개)
    from collections import defaultdict
    category_products = defaultdict(list)
    for pid, pname, pprice, pcategory in product_rows:
        if len(category_products[pcategory]) < 2:
            category_products[pcategory].append((pid, 1, pprice))

    categories = list(category_products.keys())
    print(f"  {len(product_rows)}개 상품, {len(categories)}개 카테고리 확인")

    # ===== orders + order_items =====
    print("주문 데이터 삽입 중...")
    cursor.execute("SELECT COUNT(*) FROM orders")
    order_count = cursor.fetchone()[0]

    if order_count == 0:
        # 사용자 목록
        user_emails = ["test@example.com", "user1@example.com", "user2@example.com"]
        # 주문 상태 (각 배송 상태가 최소 1개씩 존재하도록 순환)
        order_statuses = ["주문완료", "배송중", "배송완료", "주문취소"]

        # 카테고리별 상품 2개씩 주문 생성
        orders_data = []
        for i, category in enumerate(categories):
            email = user_emails[i % len(user_emails)]
            status = order_statuses[i % len(order_statuses)]
            items = category_products[category]
            total_price = sum(price for _, _, price in items)
            orders_data.append((email, total_price, status, items))

        order_ids = []
        for user_email, total_price, status, items in orders_data:
            user_id = user_map.get(user_email)
            if not user_id:
                continue

            # RETURNING으로 생성된 order_id 가져오기
            order_id_var = cursor.var(int)
            cursor.execute(
                """
                INSERT INTO orders (user_id, total_price, status)
                VALUES (:user_id, :total_price, :status)
                RETURNING order_id INTO :order_id
                """,
                {"user_id": user_id, "total_price": total_price, "status": status, "order_id": order_id_var}
            )
            order_id = order_id_var.getvalue()[0]
            order_ids.append((order_id, user_email, status, total_price))

            for product_id, quantity, price in items:
                cursor.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, quantity, price)
                    VALUES (:order_id, :product_id, :quantity, :price)
                    """,
                    {"order_id": order_id, "product_id": product_id, "quantity": quantity, "price": price}
                )

        conn.commit()
        print(f"  {len(order_ids)}건 주문 삽입 완료")

        # ===== payments =====
        print("결제 데이터 삽입 중...")
        payment_methods = ["신용카드", "카카오페이", "네이버페이", "계좌이체"]
        for i, (order_id, user_email, status, total_price) in enumerate(order_ids):
            user_id = user_map.get(user_email)
            method = payment_methods[i % len(payment_methods)]

            if status == "주문취소":
                pay_status = "결제취소"
            else:
                pay_status = "결제완료"

            cursor.execute(
                """
                INSERT INTO payments (order_id, user_id, payment_method, amount, status)
                VALUES (:order_id, :user_id, :payment_method, :amount, :status)
                """,
                {"order_id": order_id, "user_id": user_id, "payment_method": method,
                 "amount": total_price, "status": pay_status}
            )
        conn.commit()
        print(f"  {len(order_ids)}건 결제 삽입 완료")

        # ===== shipping =====
        print("배송 데이터 삽입 중...")
        carriers = ["CJ대한통운", "한진택배", "롯데택배", "로젠택배"]
        for i, (order_id, user_email, status, total_price) in enumerate(order_ids):
            carrier = carriers[i % len(carriers)]
            tracking = f"TRACK{order_id:08d}"

            if status == "주문취소":
                ship_status = "배송취소"
                shipped_at = "NULL"
                delivered_at = "NULL"
            elif status == "배송완료":
                ship_status = "배송완료"
                shipped_at = "CURRENT_TIMESTAMP - INTERVAL '3' DAY"
                delivered_at = "CURRENT_TIMESTAMP - INTERVAL '1' DAY"
            elif status == "배송중":
                ship_status = "배송중"
                shipped_at = "CURRENT_TIMESTAMP - INTERVAL '1' DAY"
                delivered_at = "NULL"
            else:
                ship_status = "배송준비중"
                shipped_at = "NULL"
                delivered_at = "NULL"

            cursor.execute(
                f"""
                INSERT INTO shipping (order_id, status, carrier, tracking_number, shipped_at, delivered_at)
                VALUES (:order_id, :status, :carrier, :tracking_number, {shipped_at}, {delivered_at})
                """,
                {"order_id": order_id, "status": ship_status, "carrier": carrier, "tracking_number": tracking}
            )
        conn.commit()
        print(f"  {len(order_ids)}건 배송 삽입 완료")

    else:
        print(f"  이미 {order_count}건 주문 존재, 건너뜀")

    cursor.close()
    conn.close()
    print("=== 시드 데이터 삽입 완료 ===")


if __name__ == "__main__":
    seed_db()
