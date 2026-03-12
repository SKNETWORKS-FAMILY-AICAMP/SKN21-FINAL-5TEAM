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
import { assertSiteCContext, buildSiteCAuthHeaders } from "./auth";
import { SiteCClient } from "./client";
import { AdapterError } from "../../domain/errors";
import {
  mapSiteCDelivery,
  mapSiteCKnowledge,
  mapSiteCOrder,
  mapSiteCOrderAction,
  mapSiteCProductSearch,
  mapSiteCUser
} from "./mappers";

export class SiteCAdapter extends BaseEcommerceSupportAdapter {
  readonly siteId = "site-a";

  constructor(private readonly client: SiteCClient) {
    super();
  }

  async validateAuth(ctx: AuthenticatedContext): Promise<User> {
    this.assertAuthenticated(ctx);
    assertSiteCContext(ctx);

    try {
      const raw = await this.client.validateSession(buildSiteCAuthHeaders(ctx));
      const mapped = mapSiteCUser(raw, this.siteId);
      if (!mapped.id) {
        throw new AdapterError("UNAUTHORIZED", "로그인이 필요합니다.");
      }
      if (mapped.id !== ctx.userId) {
        throw new AdapterError("FORBIDDEN", "세션 사용자와 요청 사용자가 일치하지 않습니다.");
      }
      return mapped;
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
      const raw = await this.client.searchProducts(input, buildSiteCAuthHeaders(ctx));
      return mapSiteCProductSearch(raw, this.siteId);
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
    throw new AdapterError("NOT_SUPPORTED", "ecommerce 사이트는 독립 knowledge 검색 API를 제공하지 않습니다.");
  }

  async getOrderStatus(
    ctx: AuthenticatedContext,
    input: GetOrderStatusInput
  ): Promise<GetOrderStatusResult> {
    this.assertAuthenticated(ctx);

    try {
      const raw = await this.client.getOrder(ctx.userId, input, buildSiteCAuthHeaders(ctx));
      const mapped = mapSiteCOrder(raw, {
        siteId: this.siteId,
        normalizeOrderStatus: (status) => this.normalizeOrderStatus(status),
        normalizeDeliveryStatus: (status) => this.normalizeDeliveryStatus(status)
      });
      this.assertOrderOwnership(mapped.order.userId, ctx);
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
      const raw = await this.client.getDelivery(input, buildSiteCAuthHeaders(ctx));

      if (!raw) {
        throw new AdapterError("NOT_FOUND", "배송 정보를 찾을 수 없습니다.", {
          orderId: input.orderId
        });
      }

      return mapSiteCDelivery(raw, {
        siteId: this.siteId,
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
    this.assertAuthenticated(ctx);

    try {
      await this.getOrderStatus(ctx, { orderId: input.orderId });

      if (input.actionType === "cancel") {
        const raw = await this.client.submitCancel(
          ctx.userId,
          input,
          buildSiteCAuthHeaders(ctx)
        );
        return mapSiteCOrderAction(raw);
      }

      if (input.actionType === "refund") {
        const raw = await this.client.submitRefund(
          ctx.userId,
          input,
          buildSiteCAuthHeaders(ctx)
        );
        return mapSiteCOrderAction(raw);
      }

      throw new AdapterError("NOT_SUPPORTED", "ecommerce 사이트는 exchange API를 제공하지 않습니다.");
    } catch (error) {
      throw this.wrapUpstreamError(error);
    }
  }
}
