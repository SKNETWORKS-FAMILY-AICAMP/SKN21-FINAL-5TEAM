import {
  GetDeliveryTrackingResult,
  GetOrderStatusResult,
  KnowledgeSearchResult,
  ProductSearchResult,
  SubmitOrderActionResult,
  User
} from "../../domain/ecommerce";

type SiteBMapperDeps = {
  siteId: string;
  currentUserId: string;
  targetOrderId: string;
  normalizeOrderStatus: (raw: string) => GetOrderStatusResult["order"]["status"];
  normalizeDeliveryStatus: (
    raw: string
  ) => GetDeliveryTrackingResult["tracking"]["deliveryStatus"];
};

const toOrderStatusToken = (raw: unknown): string => {
  const value = String(raw ?? "unknown").toLowerCase();
  if (value.includes("결제") && value.includes("대기")) return "pending";
  if (value.includes("결제") && value.includes("완료")) return "paid";
  if (value.includes("배송") && value.includes("준비")) return "preparing";
  if (value.includes("배송") && value.includes("중")) return "shipped";
  if (value.includes("배송") && value.includes("완료")) return "delivered";
  if (value.includes("취소")) return "cancelled";
  if (value.includes("환불")) return "refunded";
  return value;
};

const toDeliveryStatusToken = (raw: unknown): string => {
  const value = String(raw ?? "unknown").toLowerCase();
  if (value.includes("준비")) return "ready";
  if (value.includes("배송") && value.includes("중")) return "in_transit";
  if (value.includes("완료")) return "delivered";
  return value;
};

export function mapSiteBUser(raw: any, siteId: string): User {
  const orders = raw.orders ?? [];

  return {
    id: String(orders[0]?.user_id ?? ""),
    siteId,
    email: undefined,
    name: undefined
  };
}

export function mapSiteBProductSearch(raw: any, siteId: string): ProductSearchResult {
  const products = raw.products ?? [];

  return {
    items: products.map((item: any) => ({
      id: String(item.product_id),
      siteId,
      title: item.name,
      shortDescription: item.description,
      price: item.price !== undefined
          ? {
              amount: Number(item.price),
              currency: "KRW"
            }
          : undefined,
      inStock: (item.stock ?? 0) > 0,
      imageUrl: item.image_url,
      categoryIds: item.category ? [String(item.category)] : undefined,
      brand: item.brand
    })),
    total: products.length
  };
}

export function mapSiteBKnowledge(raw: any, siteId: string): KnowledgeSearchResult {
  void raw;
  void siteId;
  return {
    documents: []
  };
}

export function mapSiteBOrder(raw: any, deps: SiteBMapperDeps): GetOrderStatusResult {
  const orders = raw.orders ?? [];
  const found =
    orders.find((o: any) => String(o.order_id) === String(deps.targetOrderId)) ?? orders[0];
  const order = found ?? {};

  return {
    order: {
      orderId: String(order.order_id ?? ""),
      siteId: deps.siteId,
      userId: deps.currentUserId,
      status: deps.normalizeOrderStatus(toOrderStatusToken(order.status ?? "unknown")),
      items: (order.items ?? []).map((item: any) => ({
        productId: String(item.product_id),
        productTitle: item.product_name,
        quantity: Number(item.quantity),
        unitPrice: item.price !== undefined
          ? {
              amount: Number(item.price),
              currency: "KRW"
            }
          : undefined,
        imageUrl: item.image_url
      })),
      totalPrice: order.total_price !== undefined
        ? {
            amount: Number(order.total_price),
            currency: "KRW"
          }
        : undefined,
      orderedAt: order.created_at
    }
  };
}

export function mapSiteBDelivery(
  raw: any,
  deps: SiteBMapperDeps
): GetDeliveryTrackingResult {
  const orders = raw.orders ?? [];
  const order =
    orders.find((o: any) => String(o.order_id) === String(deps.targetOrderId)) ?? orders[0] ?? {};

  return {
    tracking: {
      orderId: String(order.order_id ?? ""),
      deliveryStatus: deps.normalizeDeliveryStatus(toDeliveryStatusToken(order.status ?? "unknown")),
      lastUpdatedAt: order.created_at
    }
  };
}

export function mapSiteBOrderAction(raw: any): SubmitOrderActionResult {
  void raw;
  return {
    success: false,
    status: "not_allowed",
    message: "bilyeo 사이트는 주문 액션 API를 제공하지 않습니다."
  };
}
