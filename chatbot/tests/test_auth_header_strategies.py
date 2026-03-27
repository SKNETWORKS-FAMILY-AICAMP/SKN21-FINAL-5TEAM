from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatbot.src.adapters.schema import AuthenticatedContext, AdapterError
from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract


def test_shared_auth_headers_build_bearer_with_optional_cookie() -> None:
    from chatbot.src.adapters.auth_headers import build_auth_headers_from_contract

    headers = build_auth_headers_from_contract(
        ResolvedAuthContract(transport="bearer_token"),
        AuthenticatedContext(
            siteId="site-b",
            userId="1",
            accessToken="bearer-123",
            cookies={"session_token": "cookie-1"},
        ),
    )

    assert headers["Authorization"] == "Bearer bearer-123"
    assert headers["Cookie"] == "session_token=cookie-1"


def test_shared_auth_headers_preserve_real_cookie_over_access_token() -> None:
    from chatbot.src.adapters.auth_headers import build_auth_headers_from_contract

    headers = build_auth_headers_from_contract(
        ResolvedAuthContract(
            transport="session_cookie",
            session_cookie_name="session_token",
        ),
        AuthenticatedContext(
            siteId="site-a",
            userId="1",
            accessToken="synthetic-token",
            cookies={"session_token": "real-cookie"},
        ),
    )

    assert headers["Cookie"] == "session_token=real-cookie"
    assert "synthetic-token" not in headers["Cookie"]


def test_shared_auth_headers_emit_cookie_plus_csrf_headers() -> None:
    from chatbot.src.adapters.auth_headers import build_auth_headers_from_contract

    headers = build_auth_headers_from_contract(
        ResolvedAuthContract(
            transport="cookie_plus_csrf",
            session_cookie_name="sessionid",
            csrf_cookie_name="csrftoken",
            csrf_header_name="X-CSRFToken",
        ),
        AuthenticatedContext(
            siteId="csrf-shop",
            userId="1",
            cookies={"sessionid": "real-session", "csrftoken": "cookie-csrf"},
            metadata={"csrf_token": "metadata-csrf"},
        ),
    )

    assert headers["Cookie"] == "sessionid=real-session; csrftoken=cookie-csrf"
    assert headers["X-CSRFToken"] == "metadata-csrf"


def test_shared_auth_headers_reject_malformed_cookie_contract() -> None:
    from chatbot.src.adapters.auth_headers import build_auth_headers_from_contract

    with pytest.raises(ValueError, match="session_cookie_name"):
        build_auth_headers_from_contract(
            ResolvedAuthContract(transport="session_cookie"),
            AuthenticatedContext(siteId="site-a", userId="1"),
        )


def test_shared_assert_context_site_uses_adapter_error() -> None:
    from chatbot.src.adapters.auth_headers import assert_context_site

    with pytest.raises(AdapterError) as exc_info:
        assert_context_site(
            AuthenticatedContext(siteId="wrong-site", userId="1"),
            expected_site_id="site-a",
            label="site-a",
        )

    assert exc_info.value.code == "INVALID_INPUT"
