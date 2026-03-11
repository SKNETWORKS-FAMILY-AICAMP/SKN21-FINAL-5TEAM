"""
DB 초기화 스크립트
모든 테이블을 DROP 후 재생성합니다.
사용법: python reset_db.py
"""
import sys
import os
import oracledb

# backend 디렉토리를 path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from models import get_connection, init_db


# FK 의존 관계를 고려한 DROP 순서 (자식 테이블부터 삭제)
DROP_ORDER = [
    "faq",
    "shipping",
    "payments",
    "order_items",
    "orders",
    "products",
    "users",
]


def reset_db():
    """모든 테이블을 DROP 후 재생성합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    print("=== 테이블 삭제 시작 ===")
    for table in DROP_ORDER:
        try:
            cursor.execute(f"DROP TABLE {table} CASCADE CONSTRAINTS")
            print(f"  {table} 테이블 삭제 완료")
        except oracledb.DatabaseError as e:
            if e.args[0].code == 942:
                print(f"  {table} 테이블 없음 (스킵)")
            else:
                raise

    conn.commit()
    cursor.close()
    conn.close()

    print("=== 테이블 재생성 시작 ===")
    init_db()
    print("=== DB 초기화 완료 ===")


if __name__ == "__main__":
    confirm = input("모든 데이터가 삭제됩니다. 계속하시겠습니까? (y/n): ")
    if confirm.lower() == "y":
        reset_db()
    else:
        print("취소되었습니다.")
