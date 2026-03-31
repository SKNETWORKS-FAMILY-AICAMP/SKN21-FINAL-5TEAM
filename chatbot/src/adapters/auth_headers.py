from __future__ import annotations

from typing import Callable

from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract

from .schema import AuthenticatedContext, AdapterError


def assert_context_site(
    ctx: AuthenticatedContext,
    *,
    expected_site_id: str,
    label: str,
) -> None:
    if ctx.siteId != expected_site_id:
        raise AdapterError(
            "INVALID_INPUT",
            f"{label} 콘텍스트가 아닙니다.",
            {"siteId": ctx.siteId},
        )


def build_auth_headers_from_contract(
    auth_contract: ResolvedAuthContract,
    ctx: AuthenticatedContext,
) -> dict[str, str]:
    builder = _HEADER_BUILDERS.get(auth_contract.transport)
    if builder is None:
        raise ValueError(f"unsupported auth transport: {auth_contract.transport}")
    return builder(auth_contract, ctx)


def _build_bearer_headers(
    auth_contract: ResolvedAuthContract,
    ctx: AuthenticatedContext,
) -> dict[str, str]:
    del auth_contract
    headers: dict[str, str] = {}
    bearer_token = _resolve_token_fallback(ctx)
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    cookie_header = _serialize_cookie_header(dict(ctx.cookies or {}))
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _build_session_cookie_headers(
    auth_contract: ResolvedAuthContract,
    ctx: AuthenticatedContext,
) -> dict[str, str]:
    cookie_map = _build_cookie_map(auth_contract, ctx)
    cookie_header = _serialize_cookie_header(cookie_map)
    return {"Cookie": cookie_header} if cookie_header else {}


def _build_cookie_plus_csrf_headers(
    auth_contract: ResolvedAuthContract,
    ctx: AuthenticatedContext,
) -> dict[str, str]:
    csrf_cookie_name = str(auth_contract.csrf_cookie_name or "").strip()
    csrf_header_name = str(auth_contract.csrf_header_name or "").strip()
    if not csrf_cookie_name:
        raise ValueError("cookie_plus_csrf transport requires csrf_cookie_name")
    if not csrf_header_name:
        raise ValueError("cookie_plus_csrf transport requires csrf_header_name")

    cookie_map = _build_cookie_map(auth_contract, ctx)
    headers: dict[str, str] = {}
    cookie_header = _serialize_cookie_header(cookie_map)
    if cookie_header:
        headers["Cookie"] = cookie_header

    metadata = ctx.metadata or {}
    csrf_token = str(
        metadata.get("csrf_token") or cookie_map.get(csrf_cookie_name) or ""
    ).strip()
    if csrf_token:
        headers[csrf_header_name] = csrf_token
    return headers


def _build_cookie_map(
    auth_contract: ResolvedAuthContract,
    ctx: AuthenticatedContext,
) -> dict[str, str]:
    session_cookie_name = str(auth_contract.session_cookie_name or "").strip()
    if not session_cookie_name:
        raise ValueError(
            f"{auth_contract.transport} transport requires session_cookie_name"
        )
    cookie_map = dict(ctx.cookies or {})
    if session_cookie_name not in cookie_map:
        fallback = _resolve_token_fallback(ctx)
        if fallback:
            cookie_map[session_cookie_name] = fallback
    return cookie_map


def _resolve_token_fallback(ctx: AuthenticatedContext) -> str:
    return str(ctx.accessToken or ctx.sessionRef or "").strip()


def _serialize_cookie_header(cookie_map: dict[str, str]) -> str:
    if not cookie_map:
        return ""
    return "; ".join(f"{key}={value}" for key, value in cookie_map.items())


_HEADER_BUILDERS: dict[
    str, Callable[[ResolvedAuthContract, AuthenticatedContext], dict[str, str]]
] = {
    "bearer_token": _build_bearer_headers,
    "session_cookie": _build_session_cookie_headers,
    "cookie_plus_csrf": _build_cookie_plus_csrf_headers,
}
