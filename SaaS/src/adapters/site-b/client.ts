import {
  GetDeliveryTrackingInput,
  GetOrderStatusInput,
  ProductSearchFilter,
  SubmitOrderActionInput
} from "../../domain/ecommerce";

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  headers?: Record<string, string>;
  body?: unknown;
};

export type SiteBClientOptions = {
  baseUrl: string;
  timeoutMs?: number;
};

export class SiteBClient {
  constructor(private readonly options: SiteBClientOptions) {}

  async validateSession(headers: Record<string, string>) {
    return this.request("/api/orders", { method: "GET", headers });
  }

  async searchProducts(input: ProductSearchFilter, headers: Record<string, string>) {
    const query = new URLSearchParams();
    if (input.query) {
      query.set("search", input.query);
    }
    if (input.categoryIds?.length) {
      query.set("category", input.categoryIds[0]);
    }
    const path = query.toString() ? `/api/products?${query.toString()}` : "/api/products";
    return this.request(path, { method: "GET", headers });
  }

  async getOrder(input: GetOrderStatusInput, headers: Record<string, string>) {
    return this.request("/api/orders", {
      method: "GET",
      headers
    });
  }

  async getDelivery(input: GetDeliveryTrackingInput, headers: Record<string, string>) {
    return this.getOrder({ orderId: input.orderId }, headers);
  }

  async submitOrderAction(input: SubmitOrderActionInput, headers: Record<string, string>) {
    void input;
    void headers;
    throw new Error("SiteB upstream error: submit order action endpoint is not provided by bilyeo");
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
          `SiteB upstream error: ${response.status} ${response.statusText} ${text}`
        );
      }

      return data;
    } finally {
      clearTimeout(timeout);
    }
  }
}
