from models import get_connection


def create_payment(order_id: int, user_id: int, payment_method: str, amount: int) -> dict:
    """결제를 생성합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO payments (order_id, user_id, payment_method, amount, status)
        VALUES (:order_id, :user_id, :payment_method, :amount, '결제완료')
        """,
        {"order_id": order_id, "user_id": user_id, "payment_method": payment_method, "amount": amount}
    )
    conn.commit()

    # 생성된 결제 조회
    cursor.execute(
        """
        SELECT payment_id, order_id, user_id, payment_method, amount, status, paid_at, created_at
        FROM payments
        WHERE order_id = :order_id AND user_id = :user_id
        ORDER BY created_at DESC FETCH FIRST 1 ROW ONLY
        """,
        {"order_id": order_id, "user_id": user_id}
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return {
            "payment_id": row[0],
            "order_id": row[1],
            "user_id": row[2],
            "payment_method": row[3],
            "amount": row[4],
            "status": row[5],
            "paid_at": str(row[6]) if row[6] else None,
            "created_at": str(row[7])
        }
    return None


def get_payment_by_order(order_id: int) -> dict:
    """주문 ID로 결제 정보를 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT payment_id, order_id, user_id, payment_method, amount, status, paid_at, created_at
        FROM payments
        WHERE order_id = :order_id
        """,
        {"order_id": order_id}
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return {
            "payment_id": row[0],
            "order_id": row[1],
            "user_id": row[2],
            "payment_method": row[3],
            "amount": row[4],
            "status": row[5],
            "paid_at": str(row[6]) if row[6] else None,
            "created_at": str(row[7])
        }
    return None


def get_payments_by_user(user_id: int) -> list:
    """사용자의 결제 목록을 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT payment_id, order_id, user_id, payment_method, amount, status, paid_at, created_at
        FROM payments
        WHERE user_id = :user_id
        ORDER BY created_at DESC
        """,
        {"user_id": user_id}
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    payments = []
    for row in rows:
        payments.append({
            "payment_id": row[0],
            "order_id": row[1],
            "user_id": row[2],
            "payment_method": row[3],
            "amount": row[4],
            "status": row[5],
            "paid_at": str(row[6]) if row[6] else None,
            "created_at": str(row[7])
        })
    return payments


def cancel_payment(payment_id: int) -> bool:
    """결제를 취소합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE payments SET status = '결제취소'
        WHERE payment_id = :payment_id
        """,
        {"payment_id": payment_id}
    )
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    return affected > 0


def refund_payment(payment_id: int) -> bool:
    """결제를 환불 처리합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE payments SET status = '환불완료'
        WHERE payment_id = :payment_id
        """,
        {"payment_id": payment_id}
    )
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    return affected > 0
