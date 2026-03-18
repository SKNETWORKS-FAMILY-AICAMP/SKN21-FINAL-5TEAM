from models import get_connection


def get_all_orders() -> list:
    """전체 주문 목록을 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT o.order_id, o.user_id, o.total_price, o.status, o.created_at,
               oi.item_id, oi.product_id, oi.quantity, oi.price,
               p.name AS product_name, p.image_url
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        ORDER BY o.created_at DESC
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    orders_dict = {}
    for row in rows:
        order_id = row[0]
        if order_id not in orders_dict:
            orders_dict[order_id] = {
                "order_id": order_id,
                "user_id": row[1],
                "total_price": row[2],
                "status": row[3],
                "created_at": str(row[4]),
                "items": []
            }
        orders_dict[order_id]["items"].append({
            "item_id": row[5],
            "product_id": row[6],
            "quantity": row[7],
            "price": row[8],
            "product_name": row[9],
            "image_url": row[10]
        })

    return list(orders_dict.values())


def get_order_detail(order_id: int) -> dict:
    """단건 주문을 상세 조회합니다. (주문 + 아이템 + 결제 + 배송)"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT o.order_id, o.total_price, o.status, o.created_at,
               oi.item_id, oi.product_id, oi.quantity, oi.price,
               p.name AS product_name, p.image_url
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        WHERE o.order_id = :order_id
        """,
        {"order_id": order_id}
    )
    rows = cursor.fetchall()

    if not rows:
        cursor.close()
        conn.close()
        return None

    order = {
        "order_id": rows[0][0],
        "total_price": rows[0][1],
        "status": rows[0][2],
        "created_at": str(rows[0][3]),
        "items": []
    }
    for row in rows:
        order["items"].append({
            "item_id": row[4],
            "product_id": row[5],
            "quantity": row[6],
            "price": row[7],
            "product_name": row[8],
            "image_url": row[9]
        })

    # 결제 정보
    cursor.execute(
        """
        SELECT payment_id, payment_method, amount, status, paid_at
        FROM payments
        WHERE order_id = :order_id
        """,
        {"order_id": order_id}
    )
    pay_row = cursor.fetchone()
    if pay_row:
        order["payment"] = {
            "payment_id": pay_row[0],
            "payment_method": pay_row[1],
            "amount": pay_row[2],
            "status": pay_row[3],
            "paid_at": str(pay_row[4]) if pay_row[4] else None
        }

    # 배송 정보
    cursor.execute(
        """
        SELECT shipping_id, status, carrier, tracking_number, shipped_at, delivered_at
        FROM shipping
        WHERE order_id = :order_id
        """,
        {"order_id": order_id}
    )
    ship_row = cursor.fetchone()
    if ship_row:
        order["shipping"] = {
            "shipping_id": ship_row[0],
            "status": ship_row[1],
            "carrier": ship_row[2],
            "tracking_number": ship_row[3],
            "shipped_at": str(ship_row[4]) if ship_row[4] else None,
            "delivered_at": str(ship_row[5]) if ship_row[5] else None
        }

    cursor.close()
    conn.close()
    return order


def cancel_order(order_id: int) -> dict:
    """주문을 취소합니다. (주문상태 변경 + 결제취소 + 재고 복구)"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT status FROM orders WHERE order_id = :order_id",
        {"order_id": order_id}
    )
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return {"error": "주문을 찾을 수 없습니다.", "code": 404}

    if row[0] in ("주문취소", "환불완료"):
        cursor.close()
        conn.close()
        return {"error": f"이미 '{row[0]}' 상태인 주문은 취소할 수 없습니다.", "code": 400}

    # 1. 주문 상태 변경
    cursor.execute(
        "UPDATE orders SET status = '주문취소' WHERE order_id = :order_id",
        {"order_id": order_id}
    )

    # 2. 결제 상태 변경
    cursor.execute(
        "UPDATE payments SET status = '결제취소' WHERE order_id = :order_id",
        {"order_id": order_id}
    )

    # 3. 재고 복구
    cursor.execute(
        "SELECT product_id, quantity FROM order_items WHERE order_id = :order_id",
        {"order_id": order_id}
    )
    items = cursor.fetchall()
    for product_id, quantity in items:
        cursor.execute(
            "UPDATE products SET stock = stock + :quantity WHERE product_id = :product_id",
            {"quantity": quantity, "product_id": product_id}
        )

    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True, "message": "주문이 취소되었습니다."}


def exchange_order(order_id: int) -> dict:
    """교환을 접수합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT status FROM orders WHERE order_id = :order_id",
        {"order_id": order_id}
    )
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return {"error": "주문을 찾을 수 없습니다.", "code": 404}

    if row[0] in ("주문취소", "환불완료", "교환접수"):
        cursor.close()
        conn.close()
        return {"error": f"'{row[0]}' 상태인 주문은 교환할 수 없습니다.", "code": 400}

    cursor.execute(
        "UPDATE orders SET status = '교환접수' WHERE order_id = :order_id",
        {"order_id": order_id}
    )

    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True, "message": "교환이 접수되었습니다."}


def refund_order(order_id: int) -> dict:
    """환불을 처리합니다. (주문상태 변경 + 결제환불 + 재고 복구)"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT status FROM orders WHERE order_id = :order_id",
        {"order_id": order_id}
    )
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return {"error": "주문을 찾을 수 없습니다.", "code": 404}

    if row[0] in ("주문취소", "환불완료"):
        cursor.close()
        conn.close()
        return {"error": f"이미 '{row[0]}' 상태인 주문은 환불할 수 없습니다.", "code": 400}

    # 1. 주문 상태 변경
    cursor.execute(
        "UPDATE orders SET status = '환불완료' WHERE order_id = :order_id",
        {"order_id": order_id}
    )

    # 2. 결제 상태 변경
    cursor.execute(
        "UPDATE payments SET status = '환불완료' WHERE order_id = :order_id",
        {"order_id": order_id}
    )

    # 3. 재고 복구
    cursor.execute(
        "SELECT product_id, quantity FROM order_items WHERE order_id = :order_id",
        {"order_id": order_id}
    )
    items = cursor.fetchall()
    for product_id, quantity in items:
        cursor.execute(
            "UPDATE products SET stock = stock + :quantity WHERE product_id = :product_id",
            {"quantity": quantity, "product_id": product_id}
        )

    conn.commit()
    cursor.close()
    conn.close()
    return {"success": True, "message": "환불이 완료되었습니다."}
