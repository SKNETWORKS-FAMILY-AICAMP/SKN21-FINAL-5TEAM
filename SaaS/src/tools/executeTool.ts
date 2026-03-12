import { AdapterRegistry } from "../adapters/base/AdapterRegistry";
import {
  AuthenticatedContext,
  GetDeliveryTrackingInput,
  GetOrderStatusInput,
  KnowledgeSearchInput,
  ProductSearchFilter,
  SubmitOrderActionInput
} from "../domain/ecommerce";
import { AdapterError } from "../domain/errors";

export type ToolName =
  | "validate_auth"
  | "search_products"
  | "search_knowledge"
  | "get_order_status"
  | "get_delivery_tracking"
  | "submit_order_action"
  | "healthcheck";

export type ExecuteToolInput = {
  toolName: ToolName;
  ctx: AuthenticatedContext;
  payload?: unknown;
};

export async function executeTool(registry: AdapterRegistry, input: ExecuteToolInput) {
  const adapter = registry.get(input.ctx.siteId);

  switch (input.toolName) {
    case "validate_auth":
      return adapter.validateAuth(input.ctx);

    case "search_products":
      return adapter.searchProducts(
        input.ctx,
        assertPayload<ProductSearchFilter>(input.payload)
      );

    case "search_knowledge":
      return adapter.searchKnowledge(
        input.ctx,
        assertPayload<KnowledgeSearchInput>(input.payload)
      );

    case "get_order_status":
      return adapter.getOrderStatus(
        input.ctx,
        assertPayload<GetOrderStatusInput>(input.payload)
      );

    case "get_delivery_tracking":
      return adapter.getDeliveryTracking(
        input.ctx,
        assertPayload<GetDeliveryTrackingInput>(input.payload)
      );

    case "submit_order_action":
      return adapter.submitOrderAction(
        input.ctx,
        assertPayload<SubmitOrderActionInput>(input.payload)
      );

    case "healthcheck":
      return adapter.healthcheck();

    default:
      throw new AdapterError("NOT_SUPPORTED", "지원하지 않는 tool 입니다.", {
        toolName: input.toolName
      });
  }
}

function assertPayload<T>(payload: unknown): T {
  if (!payload || typeof payload !== "object") {
    throw new AdapterError("INVALID_INPUT", "payload가 필요합니다.");
  }
  return payload as T;
}
