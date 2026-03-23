import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from chatbot.src.onboarding.overlay_generator import generate_overlay_scaffold


def test_generate_overlay_scaffold_creates_bundle_structure_and_report(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "food-run-001",
        "site": "food",
        "source_root": "/workspace/food",
        "created_at": "2026-03-15T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/users/views.py:login"],
                "me_entrypoints": ["backend/users/views.py:me"],
            },
            "product_api": ["/api/products/"],
            "order_api": ["/api/orders/"],
            "frontend_mount_points": ["frontend/src/App.js"],
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    assert (run_root / "files").is_dir()
    assert (run_root / "patches").is_dir()
    assert (run_root / "reports").is_dir()

    plan_path = run_root / "reports" / "generation-plan.json"
    assert plan_path.exists()

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "chat_auth_endpoint" in plan["recommended_outputs"]
    assert "frontend_widget_mount_patch" in plan["recommended_outputs"]
    assert plan["detected"]["auth"]["login_entrypoints"] == ["backend/users/views.py:login"]

    refreshed_manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    smoke_steps = refreshed_manifest["tests"]["smoke"]
    assert len(smoke_steps) == 7
    ids = [step["id"] for step in smoke_steps]
    assert ids == ["chat-auth-token-unauthenticated", "login", "chat-auth-token", "widget-bundle", "chat-stream", "product-api", "order-api"]
    widget_bundle_step = next(step for step in smoke_steps if step["id"] == "widget-bundle")
    chat_stream_step = next(step for step in smoke_steps if step["id"] == "chat-stream")
    assert widget_bundle_step["expects"]["body_contains"] == ["order-cs-widget"]
    assert chat_stream_step["body"] == {
        "message": "주문 상태를 확인해줘",
        "access_token": "{{chat_auth.access_token}}",
        "site_id": "{{chat_auth.site_id}}",
    }
    assert chat_stream_step["expects"]["header_contains"] == {"content-type": "text/event-stream"}
    assert chat_stream_step["expects"]["body_contains"] == ["data:"]
    for step in smoke_steps:
        assert step["kind"] == "http"
        assert step["method"] in {"GET", "POST"}
        assert "url" in step
        assert "expects" in step
        assert isinstance(step["expects"], dict)


def test_generate_overlay_scaffold_uses_strategy_aware_login_route_for_flask(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-001"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "bilyeo-run-001",
        "site": "bilyeo",
        "source_root": "/workspace/bilyeo",
        "created_at": "2026-03-15T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "backend_strategy": "flask",
            "route_prefixes": ["/api/auth", "/api/orders"],
            "product_api": ["/products"],
            "order_api": ["/api/orders"],
            "frontend_mount_points": ["frontend/src/App.vue"],
        },
        "generated_files": [],
        "patch_targets": [],
        "frontend_artifacts": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    smoke_steps = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))["tests"]["smoke"]
    login_step = next(step for step in smoke_steps if step["id"] == "login")
    order_step = next(step for step in smoke_steps if step["id"] == "order-api")

    assert login_step["url"] == "http://127.0.0.1:8000/api/auth/login"
    assert order_step["url"] == "http://127.0.0.1:8000/api/orders"


def test_generate_overlay_scaffold_recommends_mount_patch_for_frontend_mount_targets(tmp_path: Path):
    run_root = tmp_path / "generated" / "shop" / "shop-run-vue"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "shop-run-vue",
        "site": "shop",
        "source_root": "/workspace/shop",
        "created_at": "2026-03-21T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "frontend_strategy": "vue",
            "frontend_mount_targets": ["frontend/src/App.vue"],
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    plan = json.loads((run_root / "reports" / "generation-plan.json").read_text(encoding="utf-8"))
    assert "frontend_widget_mount_patch" in plan["recommended_outputs"]


