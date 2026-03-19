from __future__ import annotations


def test_build_onboarding_event_store_returns_none_without_url() -> None:
    from chatbot.src.onboarding.redis_runtime import build_onboarding_event_store

    store = build_onboarding_event_store(redis_url="")

    assert store is None


def test_build_onboarding_event_store_builds_store_with_factory() -> None:
    from chatbot.src.onboarding.redis_runtime import build_onboarding_event_store

    captured: dict[str, str] = {}

    class _FakeRedis:
        pass

    def factory(url: str):
        captured["url"] = url
        return _FakeRedis()

    store = build_onboarding_event_store(
        redis_url="redis://localhost:6379/0",
        client_factory=factory,
    )

    assert store is not None
    assert captured["url"] == "redis://localhost:6379/0"
    assert store.redis_client.__class__.__name__ == "_FakeRedis"
