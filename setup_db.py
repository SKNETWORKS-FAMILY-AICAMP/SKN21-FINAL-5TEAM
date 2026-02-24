import pymysql
import getpass
import os
from dotenv import load_dotenv
import sys

# Load .env variables
load_dotenv()

TARGET_USER = os.getenv("DB_USER", "ecom_user")
TARGET_PW = os.getenv("DB_PASSWORD", "ecopchatbot!")
TARGET_DB = os.getenv("DB_NAME", "ecommerce_db")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))

print("=== Local MySQL Setup Script ===")
print("이 스크립트는 .env 파일에 정의된 데이터베이스와 유저를 생성합니다.")
print(f"대상 데이터베이스: {TARGET_DB}")
print(f"대상 유저:        {TARGET_USER}")
print(f"접속 호스트:      {DB_HOST}:{DB_PORT}")
print("================================")
print("MySQL 'root' 계정의 비밀번호가 필요합니다.")

try:
    root_password = getpass.getpass("MySQL root 비밀번호 입력 (없으면 엔터): ")
except Exception:
    # Some environments might fail on getpass
    root_password = input("MySQL root 비밀번호 입력 (없으면 엔터): ")

try:
    # Connect as root
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user='root',
        password=root_password,
        charset='utf8mb4'
    )
    
    with conn.cursor() as cursor:
        print(f"\n[1/4] 데이터베이스 '{TARGET_DB}' 생성 확인...")
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {TARGET_DB};")
        
        print(f"[2/4] 유저 '{TARGET_USER}' 생성...")
        # Create user if not exists
        cursor.execute(f"CREATE USER IF NOT EXISTS '{TARGET_USER}'@'localhost' IDENTIFIED BY '{TARGET_PW}';")
        
        # Update password to ensure it matches .env (in case user already exists with old pw)
        print(f"[2-1/4] 유저 비밀번호 동기화...")
        cursor.execute(f"ALTER USER '{TARGET_USER}'@'localhost' IDENTIFIED BY '{TARGET_PW}';")
        
        print(f"[3/4] 권한 부여...")
        cursor.execute(f"GRANT ALL PRIVILEGES ON {TARGET_DB}.* TO '{TARGET_USER}'@'localhost';")
        
        print("[4/4] 권한 적용 (FLUSH PRIVILEGES)...")
        cursor.execute("FLUSH PRIVILEGES;")
        
    conn.commit()
    print("\n✅ 성공! 데이터베이스와 유저가 정상적으로 설정되었습니다.")
    print("이제 애플리케이션을 실행해보세요.")
    
except pymysql.err.OperationalError as e:
    code, msg = e.args
    if code == 1045:
        print(f"\n❌ [오류] 'root' 계정 로그인 실패. 비밀번호를 확인해주세요.")
    elif code == 2003:
        print(f"\n❌ [오류] MySQL 서버에 연결할 수 없습니다. MySQL이 실행 중인지 확인해주세요.\n(Host: {DB_HOST}, Port: {DB_PORT})")
    else:
        print(f"\n❌ [오류] MySQL 에러 발생: {e}")
except Exception as e:
    print(f"\n❌ [오류] 예상치 못한 에러: {e}")
finally:
    if 'conn' in locals() and conn.open:
        conn.close()
