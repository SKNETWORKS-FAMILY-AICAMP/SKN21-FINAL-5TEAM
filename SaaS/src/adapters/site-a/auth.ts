import { AuthenticatedContext } from "../../domain/ecommerce";
import { AdapterError } from "../../domain/errors";

export function assertSiteAContext(ctx: AuthenticatedContext) {
  if (ctx.siteId !== "site-b") {
    throw new AdapterError("INVALID_INPUT", "site-b 컨텍스트가 아닙니다.", {
      siteId: ctx.siteId
    });
  }
}

export function buildSiteAAuthHeaders(ctx: AuthenticatedContext): Record<string, string> {
  const headers: Record<string, string> = {};

  const cookieMap = {
    ...(ctx.cookies ?? {}),
    ...(ctx.accessToken ? { session_token: ctx.accessToken } : {})
  };

  if (Object.keys(cookieMap).length > 0) {
    headers.Cookie = Object.entries(cookieMap)
      .map(([k, v]) => `${k}=${v}`)
      .join("; ");
  }

  return headers;
}
