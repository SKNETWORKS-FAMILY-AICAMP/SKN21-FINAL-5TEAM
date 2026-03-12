import { AuthenticatedContext } from "../../domain/ecommerce";
import { AdapterError } from "../../domain/errors";

export function assertSiteCContext(ctx: AuthenticatedContext) {
  if (ctx.siteId !== "site-a") {
    throw new AdapterError("INVALID_INPUT", "site-a 컨텍스트가 아닙니다.", {
      siteId: ctx.siteId
    });
  }
}

export function buildSiteCAuthHeaders(ctx: AuthenticatedContext): Record<string, string> {
  const headers: Record<string, string> = {};

  const cookieMap = {
    ...(ctx.cookies ?? {}),
    ...(ctx.accessToken ? { access_token: ctx.accessToken } : {}),
    ...(ctx.sessionRef ? { access_token: ctx.sessionRef } : {})
  };

  if (Object.keys(cookieMap).length > 0) {
    headers.Cookie = Object.entries(cookieMap)
      .map(([k, v]) => `${k}=${v}`)
      .join("; ");
  }

  return headers;
}
