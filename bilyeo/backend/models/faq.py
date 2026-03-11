from models import get_connection


def insert_faq_batch(faq_list):
    """FAQ 데이터를 일괄 삽입합니다. 중복은 무시합니다.

    Args:
        faq_list: [(source, category, question, answer), ...] 형태의 리스트
    """
    conn = get_connection()
    cursor = conn.cursor()
    inserted = 0
    try:
        for source, category, question, answer in faq_list:
            cursor.execute("""
                MERGE INTO faq f
                USING (SELECT :source AS source, :question AS question FROM dual) d
                ON (f.source = d.source AND f.question = d.question)
                WHEN NOT MATCHED THEN
                    INSERT (source, category, question, answer)
                    VALUES (:source, :category, :question, :answer)
            """, {
                "source": source,
                "category": category,
                "question": question,
                "answer": answer,
            })
            inserted += cursor.rowcount
        conn.commit()
    finally:
        cursor.close()
        conn.close()
    return inserted


def get_all_faq(source=None, category=None):
    """FAQ 목록을 조회합니다."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        query = "SELECT faq_id, source, category, question, answer, created_at FROM faq WHERE 1=1"
        params = {}

        if source:
            query += " AND source = :source"
            params["source"] = source
        if category:
            query += " AND category = :category"
            params["category"] = category

        query += " ORDER BY faq_id"
        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "faq_id": row[0],
                "source": row[1],
                "category": row[2],
                "question": row[3],
                "answer": row[4] if row[4] else "",
                "created_at": str(row[5]) if row[5] else None,
            }
            for row in rows
        ]
    finally:
        cursor.close()
        conn.close()
