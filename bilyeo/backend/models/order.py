from models import get_connection


def get_orders_by_user(user_id: int) -> list:
    """사용자의 주문 목록을 조회합니다."""
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
        WHERE o.user_id = :user_id
        ORDER BY o.created_at DESC
        """,
        {"user_id": user_id}
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    # 주문별로 그룹핑
    orders_dict = {}
    for row in rows:
        order_id = row[0]
        if order_id not in orders_dict:
            orders_dict[order_id] = {
                "order_id": order_id,
                "total_price": row[1],
                "status": row[2],
                "created_at": str(row[3]),
                "items": []
            }
        orders_dict[order_id]["items"].append({
            "item_id": row[4],
            "product_id": row[5],
            "quantity": row[6],
            "price": row[7],
            "product_name": row[8],
            "image_url": row[9]
        })

    return list(orders_dict.values())
