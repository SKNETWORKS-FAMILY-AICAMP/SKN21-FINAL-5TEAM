from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from chatbot.src.adapters import setup as adapter_setup
from chatbot.src.adapters.base import AdapterError, BaseEcommerceSupportAdapter
from chatbot.src.adapters.schema import AuthenticatedContext
from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract


@dataclass(frozen=True)
class RuntimeAuthResolution:
    adapter: BaseEcommerceSupportAdapter
    auth_contract: ResolvedAuthContract
    site_id: str
    user_id: str | None
    access_token: str | None
    cookies: dict[str, str]
    auth_metadata: dict[str, Any]
    context: AuthenticatedContext


def _normalize_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _previous_user_info(request: Any) -> dict[str, Any]:
    previous_state = getattr(request, "previous_state", None)
    if not isinstance(previous_state, dict):
        return {}
    user_info = previous_state.get("user_info")
    return dict(user_info) if isinstance(user_info, dict) else {}


def _request_cookies(http_request: Any) -> dict[str, str]:
    cookies = getattr(http_request, "cookies", None)
    if not isinstance(cookies, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in cookies.items()
        if _normalize_text(key) and _normalize_text(value)
    }


def _request_headers(http_request: Any) -> dict[str, str]:
    headers = getattr(http_request, "headers", None)
    if headers is None:
        return {}
    try:
        items = headers.items()
    except Exception:
        if isinstance(headers, dict):
            items = headers.items()
        else:
            return {}
    normalized: dict[str, str] = {}
    for key, value in items:
        key_text = _normalize_text(key)
        value_text = _normalize_text(value)
        if key_text and value_text:
            normalized[key_text] = value_text
    return normalized


def _lookup_header(headers: dict[str, str], header_name: str | None) -> str | None:
    normalized_name = _normalize_text(header_name)
    if not normalized_name:
        return None
    if normalized_name in headers:
        return _normalize_text(headers[normalized_name])
    lower_name = normalized_name.lower()
    for key, value in headers.items():
        if key.lower() == lower_name:
            return _normalize_text(value)
    return None


def _resolve_adapter(site_id: str | None) -> BaseEcommerceSupportAdapter:
    effective_site_id = _normalize_text(site_id)
    if not effective_site_id:
        raise HTTPException(status_code=400, detail="site_id is required")
    try:
        return adapter_setup.resolve_site_adapter(effective_site_id)
    except AdapterError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


def _resolve_adapter_auth_contract(
    adapter: BaseEcommerceSupportAdapter,
) -> ResolvedAuthContract:
    contract = getattr(adapter, "auth_contract", None)
    if isinstance(contract, ResolvedAuthContract):
        return contract
    raise HTTPException(
        status_code=500,
        detail=f"adapter {adapter.site_id} missing auth_contract",
    )


