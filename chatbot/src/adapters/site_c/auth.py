from typing import Dict
from ..schema import AuthenticatedContext, AdapterError

def assert_site_c_context(ctx: AuthenticatedContext) -> None:
    if ctx.siteId != "site-c":
        raise AdapterError("INVALID_INPUT", "site-c 콘텍스트가 아닙니다.", {"siteId": ctx.siteId})

def build_site_c_auth_headers(ctx: AuthenticatedContext) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    cookie_map = ctx.cookies.copy() if ctx.cookies else {}
    
    if ctx.accessToken:
        cookie_map["access_token"] = ctx.accessToken
    elif ctx.sessionRef:
        cookie_map["access_token"] = ctx.sessionRef
        
    if cookie_map:
        headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in cookie_map.items()])

    return headers