def test_generate_overlay_scaffold_uses_session_native_auth_chain_for_django(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-session"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "food-run-session",
        "site": "food",
        "source_root": "/workspace/food",
        "created_at": "2026-03-18T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/users/views.py:login"],
                "me_entrypoints": ["backend/users/views.py:me"],
                "auth_style": "session_cookie",
                "login_fields": ["email", "password"],
                "login_route": "/api/users/login/",
                "me_route": "/api/users/me/",
                "logout_route": "/api/users/logout/",
                "route_source": "django_urlpatterns",
                "session_check_shape": {"mode": "authenticated_user"},
            },
            "backend_strategy": "django",
            "product_api": ["/api/products/"],
            "product_api_shape": {"mode": "root_array"},
            "order_api": ["/api/orders/"],
            "order_api_shape": {"mode": "root_array"},
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    smoke_steps = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))["tests"]["smoke"]
    ids = [step["id"] for step in smoke_steps]
    login_step = next(step for step in smoke_steps if step["id"] == "login")
    me_step = next(step for step in smoke_steps if step["id"] == "session-me")
    product_step = next(step for step in smoke_steps if step["id"] == "product-api")

    assert ids == [
        "chat-auth-token-unauthenticated",
        "login",
        "session-me",
        "chat-auth-token",
        "widget-bundle",
        "chat-stream",
        "product-api",
        "order-api",
    ]
    chat_auth_unauth_step = next(step for step in smoke_steps if step["id"] == "chat-auth-token-unauthenticated")
    chat_auth_step = next(step for step in smoke_steps if step["id"] == "chat-auth-token")
    widget_bundle_step = next(step for step in smoke_steps if step["id"] == "widget-bundle")
    chat_stream_step = next(step for step in smoke_steps if step["id"] == "chat-stream")
    assert login_step["url"] == "http://127.0.0.1:8000/api/users/login/"
    assert login_step["body"] == {"email": "{{probe.credentials.email}}", "password": "{{probe.credentials.password}}"}
    assert login_step["uses"] == ["probe.credentials.email", "probe.credentials.password"]
    assert login_step["exports"]["login.cookies"] == "headers['set-cookie']"
    assert chat_auth_unauth_step["expects"]["status"] == 401
    assert chat_auth_step["expects"]["status"] == 200
    assert chat_auth_step["expects"]["json_path_equals"] == {"authenticated": True}
    assert chat_auth_step["exports"]["chat_auth.site_id"] == "json.site_id"
    assert widget_bundle_step["url"] == "http://127.0.0.1:8000/widget.js"
    assert widget_bundle_step["expects"]["header_contains"] == {"content-type": "javascript"}
    assert widget_bundle_step["expects"]["body_contains"] == ["order-cs-widget"]
    assert chat_stream_step["url"] == "http://127.0.0.1:8000/api/v1/chat/stream"
    assert chat_stream_step["body"] == {
        "message": "주문 상태를 확인해줘",
        "access_token": "{{chat_auth.access_token}}",
        "site_id": "{{chat_auth.site_id}}",
    }
    assert chat_stream_step["expects"]["header_contains"] == {"content-type": "text/event-stream"}
    assert chat_stream_step["expects"]["body_contains"] == ["data:"]
    assert chat_stream_step["uses"] == ["chat_auth.access_token", "chat_auth.site_id"]
    assert me_step["url"] == "http://127.0.0.1:8000/api/users/me/"
    assert me_step["headers"]["Cookie"] == "{{login.cookies}}"
    assert me_step["expects"]["json_path_equals"] == {"authenticated": True}
    assert product_step["headers"]["Cookie"] == "{{login.cookies}}"
    assert product_step["expects"]["json_type"] == "list"
    assert product_step["exports"]["product.first_item"] == "json[0]"


def test_generate_overlay_scaffold_uses_session_native_auth_chain_for_flask_wrapper_shapes(tmp_path: Path):
    run_root = tmp_path / "generated" / "bilyeo" / "bilyeo-run-session"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "bilyeo-run-session",
        "site": "bilyeo",
        "source_root": "/workspace/bilyeo",
        "created_at": "2026-03-18T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/routes/auth.py:login"],
                "me_entrypoints": [],
                "auth_style": "session",
                "login_fields": ["email", "password"],
                "login_route": "/api/auth/login/",
                "me_route": None,
                "logout_route": "/api/auth/logout/",
                "route_source": "flask_blueprint_routes",
                "session_check_shape": {"mode": "login_response_user"},
            },
            "backend_strategy": "flask",
            "product_api": ["/api/products/"],
            "product_api_shape": {"mode": "object_array", "key": "products"},
            "order_api": ["/api/orders/"],
            "order_api_shape": {"mode": "object_array", "key": "orders"},
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    smoke_steps = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))["tests"]["smoke"]
    ids = [step["id"] for step in smoke_steps]
    login_step = next(step for step in smoke_steps if step["id"] == "login")
    chat_stream_step = next(step for step in smoke_steps if step["id"] == "chat-stream")
    product_step = next(step for step in smoke_steps if step["id"] == "product-api")
    order_step = next(step for step in smoke_steps if step["id"] == "order-api")

    assert ids == ["chat-auth-token-unauthenticated", "login", "chat-auth-token", "widget-bundle", "chat-stream", "product-api", "order-api"]
    assert login_step["url"] == "http://127.0.0.1:8000/api/auth/login/"
    assert login_step["body"] == {"email": "{{probe.credentials.email}}", "password": "{{probe.credentials.password}}"}
    assert login_step["expects"]["json_keys"] == ["user"]
    assert next(step for step in smoke_steps if step["id"] == "widget-bundle")["expects"]["body_contains"] == ["order-cs-widget"]
    assert chat_stream_step["body"]["site_id"] == "{{chat_auth.site_id}}"
    assert chat_stream_step["expects"]["body_contains"] == ["data:"]
    assert product_step["expects"]["json_keys"] == ["products"]
    assert product_step["exports"]["product.first_item"] == "json.products[0]"
    assert order_step["expects"]["json_keys"] == ["orders"]
    assert order_step["exports"]["order.first_order"] == "json.orders[0]"


