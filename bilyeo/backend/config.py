import os

# Oracle DB 설정
ORACLE_USER = os.environ.get("ORACLE_USER", "bilyeo")
ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "0310")
ORACLE_HOST = os.environ.get("ORACLE_HOST", "DESKTOP-IMG07LN")
ORACLE_PORT = os.environ.get("ORACLE_PORT", "1521")
ORACLE_SERVICE_NAME = os.environ.get("ORACLE_SERVICE_NAME", "freepdb1")
ORACLE_DSN = f"{ORACLE_HOST}:{ORACLE_PORT}/{ORACLE_SERVICE_NAME}"

# JWT 시크릿 키
SECRET_KEY = os.environ.get("SECRET_KEY", "your-secret-key-change-in-production")

# JWT 토큰 만료 시간 (초)
JWT_EXPIRATION = 3600
