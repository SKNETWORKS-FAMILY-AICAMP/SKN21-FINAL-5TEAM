import { AuthenticatedContext } from "../../domain/ecommerce";
import { AdapterError } from "../../domain/errors";

export function assertSiteBContext(ctx: AuthenticatedContext) {
  if (ctx.siteId !== "site-c") {
    throw new AdapterError("INVALID_INPUT", "site-c 컨텍스트가 아닙니다.", {
      siteId: ctx.siteId
    });
  }
}

export function buildSiteBAuthHeaders(ctx: AuthenticatedContext): Record<string, string> {
  const headers: Record<string, string> = {};

  if (ctx.accessToken) {
    headers.Authorization = `Bearer ${ctx.accessToken}`;
  } else if (ctx.sessionRef) {
    headers.Authorization = `Bearer ${ctx.sessionRef}`;
  }

  return headers;
}
