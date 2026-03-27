import os
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

from chat_auth import chat_auth_bp
from models import init_db
from routes.auth import auth_bp
from routes.order import order_bp
from routes.product import product_bp

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)


def init_db_with_retry(max_attempts: int = 30, delay_seconds: int = 5):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            init_db()
            print(f"[bilyeo] Oracle schema ready (attempt {attempt}/{max_attempts})")
            return
        except Exception as exc:
            last_error = exc
            print(f"[bilyeo] Oracle init failed (attempt {attempt}/{max_attempts}): {exc}")
            if attempt < max_attempts:
                time.sleep(delay_seconds)
    raise last_error


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
    CORS(app)

    init_db_with_retry()

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(product_bp, url_prefix="/api/products")
    app.register_blueprint(order_bp, url_prefix="/api/orders")
    app.register_blueprint(chat_auth_bp, url_prefix="/api")
    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
