from models import get_connection


def find_user_by_email(email: str) -> dict:
    """이메일로 사용자를 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id, email, password, name, phone, address FROM users WHERE email = :email",
        {"email": email}
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return {
            "user_id": row[0], "email": row[1], "password": row[2],
            "name": row[3], "phone": row[4], "address": row[5]
        }
    return None


def find_user_by_id(user_id: int) -> dict:
    """사용자 ID로 사용자를 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id, email, name, phone, address FROM users WHERE user_id = :user_id",
        {"user_id": user_id}
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()

    if row:
        return {"user_id": row[0], "email": row[1], "name": row[2], "phone": row[3], "address": row[4]}
    return None
