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


def test_analyze_site_ignores_frontend_build_artifacts_for_mount_contract(tmp_path: Path):
    site_root = tmp_path / "food"
    frontend_src = site_root / "frontend" / "src"
    frontend_build = site_root / "frontend" / "build" / "static" / "js"

    frontend_src.mkdir(parents=True)
    frontend_build.mkdir(parents=True)

    (frontend_src / "App.js").write_text(
        """
export default function App() {
  return <Chatbot />;
}
""",
        encoding="utf-8",
    )
    (frontend_build / "main.76c8743f.js").write_text(
        'function App(){return React.createElement("div", null, "Chatbot")}\n',
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)

    assert analysis["frontend_mount_points"] == ["frontend/src/App.js"]
    assert analysis["integration_contract"]["frontend"]["app_shell_path"] == "frontend/src/App.js"
    assert analysis["integration_contract"]["frontend"]["widget_mount_points"] == ["frontend/src/App.js"]


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
    data = json.loads(request.body.decode())
    email = data.get("email")
    password = data.get("password")
    token_value = request.COOKIES.get(SESSION_TOKEN_COOKIE_NAME)
    return email or password or token_value

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
    assert analysis["auth"]["login_route"] == "/api/users/login/"
    assert analysis["auth"]["me_route"] == "/api/users/me/"
    assert analysis["auth"]["logout_route"] is None
    assert analysis["auth"]["login_fields"] == ["email", "password"]
    assert analysis["auth"]["route_source"] == "django_urlpatterns"
    assert "session_token" in analysis["auth"]["signals"]
    assert "request.COOKIES" in analysis["auth"]["signals"]
    assert analysis["backend_strategy"] == "django"
    assert analysis["frontend_strategy"] == "react"
    assert "backend/foodshop/urls.py" in analysis["backend_route_targets"]
    assert "frontend/src/App.jsx" in analysis["frontend_mount_targets"]
    assert "backend/users/views.py" in analysis["tool_registry_targets"]


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
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    session["user_id"] = 1
    return {"user": {"email": email}, "ok": bool(password)}
""",
        encoding="utf-8",
    )
    (frontend_src / "App.vue").write_text("<template><ChatBot /></template>", encoding="utf-8")

    analysis = analyze_site(site_root)

    assert analysis["framework"]["backend"] == "flask"
    assert analysis["framework"]["frontend"] == "vue"
    assert analysis["auth"]["auth_style"] == "session"
    assert analysis["auth"]["login_fields"] == ["email", "password"]
    assert "session[" in "".join(analysis["auth"]["signals"])
    assert analysis["backend_entrypoints"] == ["backend/app.py"]
    assert analysis["route_prefixes"] == ["/api/auth", "/api/orders"]


def test_analyze_site_detects_flask_login_route_and_response_shapes(tmp_path: Path):
    site_root = tmp_path / "bilyeo"
    backend_root = site_root / "backend"
    routes_root = backend_root / "routes"

    routes_root.mkdir(parents=True)

    (backend_root / "app.py").write_text(
        """
from flask import Flask
from routes.auth import auth_bp
from routes.product import product_bp
from routes.order import order_bp

app = Flask(__name__)
app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(product_bp, url_prefix="/api/products")
app.register_blueprint(order_bp, url_prefix="/api/orders")
""",
        encoding="utf-8",
    )
    (routes_root / "auth.py").write_text(
        """
from flask import Blueprint, request, jsonify, session
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")
    session["user_id"] = 1
    return jsonify({"message": "ok", "user": {"email": email}, "ok": bool(password)})
""",
        encoding="utf-8",
    )
    (routes_root / "product.py").write_text(
        """
from flask import Blueprint, jsonify
product_bp = Blueprint("product", __name__)

@product_bp.route("", methods=["GET"])
def list_products():
    return jsonify({"products": [{"id": 1}]})
""",
        encoding="utf-8",
    )
    (routes_root / "order.py").write_text(
        """
from flask import Blueprint, jsonify
order_bp = Blueprint("order", __name__)

@order_bp.route("", methods=["GET"])
def list_orders():
    return jsonify({"orders": [{"id": 1}]})
