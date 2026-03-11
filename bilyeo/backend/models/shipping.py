from models import get_connection


def create_shipping(order_id: int, carrier: str = None, tracking_number: str = None) -> dict:
    """배송 정보를 생성합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO shipping (order_id, status, carrier, tracking_number)
        VALUES (:order_id, '배송준비중', :carrier, :tracking_number)
        """,
        {"order_id": order_id, "carrier": carrier, "tracking_number": tracking_number}
    )
    conn.commit()

    # 생성된 배송 정보 조회
    cursor.execute(
        """
        SELECT shipping_id, order_id, status, carrier, tracking_number, shipped_at, delivered_at, created_at
        FROM shipping
        WHERE order_id = :order_id
        ORDER BY created_at DESC FETCH FIRST 1 ROW ONLY
        """,
        {"order_id": order_id}
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return {
            "shipping_id": row[0],
            "order_id": row[1],
            "status": row[2],
            "carrier": row[3],
            "tracking_number": row[4],
            "shipped_at": str(row[5]) if row[5] else None,
            "delivered_at": str(row[6]) if row[6] else None,
            "created_at": str(row[7])
        }
    return None


def get_shipping_by_order(order_id: int) -> dict:
    """주문 ID로 배송 상태를 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT shipping_id, order_id, status, carrier, tracking_number, shipped_at, delivered_at, created_at
        FROM shipping
        WHERE order_id = :order_id
        """,
        {"order_id": order_id}
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return {
            "shipping_id": row[0],
            "order_id": row[1],
            "status": row[2],
            "carrier": row[3],
            "tracking_number": row[4],
            "shipped_at": str(row[5]) if row[5] else None,
            "delivered_at": str(row[6]) if row[6] else None,
            "created_at": str(row[7])
        }
    return None


def update_shipping_status(shipping_id: int, status: str) -> bool:
    """배송 상태를 업데이트합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    # 배송중으로 변경 시 shipped_at 설정
    if status == "배송중":
        cursor.execute(
            """
            UPDATE shipping SET status = :status, shipped_at = CURRENT_TIMESTAMP
            WHERE shipping_id = :shipping_id
            """,
            {"status": status, "shipping_id": shipping_id}
        )
    # 배송완료로 변경 시 delivered_at 설정
    elif status == "배송완료":
        cursor.execute(
            """
            UPDATE shipping SET status = :status, delivered_at = CURRENT_TIMESTAMP
            WHERE shipping_id = :shipping_id
            """,
            {"status": status, "shipping_id": shipping_id}
        )
    else:
        cursor.execute(
            """
            UPDATE shipping SET status = :status
            WHERE shipping_id = :shipping_id
            """,
            {"status": status, "shipping_id": shipping_id}
        )

    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    return affected > 0


def update_tracking_info(shipping_id: int, carrier: str, tracking_number: str) -> bool:
    """운송장 정보를 업데이트합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE shipping SET carrier = :carrier, tracking_number = :tracking_number
        WHERE shipping_id = :shipping_id
        """,
        {"carrier": carrier, "tracking_number": tracking_number, "shipping_id": shipping_id}
    )
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    return affected > 0
