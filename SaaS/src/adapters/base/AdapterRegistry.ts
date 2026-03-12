import { EcommerceSupportAdapter } from "../../domain/ecommerce";
import { AdapterError } from "../../domain/errors";

export class AdapterRegistry {
  private adapters = new Map<string, EcommerceSupportAdapter>();

  register(adapter: EcommerceSupportAdapter) {
    this.adapters.set(adapter.siteId, adapter);
  }

  registerMany(adapters: EcommerceSupportAdapter[]) {
    for (const adapter of adapters) {
      this.register(adapter);
    }
  }

  get(siteId: string): EcommerceSupportAdapter {
    const adapter = this.adapters.get(siteId);
    if (!adapter) {
      throw new AdapterError(
        "NOT_FOUND",
        `siteId=${siteId} 에 대한 adapter를 찾을 수 없습니다.`
      );
    }
    return adapter;
  }

  listSiteIds(): string[] {
    return [...this.adapters.keys()];
  }
}
