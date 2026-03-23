import { BaseEcommerceSupportAdapter } from "../base/BaseEcommerceSupportAdapter";
import {
  AuthenticatedContext,
  GetDeliveryTrackingInput,
  GetDeliveryTrackingResult,
  GetOrderStatusInput,
  GetOrderStatusResult,
  KnowledgeSearchInput,
  KnowledgeSearchResult,
  ProductSearchFilter,
  ProductSearchResult,
  SubmitOrderActionInput,
  SubmitOrderActionResult,
  User
} from "../../domain/ecommerce";
import { assertSiteBContext, buildSiteBAuthHeaders } from "./auth";
import { SiteBClient } from "./client";
import { AdapterError } from "../../domain/errors";
import {
  mapSiteBDelivery,
  mapSiteBKnowledge,
  mapSiteBOrder,
  mapSiteBOrderAction,
  mapSiteBProductSearch,
  mapSiteBUser
} from "./mappers";

export class SiteBAdapter extends BaseEcommerceSupportAdapter {
  readonly siteId = "site-c";

  constructor(private readonly client: SiteBClient) {
    super();
  }

  async validateAuth(ctx: AuthenticatedContext): Promise<User> {
    this.assertAuthenticated(ctx);
    assertSiteBContext(ctx);

    try {
      const raw = await this.client.validateSession(buildSiteBAuthHeaders(ctx));
      const hasOrdersArray = Array.isArray(raw.orders);
      if (!hasOrdersArray) {
        throw new AdapterError("UNAUTHORIZED", "토큰 검증에 실패했습니다.");
      }
      return {
        ...mapSiteBUser(raw, this.siteId),
        id: ctx.userId
      };
    } catch (error) {
      throw this.wrapUpstreamError(error);
    }
  }

  async searchProducts(
    ctx: AuthenticatedContext,
    input: ProductSearchFilter
  ): Promise<ProductSearchResult> {
    this.assertAuthenticated(ctx);

    try {
      const raw = await this.client.searchProducts(input, buildSiteBAuthHeaders(ctx));
      return mapSiteBProductSearch(raw, this.siteId);
    } catch (error) {
      throw this.wrapUpstreamError(error);
    }
  }

  async searchKnowledge(
    ctx: AuthenticatedContext,
    input: KnowledgeSearchInput
  ): Promise<KnowledgeSearchResult> {
    void ctx;
    void input;
    throw new AdapterError("NOT_SUPPORTED", "bilyeo 사이트는 지식문서 검색 API를 제공하지 않습니다.");
  }

  async getOrderStatus(
    ctx: AuthenticatedContext,
    input: GetOrderStatusInput
  ): Promise<GetOrderStatusResult> {
    this.assertAuthenticated(ctx);

    try {
      const raw = await this.client.getOrder(input, buildSiteBAuthHeaders(ctx));
      const mapped = mapSiteBOrder(raw, {
        siteId: this.siteId,
        currentUserId: ctx.userId,
        targetOrderId: String(input.orderId),
        normalizeOrderStatus: (status) => this.normalizeOrderStatus(status),
        normalizeDeliveryStatus: (status) => this.normalizeDeliveryStatus(status)
      });

      if (!mapped.order.orderId || mapped.order.orderId !== String(input.orderId)) {
        throw new AdapterError("NOT_FOUND", "주문을 찾을 수 없습니다.", {
          orderId: input.orderId
        });
      }

      return mapped;
    } catch (error) {
      throw this.wrapUpstreamError(error);
    }
  }

  async getDeliveryTracking(
    ctx: AuthenticatedContext,
    input: GetDeliveryTrackingInput
  ): Promise<GetDeliveryTrackingResult> {
    this.assertAuthenticated(ctx);

    try {
      await this.getOrderStatus(ctx, { orderId: input.orderId });
      const raw = await this.client.getDelivery(input, buildSiteBAuthHeaders(ctx));
      return mapSiteBDelivery(raw, {
        siteId: this.siteId,
        currentUserId: ctx.userId,
        targetOrderId: String(input.orderId),
        normalizeOrderStatus: (status) => this.normalizeOrderStatus(status),
        normalizeDeliveryStatus: (status) => this.normalizeDeliveryStatus(status)
      });
    } catch (error) {
      throw this.wrapUpstreamError(error);
    }
  }

  async submitOrderAction(
    ctx: AuthenticatedContext,
    input: SubmitOrderActionInput
  ): Promise<SubmitOrderActionResult> {
    void ctx;
    void input;
    throw new AdapterError("NOT_SUPPORTED", "bilyeo 사이트는 주문 취소/환불/교환 API를 제공하지 않습니다.");
  }
}
