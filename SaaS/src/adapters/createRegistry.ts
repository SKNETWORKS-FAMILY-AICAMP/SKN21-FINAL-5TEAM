import { AdapterRegistry } from "./base/AdapterRegistry";
import { SiteAAdapter } from "./site-a/SiteAAdapter";
import { SiteAClient } from "./site-a/client";
import { SiteBAdapter } from "./site-b/SiteBAdapter";
import { SiteBClient } from "./site-b/client";
import { SiteCAdapter } from "./site-c/SiteCAdapter";
import { SiteCClient } from "./site-c/client";

export type AdapterBootstrapConfig = {
  siteA: { baseUrl: string };
  siteB: { baseUrl: string };
  siteC: { baseUrl: string };
};

export function createAdapterRegistry(config: AdapterBootstrapConfig): AdapterRegistry {
  const registry = new AdapterRegistry();

  registry.registerMany([
    // site-a => ecommerce
    new SiteCAdapter(new SiteCClient({ baseUrl: config.siteA.baseUrl })),
    // site-b => food
    new SiteAAdapter(new SiteAClient({ baseUrl: config.siteB.baseUrl })),
    // site-c => bilyeo
    new SiteBAdapter(new SiteBClient({ baseUrl: config.siteC.baseUrl }))
  ]);

  return registry;
}