def test_generate_overlay_scaffold_marks_missing_login_route_without_guessing(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-missing-auth"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "food-run-missing-auth",
        "site": "food",
        "source_root": "/workspace/food",
        "created_at": "2026-03-18T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/users/views.py:login"],
                "me_entrypoints": [],
                "auth_style": "session_cookie",
                "login_route": None,
                "me_route": None,
                "logout_route": None,
                "route_source": None,
            },
            "backend_strategy": "django",
            "product_api": ["/api/products/"],
            "order_api": ["/api/orders/"],
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root)

    smoke_steps = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))["tests"]["smoke"]
    login_step = next(step for step in smoke_steps if step["id"] == "login")

    assert "url" not in login_step
    assert login_step["kind"] == "analysis_error"
    assert "login route" in login_step["error"]


def test_generate_overlay_scaffold_writes_recovered_smoke_plan_artifact(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-001"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "food-run-001",
        "site": "food",
        "source_root": "/workspace/food",
        "created_at": "2026-03-15T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/users/views.py:login"],
                "me_entrypoints": ["backend/users/views.py:me"],
            },
            "product_api": ["/api/products/"],
            "order_api": ["/api/orders/"],
            "frontend_mount_points": ["frontend/src/App.js"],
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    recovery_payload = {
        "classification": "response_schema_mismatch",
        "should_retry": True,
        "proposed_probe_updates": [
            {
                "step_id": "chat-auth-token",
                "merge": {
                    "url": "http://127.0.0.1:8000/api/chat/recovered-auth-token",
                    "headers": {"X-Recovery-Attempt": "1"},
                    "body": {"scope": "recovered"},
                },
            }
        ],
        "proposed_schema_overrides": [
            {
                "step_id": "chat-auth-token",
                "exports": {"chat_auth.access_token": "json.token"},
            }
        ],
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root, recovery_payload=recovery_payload)

    recovered_path = run_root / "reports" / "recovered-smoke-plan.json"
    assert recovered_path.exists()

    recovered_plan = json.loads(recovered_path.read_text(encoding="utf-8"))
    recovered_step = next(step for step in recovered_plan["steps"] if step["id"] == "chat-auth-token")
    assert recovered_step["url"].endswith("/api/chat/recovered-auth-token")
    assert recovered_step["headers"]["X-Recovery-Attempt"] == "1"
    assert recovered_step["body"] == {"scope": "recovered"}
    assert recovered_step["exports"]["chat_auth.access_token"] == "json.token"


def test_generate_overlay_scaffold_applies_recovered_schema_overrides(tmp_path: Path):
    run_root = tmp_path / "generated" / "food" / "food-run-002"
    run_root.mkdir(parents=True)

    manifest = {
        "run_id": "food-run-002",
        "site": "food",
        "source_root": "/workspace/food",
        "created_at": "2026-03-15T12:00:00+09:00",
        "agent_version": "test-v1",
        "analysis": {
            "auth": {
                "login_entrypoints": ["backend/users/views.py:login"],
                "me_entrypoints": ["backend/users/views.py:me"],
            },
            "product_api": ["/api/products/"],
            "order_api": ["/api/orders/"],
        },
        "generated_files": [],
        "patch_targets": [],
        "docker": {},
        "tests": {},
        "status": "generated",
    }
    recovery_payload = {
        "classification": "response_schema_mismatch",
        "should_retry": True,
        "proposed_probe_updates": [],
        "proposed_schema_overrides": [
            {
                "step_id": "chat-auth-token",
                "expects": {"status": 200, "json_keys": ["token"]},
                "exports": {"chat_auth.access_token": "json.token"},
            }
        ],
    }
    (run_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    generate_overlay_scaffold(run_root, recovery_payload=recovery_payload)

    recovered_plan = json.loads((run_root / "reports" / "recovered-smoke-plan.json").read_text(encoding="utf-8"))
    recovered_step = next(step for step in recovered_plan["steps"] if step["id"] == "chat-auth-token")
    assert recovered_step["expects"]["json_keys"] == ["token"]
    assert recovered_step["exports"]["chat_auth.access_token"] == "json.token"
