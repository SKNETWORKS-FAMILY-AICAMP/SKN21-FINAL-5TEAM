export type ID = string;

export type CurrencyCode = "KRW" | "USD" | "JPY" | "EUR" | string;

export type Money = {
  amount: number;
  currency: CurrencyCode;
};

export type AuthenticatedContext = {
  siteId: string;
  userId: string;
  sessionRef?: string;
  accessToken?: string;
  cookies?: Record<string, string>;
  metadata?: Record<string, unknown>;
};

export type User = {
  id: ID;
  siteId: string;
  email?: string;
  name?: string;
};

export type ProductSearchFilter = {
  query: string;
  categoryIds?: ID[];
  brandNames?: string[];
  minPrice?: number;
  maxPrice?: number;
  inStockOnly?: boolean;
  limit?: number;
};

export type ProductSummary = {
  id: ID;
  siteId: string;
  title: string;
  shortDescription?: string;
  price?: Money;
  inStock?: boolean;
  imageUrl?: string;
  productUrl?: string;
  categoryIds?: ID[];
  brand?: string;
};

export type ProductSearchResult = {
  items: ProductSummary[];
  total?: number;
};

export type KnowledgeDocumentType =
  | "faq"
  | "shipping_policy"
  | "return_policy"
  | "exchange_policy"
  | "cancel_policy"
  | "general_policy";

export type KnowledgeDocument = {
  id: ID;
  siteId: string;
  type: KnowledgeDocumentType;
  title: string;
  content: string;
  url?: string;
  tags?: string[];
  updatedAt?: string;
};

export type KnowledgeSearchInput = {
  query: string;
  topK?: number;
  documentTypes?: KnowledgeDocumentType[];
};

export type KnowledgeSearchResult = {
  documents: KnowledgeDocument[];
};

export type OrderStatus =
  | "pending"
  | "paid"
  | "preparing"
  | "shipped"
  | "delivered"
  | "cancel_requested"
  | "cancelled"
  | "exchange_requested"
  | "refund_requested"
  | "refunded"
  | "unknown";

export type DeliveryStatus =
  | "ready"
  | "in_transit"
  | "out_for_delivery"
  | "delivered"
  | "delayed"
  | "unknown";

export type OrderItem = {
  productId: ID;
  productTitle: string;
  quantity: number;
  unitPrice?: Money;
  imageUrl?: string;
};

export type OrderSummary = {
  orderId: ID;
  siteId: string;
  userId: ID;
  status: OrderStatus;
  items: OrderItem[];
  totalPrice?: Money;
  orderedAt?: string;
};

export type GetOrderStatusInput = {
  orderId: ID;
};

export type GetOrderStatusResult = {
  order: OrderSummary;
};

export type DeliveryTracking = {
  orderId: ID;
  deliveryStatus: DeliveryStatus;
  carrierName?: string;
  trackingNumber?: string;
  trackingUrl?: string;
  lastUpdatedAt?: string;
  events?: Array<{
    status: string;
    description?: string;
    timestamp?: string;
  }>;
};

export type GetDeliveryTrackingInput = {
  orderId: ID;
};

export type GetDeliveryTrackingResult = {
  tracking: DeliveryTracking;
};

export type OrderActionType = "cancel" | "refund" | "exchange";

export type OrderActionReason =
  | "changed_mind"
  | "wrong_item"
  | "defective_item"
  | "delayed_delivery"
  | "duplicate_order"
  | "other";

export type SubmitOrderActionInput = {
  orderId: ID;
  actionType: OrderActionType;
  reasonCode: OrderActionReason;
  reasonText?: string;
  itemIds?: ID[];
};

export type SubmitOrderActionResult = {
  success: boolean;
  requestId?: ID;
  status:
    | "accepted"
    | "requested"
    | "rejected"
    | "not_allowed"
    | "manual_review_required";
  message: string;
};

export type AdapterHealth = {
  siteId: string;
  ok: boolean;
  checkedAt: string;
};

export interface EcommerceSupportAdapter {
  readonly siteId: string;

  validateAuth(ctx: AuthenticatedContext): Promise<User>;

  searchProducts(
    ctx: AuthenticatedContext,
    input: ProductSearchFilter
  ): Promise<ProductSearchResult>;

  searchKnowledge(
    ctx: AuthenticatedContext,
    input: KnowledgeSearchInput
  ): Promise<KnowledgeSearchResult>;

  getOrderStatus(
    ctx: AuthenticatedContext,
    input: GetOrderStatusInput
  ): Promise<GetOrderStatusResult>;

  getDeliveryTracking(
    ctx: AuthenticatedContext,
    input: GetDeliveryTrackingInput
  ): Promise<GetDeliveryTrackingResult>;

  submitOrderAction(
    ctx: AuthenticatedContext,
    input: SubmitOrderActionInput
  ): Promise<SubmitOrderActionResult>;

  healthcheck(): Promise<AdapterHealth>;
}