""",
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)

    assert analysis["auth"]["login_route"] == "/api/auth/login/"
    assert analysis["auth"]["session_check_shape"] == {"mode": "login_response_user"}
    assert analysis["product_api_shape"] == {"mode": "object_array", "key": "products"}
    assert analysis["order_api_shape"] == {"mode": "object_array", "key": "orders"}


def test_analyze_site_emits_food_integration_contract(tmp_path: Path):
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

def login(request):
    token = request.COOKIES.get("session_token")
    return token

def me(request):
    session = SessionToken.objects.select_related("user").first()
    return session
""",
        encoding="utf-8",
    )
    (backend_shop / "urls.py").write_text(
        """
from django.urls import include, path

urlpatterns = [
    path("api/users/", include("users.urls")),
    path("api/products/", include("products.urls")),
    path("api/orders/", include("orders.urls")),
]
""",
        encoding="utf-8",
    )
    (frontend_src / "App.js").write_text(
        """
export default function App() {
  return <main><Chatbot /></main>;
}
""",
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)
    contract = analysis["integration_contract"]

    assert contract["site"] == "food"
    assert contract["backend"]["framework"] == "django"
    assert contract["backend"]["auth_style"] == "session_cookie"
    assert contract["backend"]["route_registration_points"] == ["backend/foodshop/urls.py"]
    assert contract["frontend"]["framework"] == "react"
    assert contract["frontend"]["app_shell_path"] == "frontend/src/App.js"
    assert contract["frontend"]["widget_mount_points"] == ["frontend/src/App.js"]
    assert contract["chat_auth"]["endpoint_path"] == "/api/chat/auth-token"
    assert contract["product_adapter"]["api_base_paths"] == ["/api/products/"]
    assert contract["order_adapter"]["api_base_paths"] == ["/api/orders/"]


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
    assert analysis["backend_strategy"] == "fastapi"
    assert "backend/app/main.py" in analysis["backend_route_targets"]


def test_analyze_site_ignores_site_packages_auth_entrypoints(tmp_path: Path):
    site_root = tmp_path / "food"
    backend_users = site_root / "backend" / "users"
    backend_shop = site_root / "backend" / "foodshop"
    backend_venv_auth = site_root / "backend" / ".venv" / "lib" / "python3.13" / "site-packages" / "django" / "contrib" / "auth"

    backend_users.mkdir(parents=True)
    backend_shop.mkdir(parents=True)
    backend_venv_auth.mkdir(parents=True)

    (backend_users / "views.py").write_text(
        """
def login(request):
    return None

def me(request):
    return None
""",
        encoding="utf-8",
    )
    (backend_users / "urls.py").write_text(
        """
from . import views

urlpatterns = [
    path("login/", views.login),
    path("me/", views.me),
]
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
    (backend_venv_auth / "__init__.py").write_text(
        """
def login(request):
    return None
""",
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)

    assert analysis["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]
    assert analysis["auth"]["login_route"] == "/api/users/login/"


def test_analyze_site_does_not_fabricate_django_login_route_when_missing(tmp_path: Path):
    site_root = tmp_path / "food"
    backend_users = site_root / "backend" / "users"
    backend_shop = site_root / "backend" / "foodshop"

    backend_users.mkdir(parents=True)
    backend_shop.mkdir(parents=True)

    (backend_users / "views.py").write_text(
        """
def login(request):
    return None
""",
        encoding="utf-8",
    )
    (backend_shop / "urls.py").write_text(
        """
urlpatterns = [
    path("api/products/", include("products.urls")),
]
""",
        encoding="utf-8",
    )

    analysis = analyze_site(site_root)

    assert analysis["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]
    assert analysis["auth"]["login_route"] is None
    assert analysis["auth"]["me_route"] is None


def test_analyze_site_emits_strategy_targets_for_flask_and_vue(tmp_path: Path):
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

app = Flask(__name__)
app.register_blueprint(auth_bp, url_prefix="/api/auth")
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

    assert analysis["backend_strategy"] == "flask"
    assert analysis["frontend_strategy"] == "vue"
    assert "backend/app.py" in analysis["backend_route_targets"]
    assert "frontend/src/App.vue" in analysis["frontend_mount_targets"]
    assert "backend/routes/auth.py" in analysis["tool_registry_targets"]
