from models import get_connection


def get_all_categories() -> list:
    """상품 카테고리 목록을 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")
    rows = cursor.fetchall()

    categories = [row[0] for row in rows]

    cursor.close()
    conn.close()
    return categories


def get_all_products(category: str = None, search: str = None) -> list:
    """상품 목록을 조회합니다. 카테고리 필터, 검색 지원."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT product_id, name, brand, price, description, image_url, category, stock FROM products"
    params = {}
    conditions = []

    if category:
        conditions.append("category = :category")
        params["category"] = category

    if search:
        conditions.append("(LOWER(name) LIKE :search OR LOWER(brand) LIKE :search)")
        params["search"] = f"%{search.lower()}%"

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC"

    cursor.execute(query, params)
    rows = cursor.fetchall()

    products = []
    for row in rows:
        products.append({
            "product_id": row[0],
            "name": row[1],
            "brand": row[2],
            "price": row[3],
            "description": row[4].read() if row[4] else "",
            "image_url": row[5],
            "category": row[6],
            "stock": row[7]
        })

    cursor.close()
    conn.close()
    return products


def get_product_by_id(product_id: int) -> dict:
    """상품 상세 정보를 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT product_id, name, brand, price, description, image_url, category, stock FROM products WHERE product_id = :product_id",
        {"product_id": product_id}
    )
    row = cursor.fetchone()

    result = None
    if row:
        result = {
            "product_id": row[0],
            "name": row[1],
            "brand": row[2],
            "price": row[3],
            "description": row[4].read() if row[4] else "",
            "image_url": row[5],
            "category": row[6],
            "stock": row[7]
        }

    cursor.close()
    conn.close()
    return result
