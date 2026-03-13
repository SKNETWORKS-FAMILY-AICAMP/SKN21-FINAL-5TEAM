import oracledb
from config import ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN


def get_connection():
    """Oracle DB 연결을 반환합니다."""
    connection = oracledb.connect(
        user=ORACLE_USER,
        password=ORACLE_PASSWORD,
        dsn=ORACLE_DSN
    )
    return connection


def _create_table(cursor, sql):
    """테이블 생성. 이미 존재하면(ORA-00955) 무시합니다."""
    try:
        cursor.execute(sql)
    except oracledb.DatabaseError as e:
        if e.args[0].code == 955:
            pass  # 테이블이 이미 존재
        else:
            raise


def init_db():
    """DB 테이블을 초기화합니다. 테이블이 없으면 생성합니다."""
    conn = get_connection()
    cursor = conn.cursor()

    # users 테이블
    _create_table(cursor, """
        CREATE TABLE users (
            user_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            email VARCHAR2(100) UNIQUE NOT NULL,
            password VARCHAR2(255) NOT NULL,
            name VARCHAR2(50) NOT NULL,
            phone VARCHAR2(20),
            address VARCHAR2(300),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # products 테이블
    _create_table(cursor, """
        CREATE TABLE products (
            product_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            name VARCHAR2(200) NOT NULL,
            brand VARCHAR2(100),
            price NUMBER NOT NULL,
            description CLOB,
            image_url VARCHAR2(500),
            category VARCHAR2(50),
            stock NUMBER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # orders 테이블
    _create_table(cursor, """
        CREATE TABLE orders (
            order_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id NUMBER NOT NULL REFERENCES users(user_id),
            total_price NUMBER NOT NULL,
            status VARCHAR2(20) DEFAULT '주문완료',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # order_items 테이블
    _create_table(cursor, """
        CREATE TABLE order_items (
            item_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            order_id NUMBER NOT NULL REFERENCES orders(order_id),
            product_id NUMBER NOT NULL REFERENCES products(product_id),
            quantity NUMBER NOT NULL,
            price NUMBER NOT NULL
        )
    """)

    # payments 테이블
    _create_table(cursor, """
        CREATE TABLE payments (
            payment_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            order_id NUMBER NOT NULL REFERENCES orders(order_id),
            user_id NUMBER NOT NULL REFERENCES users(user_id),
            payment_method VARCHAR2(50) NOT NULL,
            amount NUMBER NOT NULL,
            status VARCHAR2(20) DEFAULT '결제완료',
            paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # shipping 테이블
    _create_table(cursor, """
        CREATE TABLE shipping (
            shipping_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            order_id NUMBER NOT NULL REFERENCES orders(order_id),
            status VARCHAR2(20) DEFAULT '배송준비중',
            carrier VARCHAR2(100),
            tracking_number VARCHAR2(100),
            shipped_at TIMESTAMP,
            delivered_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # faq 테이블
    _create_table(cursor, """
        CREATE TABLE faq (
            faq_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source VARCHAR2(100) NOT NULL,
            category VARCHAR2(100),
            question VARCHAR2(2000) NOT NULL,
            answer CLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # product_info 테이블
    _create_table(cursor, """
        CREATE TABLE product_info (
            info_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            product_id NUMBER NOT NULL REFERENCES products(product_id),
            volume_weight VARCHAR2(500),
            main_spec VARCHAR2(500),
            expiry VARCHAR2(500),
            usage_method CLOB,
            manufacturer CLOB,
            country_of_origin VARCHAR2(200),
            ingredients CLOB,
            functional_cosmetic VARCHAR2(500),
            precautions CLOB,
            quality_standard VARCHAR2(500),
            consumer_hotline VARCHAR2(200),
            review CLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()
