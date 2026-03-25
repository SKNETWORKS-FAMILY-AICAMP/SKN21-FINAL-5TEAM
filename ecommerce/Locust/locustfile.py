import os
import random
import time
from typing import Any

from locust import HttpUser, LoadTestShape, between, task


# Run guide (PowerShell)
# 1) Seed test data/users:
#    uv run python ecommerce/scripts/seed.py
# 2) Start backend (separate terminal):
#    uv run python -m ecommerce.backend.app.main
# 3) Run locust (UI):
#    uv run locust -f Locust/locustfile.py
# 4) Run locust (headless):
#    uv run locust -f Locust/locustfile.py --headless --run-time 5m
# 5) Optional env:
#    $env:LOCUST_TEST_PASSWORD="locust1234"
#    $env:LOCUST_HOST="https://moyeo.kro.kr"
#    $env:LOCUST_RELOGIN_INTERVAL_SECONDS="60"

LOCUST_HOST = os.getenv("LOCUST_HOST", "https://moyeo.kro.kr")
AUTH_TOKEN = os.getenv("LOCUST_AUTH_TOKEN", "").strip()
LOCUST_TEST_PASSWORD = os.getenv("LOCUST_TEST_PASSWORD", "locust1234")
MIN_USER_ID = int(os.getenv("LOCUST_MIN_USER_ID", "1"))
MAX_USER_ID = int(os.getenv("LOCUST_MAX_USER_ID", "100"))
SEARCH_KEYWORDS = ["shirt", "pants", "shoes", "jacket", "bag"]
CHAT_MESSAGES = [
    "Recommend spring jackets",
    "What is your return policy?",
    "How long does shipping take?",
    "Show today's sale items",
]

WAVE_USERS = int(os.getenv("LOCUST_WAVE_USERS", "100"))
WAVE_SPAWN_RATE = float(os.getenv("LOCUST_WAVE_SPAWN_RATE", "20"))
WAVE_HOLD_SECONDS = int(os.getenv("LOCUST_WAVE_HOLD_SECONDS", "180"))
WAVE_IDLE_SECONDS = int(os.getenv("LOCUST_WAVE_IDLE_SECONDS", "0"))
RELOGIN_INTERVAL_SECONDS = int(os.getenv("LOCUST_RELOGIN_INTERVAL_SECONDS", "0"))
ENABLE_CHATBOT = os.getenv("LOCUST_ENABLE_CHATBOT", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class BaseScenarioUser(HttpUser):
    abstract = True

    if LOCUST_HOST:
        host = LOCUST_HOST

    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.user_id = random.randint(MIN_USER_ID, MAX_USER_ID)
        self.authenticated = False
        self.last_login_at = 0.0

        if AUTH_TOKEN:
            self.client.headers.update({"Authorization": f"Bearer {AUTH_TOKEN}"})
            self.authenticated = True
            self.last_login_at = time.time()

        self.client.headers.update({"Accept": "application/json"})
        self.client.get("/", name="GET /")

        if not self.authenticated:
            self._login()

    @staticmethod
    def _json_or_none(response) -> Any | None:
        try:
            return response.json()
        except ValueError:
            return None

    def _login(self) -> None:
        email = f"locust_user_{self.user_id:03d}@example.com"
        with self.client.post(
            "/users/login",
            json={"email": email, "password": LOCUST_TEST_PASSWORD},
            name="POST /users/login",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.authenticated = True
                self.last_login_at = time.time()
                response.success()
            else:
                self.authenticated = False
                response.failure(f"login failed: {response.status_code}")

    def _ensure_login(self) -> bool:
        if self.authenticated and RELOGIN_INTERVAL_SECONDS > 0:
            if time.time() - self.last_login_at >= RELOGIN_INTERVAL_SECONDS:
                self._login()
            return self.authenticated

        if self.authenticated:
            return True

        self._login()
        return self.authenticated


class PurchaseFlowUser(BaseScenarioUser):
    weight = 34

    @task
    def purchase_smoke(self) -> None:
        if not self._ensure_login():
            return

        products_res = self.client.get("/products/new?limit=20", name="GET /products/new")
        products = self._json_or_none(products_res)
        if isinstance(products, list) and products:
            target = random.choice(products)
            product_id = target.get("id")
            if isinstance(product_id, int):
                self.client.get(
                    f"/products/new/{product_id}/options",
                    name="GET /products/new/{product_id}/options",
                )

        self.client.get(f"/carts/{self.user_id}/summary", name="GET /carts/{user_id}/summary")
        self.client.get("/orders/orders/health", name="GET /orders/orders/health")


class ProductSearchUser(BaseScenarioUser):
    weight = 33

    @task
    def search_products(self) -> None:
        if not self._ensure_login():
            return

        keyword = random.choice(SEARCH_KEYWORDS)
        self.client.get(
            "/products/new",
            params={"keyword": keyword, "limit": 20},
            name="GET /products/new?keyword",
        )
        self.client.get("/products/categories/menu", name="GET /products/categories/menu")
        self.client.get("/products/health", name="GET /products/health")


class ShippingAddressUser(BaseScenarioUser):
    weight = 33

    @task
    def shipping_smoke(self) -> None:
        if not self._ensure_login():
            return

        self.client.get(f"/shipping?user_id={self.user_id}", name="GET /shipping")
        self.client.get("/inventories/health", name="GET /inventories/health")
        self.client.get(
            f"/user-history/users/{self.user_id}/summary?days=30",
            name="GET /user-history/users/{user_id}/summary",
        )


class ChatbotUser(BaseScenarioUser):
    weight = 0 if not ENABLE_CHATBOT else 10

    @task
    def use_chatbot(self) -> None:
        if not ENABLE_CHATBOT:
            return

        if not self._ensure_login():
            return

        payload = {"message": random.choice(CHAT_MESSAGES)}
        self.client.post(
            "/api/v1/chat/stream",
            json=payload,
            name="POST /api/v1/chat/stream",
            timeout=60,
        )


class RepeatingWaveShape(LoadTestShape):
    """
    Repeating wave:
    - Hold phase: keep WAVE_USERS users for WAVE_HOLD_SECONDS
    - Idle phase: 0 users for WAVE_IDLE_SECONDS
    - Repeat forever

    Note: When LoadTestShape is present, UI Users/SpawnRate values are ignored.
    """

    def tick(self):
        cycle = WAVE_HOLD_SECONDS + WAVE_IDLE_SECONDS
        if cycle <= 0:
            return WAVE_USERS, WAVE_SPAWN_RATE

        elapsed = int(self.get_run_time())
        phase_time = elapsed % cycle

        if phase_time < WAVE_HOLD_SECONDS:
            return WAVE_USERS, WAVE_SPAWN_RATE
        return 0, WAVE_SPAWN_RATE
