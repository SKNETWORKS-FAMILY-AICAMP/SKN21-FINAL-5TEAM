from typing import Dict

from chatbot.src.onboarding_v2.models.planning import ResolvedAuthContract

from ..auth_headers import assert_context_site, build_auth_headers_from_contract
from ..schema import AuthenticatedContext

SITE_ID = "site-a"
AUTH_CONTRACT = ResolvedAuthContract(
    transport="session_cookie",
    session_cookie_name="session_token",
)

def assert_site_a_context(ctx: AuthenticatedContext) -> None:
    assert_context_site(ctx, expected_site_id=SITE_ID, label=SITE_ID)


def build_site_a_auth_headers(ctx: AuthenticatedContext) -> Dict[str, str]:
    return build_auth_headers_from_contract(AUTH_CONTRACT, ctx)
