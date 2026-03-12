import {
  AdapterHealth,
  AuthenticatedContext,
  DeliveryStatus,
  EcommerceSupportAdapter,
  GetDeliveryTrackingInput,
  GetDeliveryTrackingResult,
  GetOrderStatusInput,
  GetOrderStatusResult,
  KnowledgeSearchInput,
  KnowledgeSearchResult,
  OrderStatus,
  ProductSearchFilter,
  ProductSearchResult,
  SubmitOrderActionInput,
  SubmitOrderActionResult,
  User
} from "../../domain/ecommerce";
import { AdapterError } from "../../domain/errors";

export abstract class BaseEcommerceSupportAdapter
  implements EcommerceSupportAdapter
{
  abstract readonly siteId: string;

  abstract validateAuth(ctx: AuthenticatedContext): Promise<User>;
  abstract searchProducts(
    ctx: AuthenticatedContext,
    input: ProductSearchFilter
  ): Promise<ProductSearchResult>;
  abstract searchKnowledge(
    ctx: AuthenticatedContext,
    input: KnowledgeSearchInput
  ): Promise<KnowledgeSearchResult>;
  abstract getOrderStatus(
    ctx: AuthenticatedContext,
    input: GetOrderStatusInput
  ): Promise<GetOrderStatusResult>;
  abstract getDeliveryTracking(
    ctx: AuthenticatedContext,
    input: GetDeliveryTrackingInput
  ): Promise<GetDeliveryTrackingResult>;
  abstract submitOrderAction(
    ctx: AuthenticatedContext,
    input: SubmitOrderActionInput
  ): Promise<SubmitOrderActionResult>;

  async healthcheck(): Promise<AdapterHealth> {
    return {
      siteId: this.siteId,
      ok: true,
      checkedAt: new Date().toISOString()
    };
  }

  protected assertAuthenticated(ctx: AuthenticatedContext) {
    if (!ctx.userId) {
      throw new AdapterError("UNAUTHORIZED", "로그인이 필요합니다.");
    }
  }

  protected assertOrderOwnership(orderUserId: string, ctx: AuthenticatedContext) {
    if (orderUserId !== ctx.userId) {
      throw new AdapterError("FORBIDDEN", "본인 주문만 조회할 수 있습니다.");
    }
  }

  protected normalizeOrderStatus(raw: string): OrderStatus {
    const v = raw.toLowerCase();

    if (["pending", "created"].includes(v)) return "pending";
    if (["paid", "payment_complete"].includes(v)) return "paid";
    if (["preparing", "packing"].includes(v)) return "preparing";
    if (["shipped", "shipping"].includes(v)) return "shipped";
    if (["delivered", "done"].includes(v)) return "delivered";
    if (["cancel_requested"].includes(v)) return "cancel_requested";
    if (["cancelled", "canceled"].includes(v)) return "cancelled";
    if (["exchange_requested"].includes(v)) return "exchange_requested";
    if (["refund_requested"].includes(v)) return "refund_requested";
    if (["refunded"].includes(v)) return "refunded";

    return "unknown";
  }

  protected normalizeDeliveryStatus(raw: string): DeliveryStatus {
    const v = raw.toLowerCase();

    if (["ready"].includes(v)) return "ready";
    if (["in_transit", "shipping"].includes(v)) return "in_transit";
    if (["out_for_delivery"].includes(v)) return "out_for_delivery";
    if (["delivered"].includes(v)) return "delivered";
    if (["delayed"].includes(v)) return "delayed";

    return "unknown";
  }

  protected wrapUpstreamError(error: unknown): AdapterError {
    if (error instanceof AdapterError) {
      return error;
    }

    return new AdapterError("UPSTREAM_ERROR", "외부 서비스 호출 중 오류가 발생했습니다.", {
      cause: error instanceof Error ? error.message : String(error)
    });
  }
}
