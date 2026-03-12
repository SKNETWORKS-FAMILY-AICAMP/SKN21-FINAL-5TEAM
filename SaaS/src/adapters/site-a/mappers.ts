import {
  DeliveryTracking,
  GetDeliveryTrackingResult,
  GetOrderStatusResult,
  KnowledgeSearchResult,
  ProductSearchResult,
  SubmitOrderActionResult,
  User
} from "../../domain/ecommerce";

type SiteAMapperDeps = {
  siteId: string;
  currentUserId: string;
  normalizeOrderStatus: (raw: string) => GetOrderStatusResult["order"]["status"];
  normalizeDeliveryStatus: (
    raw: string
  ) => GetDeliveryTrackingResult["tracking"]["deliveryStatus"];
};

export function mapSiteAUser(raw: any, siteId: string): User {
  return {
    id: String(raw.user?.id ?? ""),
    siteId,
    email: raw.user?.email,
    name: raw.user?.name
  };
}

export function mapSiteAProductSearch(raw: any, siteId: string): ProductSearchResult {
  const list = Array.isArray(raw) ? raw : [];

  const items = list.map((item: any) => ({
    id: String(item.id),
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
    imageUrl: item.image,
    categoryIds: item.category ? [String(item.category)] : undefined,
    brand: item.brand
  }));

  return {
    items,
    total: items.length
  };
}

export function mapSiteAKnowledge(raw: any, siteId: string): KnowledgeSearchResult {
  void raw;
  void siteId;
  return { documents: [] };
}

export function mapSiteAOrder(raw: any, deps: SiteAMapperDeps): GetOrderStatusResult {
  return {
    order: {
      orderId: String(raw.id),
      siteId: deps.siteId,
      userId: deps.currentUserId,
      status: deps.normalizeOrderStatus(raw.status ?? "unknown"),
      items: [
        {
          productId: String(raw.product?.id),
          productTitle: raw.product?.name ?? "",
          quantity: Number(raw.quantity ?? 0),
          unitPrice:
            raw.product?.price !== undefined
              ? {
                  amount: Number(raw.product.price),
                  currency: "KRW"
                }
              : undefined,
          imageUrl: raw.product?.image_url
        }
      ],
      totalPrice: raw.total_price !== undefined
        ? {
            amount: Number(raw.total_price),
            currency: "KRW"
          }
        : undefined,
      orderedAt: raw.created_at
    }
  };
}

export function mapSiteADelivery(raw: any, deps: SiteAMapperDeps): GetDeliveryTrackingResult {
  const rawStatus = String(raw.status ?? "unknown").toLowerCase();
  const deliveryToken = rawStatus === "shipping" ? "in_transit" : rawStatus;

  const tracking: DeliveryTracking = {
    orderId: String(raw.id),
    deliveryStatus: deps.normalizeDeliveryStatus(deliveryToken),
    lastUpdatedAt: raw.created_at
  };

  return { tracking };
}

export function mapSiteAOrderAction(raw: any): SubmitOrderActionResult {
  const ok = Boolean(raw.order || raw.message);

  return {
    success: ok,
    status: ok ? "accepted" : "rejected",
    message: raw.message ?? "요청이 처리되었습니다."
  };
}
