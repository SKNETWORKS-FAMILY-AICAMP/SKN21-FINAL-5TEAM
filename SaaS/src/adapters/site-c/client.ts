import {
  GetDeliveryTrackingInput,
  GetOrderStatusInput,
  ProductSearchFilter,
  SubmitOrderActionInput
} from "../../domain/ecommerce";

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH";
  headers?: Record<string, string>;
  body?: unknown;
};

export type SiteCClientOptions = {
  baseUrl: string;
  timeoutMs?: number;
};

export class SiteCClient {
  constructor(private readonly options: SiteCClientOptions) {}

  async validateSession(headers: Record<string, string>) {
    return this.request("/users/me", { method: "GET", headers });
  }

  async searchProducts(input: ProductSearchFilter, headers: Record<string, string>) {
    const query = new URLSearchParams();
    if (input.query) {
      query.set("keyword", input.query);
    }
    if (input.minPrice !== undefined) {
      query.set("min_price", String(input.minPrice));
    }
    if (input.maxPrice !== undefined) {
      query.set("max_price", String(input.maxPrice));
    }
    if (input.limit !== undefined) {
      query.set("limit", String(input.limit));
    }

    const path = query.toString() ? `/products/new?${query.toString()}` : "/products/new";
    return this.request(path, { method: "GET", headers });
  }

  async getOrder(userId: string, input: GetOrderStatusInput, headers: Record<string, string>) {
    return this.request(`/orders/${userId}/orders/${input.orderId}`, {
      method: "GET",
      headers
    });
  }

  async getDelivery(input: GetDeliveryTrackingInput, headers: Record<string, string>) {
    return this.request(`/shipping/order/${input.orderId}`, {
      method: "GET",
      headers
    });
  }

  async submitCancel(
    userId: string,
    input: SubmitOrderActionInput,
    headers: Record<string, string>
  ) {
    const query = new URLSearchParams();
    if (input.reasonText) {
      query.set("reason", input.reasonText);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this.request(`/orders/${userId}/orders/${input.orderId}/cancel${suffix}`, {
      method: "POST",
      headers
    });
  }

  async submitRefund(
    userId: string,
    input: SubmitOrderActionInput,
    headers: Record<string, string>
  ) {
    const reason = input.reasonText || input.reasonCode || "환불 요청";
    const query = new URLSearchParams({ reason });
    return this.request(`/orders/${userId}/orders/${input.orderId}/refund?${query.toString()}`, {
      method: "POST",
      headers
    });
  }

  private async request(path: string, options: RequestOptions) {
    const controller = new AbortController();
    const timeout = setTimeout(
      () => controller.abort(),
      this.options.timeoutMs ?? 10000
    );

    try {
      const response = await fetch(`${this.options.baseUrl}${path}`, {
        method: options.method ?? "GET",
        headers: {
          "Content-Type": "application/json",
          ...(options.headers ?? {})
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
        signal: controller.signal
      });

      const text = await response.text();
      const data = text ? JSON.parse(text) : undefined;

      if (!response.ok) {
        throw new Error(
          `SiteC upstream error: ${response.status} ${response.statusText} ${text}`
        );
      }

      return data;
    } finally {
      clearTimeout(timeout);
    }
  }
}
