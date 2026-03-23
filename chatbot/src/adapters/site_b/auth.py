from typing import Dict
from ..schema import AuthenticatedContext, AdapterError


def assert_site_b_context(ctx: AuthenticatedContext) -> None:
    if ctx.siteId != "site-b":
        raise AdapterError(
            "INVALID_INPUT", "site-b 콘텍스트가 아닙니다.", {"siteId": ctx.siteId}
        )


def build_site_b_auth_headers(ctx: AuthenticatedContext) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if ctx.accessToken:
        headers["Authorization"] = f"Bearer {ctx.accessToken}"
    elif ctx.sessionRef:
        headers["Authorization"] = f"Bearer {ctx.sessionRef}"
    return headers
