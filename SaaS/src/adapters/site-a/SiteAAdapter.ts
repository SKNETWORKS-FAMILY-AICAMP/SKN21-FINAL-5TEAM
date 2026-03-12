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
import { buildSiteAAuthHeaders, assertSiteAContext } from "./auth";
import { SiteAClient } from "./client";
import { AdapterError } from "../../domain/errors";
import {
  mapSiteADelivery,
  mapSiteAKnowledge,
  mapSiteAOrder,
  mapSiteAOrderAction,
  mapSiteAProductSearch,
  mapSiteAUser
} from "./mappers";

export class SiteAAdapter extends BaseEcommerceSupportAdapter {
  readonly siteId = "site-b";

  constructor(private readonly client: SiteAClient) {
    super();
  }

  async validateAuth(ctx: AuthenticatedContext): Promise<User> {
    this.assertAuthenticated(ctx);
    assertSiteAContext(ctx);

    try {
      const raw = await this.client.validateSession(buildSiteAAuthHeaders(ctx));
      return mapSiteAUser(raw, this.siteId);
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
      const raw = await this.client.searchProducts(input, buildSiteAAuthHeaders(ctx));
      return mapSiteAProductSearch(raw, this.siteId);
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
    throw new AdapterError("NOT_SUPPORTED", "food 사이트는 지식문서 검색 API를 제공하지 않습니다.");
  }

  async getOrderStatus(
    ctx: AuthenticatedContext,
    input: GetOrderStatusInput
  ): Promise<GetOrderStatusResult> {
    this.assertAuthenticated(ctx);

    try {
      const raw = await this.client.getOrder(input, buildSiteAAuthHeaders(ctx));
      const mapped = mapSiteAOrder(raw, {
        siteId: this.siteId,
        currentUserId: ctx.userId,
        normalizeOrderStatus: (status) => this.normalizeOrderStatus(status),
        normalizeDeliveryStatus: (status) => this.normalizeDeliveryStatus(status)
      });
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
      const raw = await this.client.getDelivery(input, buildSiteAAuthHeaders(ctx));
      return mapSiteADelivery(raw, {
        siteId: this.siteId,
        currentUserId: ctx.userId,
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
      const raw = await this.client.submitOrderAction(input, buildSiteAAuthHeaders(ctx));
      return mapSiteAOrderAction(raw);
    } catch (error) {
      throw this.wrapUpstreamError(error);
    }
  }
}
