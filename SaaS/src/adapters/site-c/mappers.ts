import {
  GetDeliveryTrackingResult,
  GetOrderStatusResult,
  KnowledgeSearchResult,
  ProductSearchResult,
  SubmitOrderActionResult,
  User
} from "../../domain/ecommerce";

type SiteCMapperDeps = {
  siteId: string;
  normalizeOrderStatus: (raw: string) => GetOrderStatusResult["order"]["status"];
  normalizeDeliveryStatus: (
    raw: string
  ) => GetDeliveryTrackingResult["tracking"]["deliveryStatus"];
};

export function mapSiteCUser(raw: any, siteId: string): User {
  if (raw.authenticated === false) {
    return {
      id: "",
      siteId
    };
  }

  return {
    id: String(raw.id),
    siteId,
    email: raw.email,
    name: raw.name
  };
}

export function mapSiteCProductSearch(raw: any, siteId: string): ProductSearchResult {
  const list = Array.isArray(raw) ? raw : [];

  return {
    items: list.map((p: any) => ({
      id: String(p.id),
      siteId,
      title: p.name,
      shortDescription: p.description,
      price:
        p.price !== undefined
          ? {
              amount: Number(p.price),
              currency: p.currency ?? "KRW"
            }
          : undefined,
      inStock: p.inStock,
      imageUrl: undefined,
      categoryIds: p.category_id ? [String(p.category_id)] : undefined,
      brand: undefined
    })),
    total: list.length
  };
}

export function mapSiteCKnowledge(raw: any, siteId: string): KnowledgeSearchResult {
  void raw;
  void siteId;
  return {
    documents: []
  };
}

export function mapSiteCOrder(raw: any, deps: SiteCMapperDeps): GetOrderStatusResult {
  return {
    order: {
      orderId: String(raw.id),
      siteId: deps.siteId,
      userId: String(raw.user_id),
      status: deps.normalizeOrderStatus(String(raw.status ?? "unknown")),
      items: (raw.items ?? []).map((item: any) => ({
        productId: String(item.product_id ?? item.id ?? ""),
        productTitle: item.product_name ?? "",
        quantity: Number(item.quantity),
        unitPrice:
          item.unit_price !== undefined
            ? {
                amount: Number(item.unit_price),
                currency: "KRW"
              }
            : undefined,
        imageUrl: undefined
      })),
      totalPrice:
        raw.total_amount !== undefined
          ? {
              amount: Number(raw.total_amount),
              currency: "KRW"
            }
          : undefined,
      orderedAt: raw.created_at
    }
  };
}

export function mapSiteCDelivery(
  raw: any,
  deps: SiteCMapperDeps
): GetDeliveryTrackingResult {
  const deliveryRawStatus = raw?.delivered_at
    ? "delivered"
    : raw?.shipped_at
      ? "in_transit"
      : "ready";

  return {
    tracking: {
      orderId: String(raw.order_id),
      deliveryStatus: deps.normalizeDeliveryStatus(deliveryRawStatus),
      carrierName: raw.courier_company,
      trackingNumber: raw.tracking_number,
      lastUpdatedAt: raw.updated_at
    }
  };
}

export function mapSiteCOrderAction(raw: any): SubmitOrderActionResult {
  return {
    success: Boolean(raw?.message),
    status: "requested",
    message: raw?.message ?? "요청이 접수되었습니다."
  };
}
