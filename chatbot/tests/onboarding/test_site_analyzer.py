import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.site_analyzer import analyze_site


def test_analyze_site_detects_auth_product_order_and_frontend_mount(tmp_path: Path):
    site_root = tmp_path / "food"

    backend_users = site_root / "backend" / "users"
    backend_products = site_root / "backend" / "products"
    backend_orders = site_root / "backend" / "orders"
    frontend_src = site_root / "frontend" / "src"

    backend_users.mkdir(parents=True)
    backend_products.mkdir(parents=True)
    backend_orders.mkdir(parents=True)
    frontend_src.mkdir(parents=True)

    (backend_users / "views.py").write_text(
        """
def login(request):
    return None

def me(request):
    return None
""",
        encoding="utf-8",
    )
    (backend_products / "urls.py").write_text(
        """
urlpatterns = [
    path("api/products/", include("products.urls")),
]
""",
        encoding="utf-8",
    )
    (backend_orders / "urls.py").write_text(
        """
urlpatterns = [
    path("api/orders/", include("orders.urls")),
]
""",
        encoding="utf-8",
    )
    (frontend_src / "App.js").write_text(
        """
function App() {
  return (
    <>
      <Chatbot />
    </>
  );
}
""",
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)

    assert analysis["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]
    assert analysis["auth"]["me_entrypoints"] == ["backend/users/views.py:me"]
    assert analysis["auth"]["auth_style"] == "unknown"
    assert analysis["product_api"] == ["/api/products/"]
    assert analysis["order_api"] == ["/api/orders/"]
    assert analysis["frontend_mount_points"] == ["frontend/src/App.js"]
    assert analysis["framework"]["backend"] == "django"
    assert analysis["framework"]["frontend"] == "react"
    assert analysis["backend_entrypoints"] == []


def test_analyze_site_returns_empty_lists_when_targets_are_missing(tmp_path: Path):
    site_root = tmp_path / "empty-site"
    site_root.mkdir(parents=True)

    analysis = analyze_site(site_root)

    assert analysis["auth"]["login_entrypoints"] == []
    assert analysis["auth"]["me_entrypoints"] == []
    assert analysis["product_api"] == []
    assert analysis["order_api"] == []
    assert analysis["frontend_mount_points"] == []
    assert analysis["auth"]["auth_style"] == "unknown"
    assert analysis["framework"]["backend"] == "unknown"
    assert analysis["framework"]["frontend"] == "unknown"
    assert analysis["backend_entrypoints"] == []


def test_analyze_site_detects_django_cookie_session_signals(tmp_path: Path):
    site_root = tmp_path / "food"
    backend_users = site_root / "backend" / "users"
    backend_shop = site_root / "backend" / "foodshop"
    frontend_src = site_root / "frontend" / "src"

    backend_users.mkdir(parents=True)
    backend_shop.mkdir(parents=True)
    frontend_src.mkdir(parents=True)

    (backend_users / "views.py").write_text(
        """
from .models import SessionToken

SESSION_TOKEN_COOKIE_NAME = "session_token"

def login(request):
    token_value = request.COOKIES.get(SESSION_TOKEN_COOKIE_NAME)
    return token_value

def me(request):
    session = SessionToken.objects.get(token="x")
    return session
""",
        encoding="utf-8",
    )
    (backend_shop / "urls.py").write_text(
        """
urlpatterns = [
    path("api/users/", include("users.urls")),
]
""",
        encoding="utf-8",
    )
    (frontend_src / "App.jsx").write_text("export default function App(){ return <Chatbot /> }", encoding="utf-8")

    analysis = analyze_site(site_root)

    assert analysis["framework"]["backend"] == "django"
    assert analysis["framework"]["frontend"] == "react"
    assert analysis["auth"]["auth_style"] == "session_cookie"
    assert "session_token" in analysis["auth"]["signals"]
    assert "request.COOKIES" in analysis["auth"]["signals"]


def test_analyze_site_detects_flask_session_and_blueprint_prefixes(tmp_path: Path):
    site_root = tmp_path / "bilyeo"
    backend_root = site_root / "backend"
    routes_root = backend_root / "routes"
    frontend_src = site_root / "frontend" / "src"

    routes_root.mkdir(parents=True)
    frontend_src.mkdir(parents=True)

    (backend_root / "app.py").write_text(
        """
from flask import Flask
from routes.auth import auth_bp
from routes.order import order_bp

def create_app():
    app = Flask(__name__)
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(order_bp, url_prefix="/api/orders")
    return app
""",
        encoding="utf-8",
    )
    (routes_root / "auth.py").write_text(
        """
from flask import Blueprint, session

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["POST"])
def login():
    session["user_id"] = 1
    return {}
""",
        encoding="utf-8",
    )
    (frontend_src / "App.vue").write_text("<template><ChatBot /></template>", encoding="utf-8")

    analysis = analyze_site(site_root)

    assert analysis["framework"]["backend"] == "flask"
    assert analysis["framework"]["frontend"] == "vue"
    assert analysis["auth"]["auth_style"] == "session"
    assert "session[" in "".join(analysis["auth"]["signals"])
    assert analysis["backend_entrypoints"] == ["backend/app.py"]
    assert analysis["route_prefixes"] == ["/api/auth", "/api/orders"]


def test_analyze_site_detects_fastapi_cookie_token_signals(tmp_path: Path):
    site_root = tmp_path / "ecommerce"
    backend_router = site_root / "backend" / "app" / "router" / "users"
    backend_app = site_root / "backend" / "app"

    backend_router.mkdir(parents=True)
    backend_app.mkdir(parents=True, exist_ok=True)

    (backend_app / "main.py").write_text(
        """
from fastapi import FastAPI
from ecommerce.backend.app.router.users.router import router as users_router

app = FastAPI()
app.include_router(users_router, prefix="/users")
""",
        encoding="utf-8",
    )
    (backend_router / "router.py").write_text(
        """
from fastapi import APIRouter, Request, Response

router = APIRouter()

@router.post("/login")
def login(request: Request, response: Response):
    access_token = "token"
    response.set_cookie(key="access_token", value=access_token)
    return {}

@router.get("/me")
def me(request: Request):
    token = request.cookies.get("access_token")
    return {"token": token}
""",
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)

    assert analysis["framework"]["backend"] == "fastapi"
    assert analysis["auth"]["auth_style"] == "token_cookie"
    assert "access_token" in analysis["auth"]["signals"]
    assert "response.set_cookie" in analysis["auth"]["signals"]
    assert analysis["backend_entrypoints"] == ["backend/app/main.py"]
