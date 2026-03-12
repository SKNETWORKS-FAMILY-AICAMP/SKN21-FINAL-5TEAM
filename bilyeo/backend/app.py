import os
from dotenv import load_dotenv
from pathlib import Path

# 프로젝트 루트의 .env 파일 로드
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

from flask import Flask
from flask_cors import CORS

from routes.auth import auth_bp
from routes.product import product_bp
from routes.order import order_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
    CORS(app)

    # 블루프린트 등록
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(product_bp, url_prefix="/api/products")
    app.register_blueprint(order_bp, url_prefix="/api/orders")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
