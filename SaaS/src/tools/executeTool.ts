import { AdapterRegistry } from "../adapters/base/AdapterRegistry";
import {
  AuthenticatedContext,
  GetDeliveryTrackingResult,
  GetDeliveryTrackingInput,
  GetOrderStatusResult,
  GetOrderStatusInput,
  KnowledgeSearchResult,
  KnowledgeSearchInput,
  ProductSearchResult,
  ProductSearchFilter,
  SubmitOrderActionResult,
  SubmitOrderActionInput,
  User,
  AdapterHealth
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

export type ExecuteToolResult =
  | User
  | ProductSearchResult
  | KnowledgeSearchResult
  | GetOrderStatusResult
  | GetDeliveryTrackingResult
  | SubmitOrderActionResult
  | AdapterHealth;

export type CommonChatbotIntent =
  | "validate_auth"
  | "search_products"
  | "get_order_status"
  | "shipping"
  | "cancel"
  | "refund"
  | "exchange"
  | "healthcheck";

export type ExecuteCommonChatbotIntentInput = {
  intent: CommonChatbotIntent;
  ctx: AuthenticatedContext;
  payload?: unknown;
};

export async function executeTool(
  registry: AdapterRegistry,
  input: ExecuteToolInput
): Promise<ExecuteToolResult> {
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

// --------------------------------------------------
// Typed wrappers (공통 adapter 기능 연결용)
// --------------------------------------------------

export async function runValidateAuth(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext
): Promise<User> {
  return executeTool(registry, {
    toolName: "validate_auth",
    ctx
  }) as Promise<User>;
}

export async function runSearchProducts(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext,
  payload: ProductSearchFilter
): Promise<ProductSearchResult> {
  return executeTool(registry, {
    toolName: "search_products",
    ctx,
    payload
  }) as Promise<ProductSearchResult>;
}

export async function runSearchKnowledge(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext,
  payload: KnowledgeSearchInput
): Promise<KnowledgeSearchResult> {
  return executeTool(registry, {
    toolName: "search_knowledge",
    ctx,
    payload
  }) as Promise<KnowledgeSearchResult>;
}

export async function runGetOrderStatus(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext,
  payload: GetOrderStatusInput
): Promise<GetOrderStatusResult> {
  return executeTool(registry, {
    toolName: "get_order_status",
    ctx,
    payload
  }) as Promise<GetOrderStatusResult>;
}

export async function runGetDeliveryTracking(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext,
  payload: GetDeliveryTrackingInput
): Promise<GetDeliveryTrackingResult> {
  return executeTool(registry, {
    toolName: "get_delivery_tracking",
    ctx,
    payload
  }) as Promise<GetDeliveryTrackingResult>;
}

export async function runSubmitOrderAction(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext,
  payload: SubmitOrderActionInput
): Promise<SubmitOrderActionResult> {
  return executeTool(registry, {
    toolName: "submit_order_action",
    ctx,
    payload
  }) as Promise<SubmitOrderActionResult>;
}

export async function runHealthcheck(
  registry: AdapterRegistry,
  ctx: AuthenticatedContext
): Promise<AdapterHealth> {
  return executeTool(registry, {
    toolName: "healthcheck",
    ctx
  }) as Promise<AdapterHealth>;
}

// --------------------------------------------------
// Common chatbot intent -> adapter tool 연결
// (현재는 공통 기능만 연결)
// --------------------------------------------------

export async function executeCommonChatbotIntent(
  registry: AdapterRegistry,
  input: ExecuteCommonChatbotIntentInput
) {
  const { intent, ctx, payload } = input;

  const toOrderActionPayload = (
    actionType: SubmitOrderActionInput["actionType"]
  ): SubmitOrderActionInput => {
    const base = assertPayload<Partial<SubmitOrderActionInput>>(payload);
    const orderId = String(base.orderId ?? "").trim();

    if (!orderId) {
      throw new AdapterError("INVALID_INPUT", "orderId가 필요합니다.");
    }

    return {
      orderId,
      actionType,
      reasonCode: base.reasonCode ?? "other",
      reasonText: base.reasonText,
      itemIds: base.itemIds
    };
  };

  switch (intent) {
    case "validate_auth":
      return runValidateAuth(registry, ctx);

    case "search_products":
      return runSearchProducts(registry, ctx, assertPayload<ProductSearchFilter>(payload));

    case "get_order_status":
      return runGetOrderStatus(registry, ctx, assertPayload<GetOrderStatusInput>(payload));

    // order_tools.shipping
    case "shipping":
      return runGetDeliveryTracking(
        registry,
        ctx,
        assertPayload<GetDeliveryTrackingInput>(payload)
      );

    // order_tools.cancel/refund/exchange
    case "cancel":
      return runSubmitOrderAction(registry, ctx, toOrderActionPayload("cancel"));

    case "refund":
      return runSubmitOrderAction(registry, ctx, toOrderActionPayload("refund"));

    case "exchange":
      return runSubmitOrderAction(registry, ctx, toOrderActionPayload("exchange"));

    case "healthcheck":
      return runHealthcheck(registry, ctx);

    default:
      throw new AdapterError("NOT_SUPPORTED", "지원하지 않는 common chatbot intent 입니다.", {
        intent
      });
  }
}