def resolve_runtime_auth(
    *,
    request: Any,
    http_request: Any,
    require_credentials: bool,
) -> RuntimeAuthResolution:
    previous_user_info = _previous_user_info(request)
    http_cookies = _request_cookies(http_request)
    headers = _request_headers(http_request)

    requested_site_id = (
        _normalize_text(getattr(request, "site_id", None))
        or _normalize_text(previous_user_info.get("site_id"))
    )
    adapter = _resolve_adapter(requested_site_id)
    auth_contract = _resolve_adapter_auth_contract(adapter)

    effective_user_id = (
        _normalize_text(getattr(request, "user_id", None))
        or _normalize_text(previous_user_info.get("id"))
        or _normalize_text(previous_user_info.get("user_id"))
    )
    previous_access_token = _normalize_text(previous_user_info.get("access_token"))
    previous_cookies = dict(previous_user_info.get("cookies") or {})
    previous_auth_metadata = dict(previous_user_info.get("auth_metadata") or {})

    access_token: str | None = None
    cookies: dict[str, str] = {}
    auth_metadata: dict[str, Any] = {}

    if auth_contract.transport == "bearer_token":
        access_token = (
            _normalize_text(getattr(request, "access_token", None))
            or previous_access_token
            or _normalize_text(http_cookies.get("access_token"))
        )
        if require_credentials and not access_token:
            raise HTTPException(status_code=401, detail="missing bearer token")

    elif auth_contract.transport == "cookie_plus_csrf":
        session_cookie_name = _normalize_text(auth_contract.session_cookie_name)
        csrf_cookie_name = _normalize_text(auth_contract.csrf_cookie_name)
        csrf_header_name = _normalize_text(auth_contract.csrf_header_name)
        if not session_cookie_name or not csrf_cookie_name or not csrf_header_name:
            raise HTTPException(
                status_code=500,
                detail=f"adapter {adapter.site_id} has incomplete cookie_plus_csrf auth_contract",
            )

        session_cookie = (
            _normalize_text(http_cookies.get(session_cookie_name))
            or _normalize_text(previous_cookies.get(session_cookie_name))
        )
        csrf_cookie_value = (
            _normalize_text(http_cookies.get(csrf_cookie_name))
            or _normalize_text(previous_cookies.get(csrf_cookie_name))
        )
        csrf_token = (
            _lookup_header(headers, csrf_header_name)
            or _normalize_text(previous_auth_metadata.get("csrf_token"))
            or csrf_cookie_value
        )
        access_token = (
            session_cookie
            or _normalize_text(getattr(request, "access_token", None))
            or previous_access_token
        )
        if session_cookie:
            cookies[session_cookie_name] = session_cookie
        if csrf_cookie_value:
            cookies[csrf_cookie_name] = csrf_cookie_value
        if csrf_token:
            auth_metadata["csrf_token"] = csrf_token
            auth_metadata["csrf_header_name"] = csrf_header_name
        if require_credentials and not session_cookie:
            raise HTTPException(
                status_code=401,
                detail=f"missing session cookie {session_cookie_name}",
            )
        if require_credentials and not csrf_token:
            raise HTTPException(
                status_code=401,
                detail=f"missing csrf token {csrf_cookie_name}",
            )

    else:
        session_cookie_name = _normalize_text(auth_contract.session_cookie_name)
        if not session_cookie_name:
            raise HTTPException(
                status_code=500,
                detail=f"adapter {adapter.site_id} missing session_cookie_name",
            )
        session_cookie = (
            _normalize_text(http_cookies.get(session_cookie_name))
            or _normalize_text(previous_cookies.get(session_cookie_name))
        )
        access_token = (
            session_cookie
            or _normalize_text(getattr(request, "access_token", None))
            or previous_access_token
        )
        if session_cookie:
            cookies[session_cookie_name] = session_cookie
        if require_credentials and not session_cookie:
            raise HTTPException(
                status_code=401,
                detail=f"missing session cookie {session_cookie_name}",
            )

    context = AuthenticatedContext(
        siteId=adapter.site_id,
        userId=str(effective_user_id or "__bridge__"),
        accessToken=access_token,
        cookies=cookies or None,
        metadata=auth_metadata or None,
    )
    return RuntimeAuthResolution(
        adapter=adapter,
        auth_contract=auth_contract,
        site_id=adapter.site_id,
        user_id=effective_user_id,
        access_token=access_token,
        cookies=cookies,
        auth_metadata=auth_metadata,
        context=context,
    )


def build_runtime_user_info(
    *,
    previous_user_info: dict[str, Any] | None,
    site_id: str,
    access_token: str | None,
    cookies: dict[str, str] | None,
    auth_metadata: dict[str, Any] | None,
    user_id: Any | None,
    user_name: str | None,
    user_email: str | None,
) -> dict[str, Any]:
    user_info = dict(previous_user_info or {})
    if user_id is not None:
        user_info["id"] = user_id
    if user_name is not None:
        user_info["name"] = user_name
    if user_email is not None:
        user_info["email"] = user_email
    user_info["site_id"] = site_id
    if access_token is not None:
        user_info["access_token"] = access_token
    if cookies:
        user_info["cookies"] = dict(cookies)
    else:
        user_info.pop("cookies", None)
    if auth_metadata:
        user_info["auth_metadata"] = dict(auth_metadata)
    else:
        user_info.pop("auth_metadata", None)
    return user_info
