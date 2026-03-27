import { createRoot } from 'react-dom/client';
import type { SharedWidgetCapabilities, SharedWidgetHostConfig } from './ChatbotWidget';
import ChatbotFab from './chatbotfab';

type SharedWidgetHostContract = {
  chatbotServerBaseUrl: string;
  authBootstrapPath: string;
  widgetBundlePath: string;
  widgetElementTag: string;
  mountMode: 'floating_launcher';
  capabilityProfile?: string;
  enabledRetrievalCorpora?: string[];
  widgetFeatures?: {
    imageUpload?: boolean;
  };
};

type GlobalSharedWidgetContract = Partial<SharedWidgetHostContract> | undefined;

const ORDER_CS_WIDGET_TAG = 'order-cs-widget';

const DEFAULT_SHARED_WIDGET_HOST_CONTRACT: SharedWidgetHostContract = {
  chatbotServerBaseUrl: '',
  authBootstrapPath: '/api/chat/auth-token',
  widgetBundlePath: '/widget.js',
  widgetElementTag: ORDER_CS_WIDGET_TAG,
  mountMode: 'floating_launcher',
};

const HTMLElementBase: typeof HTMLElement =
  typeof HTMLElement === 'undefined' ? (class {} as typeof HTMLElement) : HTMLElement;

declare global {
  // The host page injects this shape before the widget boots.
  // eslint-disable-next-line no-var
  var __ORDER_CS_WIDGET_HOST_CONTRACT__: GlobalSharedWidgetContract;
  // eslint-disable-next-line no-var
  var __ORDER_CS_WIDGET_CSS__: string | undefined;
}

type HostAttributeName =
  | 'chatbot-server-base-url'
  | 'auth-bootstrap-path'
  | 'widget-bundle-path'
  | 'mount-mode'
  | 'capabilities'
  | 'capability-profile'
  | 'enabled-retrieval-corpora';

type AttributeOverrides = Partial<Record<HostAttributeName, string | null | undefined>>;

function normalizeBaseUrl(value: string | null | undefined): string {
  return String(value ?? '').trim().replace(/\/+$/, '');
}

function normalizeString(value: string | null | undefined): string {
  return String(value ?? '').trim();
}

function readAttributeOverrides(element: HTMLElement): AttributeOverrides {
  return {
    'chatbot-server-base-url': element.getAttribute('chatbot-server-base-url'),
    'auth-bootstrap-path': element.getAttribute('auth-bootstrap-path'),
    'widget-bundle-path': element.getAttribute('widget-bundle-path'),
    'mount-mode': element.getAttribute('mount-mode'),
    capabilities: element.getAttribute('capabilities'),
    'capability-profile': element.getAttribute('capability-profile'),
    'enabled-retrieval-corpora': element.getAttribute('enabled-retrieval-corpora'),
  };
}

function parseEnabledRetrievalCorpora(value: string | null | undefined): string[] | undefined {
  const normalized = normalizeString(value);
  if (!normalized) {
    return undefined;
  }
  return normalized
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function readGlobalContract(): SharedWidgetHostContract {
  const globalContract = globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__ ?? {};
  return {
    chatbotServerBaseUrl: normalizeBaseUrl(
      globalContract.chatbotServerBaseUrl ?? DEFAULT_SHARED_WIDGET_HOST_CONTRACT.chatbotServerBaseUrl,
    ),
    authBootstrapPath: normalizeString(
      globalContract.authBootstrapPath ?? DEFAULT_SHARED_WIDGET_HOST_CONTRACT.authBootstrapPath,
    ),
    widgetBundlePath: normalizeString(
      globalContract.widgetBundlePath ?? DEFAULT_SHARED_WIDGET_HOST_CONTRACT.widgetBundlePath,
    ),
    widgetElementTag: normalizeString(
      globalContract.widgetElementTag ?? DEFAULT_SHARED_WIDGET_HOST_CONTRACT.widgetElementTag,
    ),
    mountMode: DEFAULT_SHARED_WIDGET_HOST_CONTRACT.mountMode,
    capabilityProfile: normalizeString(globalContract.capabilityProfile),
    enabledRetrievalCorpora: Array.isArray(globalContract.enabledRetrievalCorpora)
      ? globalContract.enabledRetrievalCorpora.map((item) => String(item).trim()).filter(Boolean)
      : undefined,
    widgetFeatures:
      globalContract.widgetFeatures &&
      typeof globalContract.widgetFeatures === 'object'
        ? { imageUpload: Boolean(globalContract.widgetFeatures.imageUpload) }
        : undefined,
  };
}

export function resolveOrderCsWidgetHostContract(
  attributeOverrides: AttributeOverrides = {},
): SharedWidgetHostContract {
  const contract = readGlobalContract();
  return {
    chatbotServerBaseUrl: normalizeBaseUrl(
      attributeOverrides['chatbot-server-base-url'] ?? contract.chatbotServerBaseUrl,
    ),
    authBootstrapPath: normalizeString(
      attributeOverrides['auth-bootstrap-path'] ?? contract.authBootstrapPath,
    ),
    widgetBundlePath: normalizeString(
      attributeOverrides['widget-bundle-path'] ?? contract.widgetBundlePath,
    ),
    // The custom element tag is fixed at registration time.
    widgetElementTag: ORDER_CS_WIDGET_TAG,
    mountMode: contract.mountMode,
    capabilityProfile: normalizeString(
      attributeOverrides['capability-profile'] ?? contract.capabilityProfile,
    ),
    enabledRetrievalCorpora:
      parseEnabledRetrievalCorpora(attributeOverrides['enabled-retrieval-corpora']) ??
      contract.enabledRetrievalCorpora,
    widgetFeatures: contract.widgetFeatures,
  };
}

function toHostedWidgetConfig(contract: SharedWidgetHostContract): SharedWidgetHostConfig {
  return {
    authBootstrapPath: contract.authBootstrapPath,
    chatbotApiBase: contract.chatbotServerBaseUrl,
    chatPath: '/api/chat',
    streamPath: '/api/v1/chat/stream',
    capabilityProfile: contract.capabilityProfile,
    enabledRetrievalCorpora: contract.enabledRetrievalCorpora,
    widgetFeatures: contract.widgetFeatures,
  };
}

function resolveHostedWidgetCapabilities(
  attributeOverrides: AttributeOverrides = {},
): SharedWidgetCapabilities | undefined {
  const capabilityValue = normalizeString(attributeOverrides.capabilities);
  if (capabilityValue.toLowerCase() === 'full') {
    return 'full';
  }
  return undefined;
}

function injectWidgetStyles(shadowRoot: ShadowRoot): void {
  const rootWithMarker = shadowRoot as ShadowRoot & {
    __orderCsWidgetStylesInjected?: boolean;
  };
  if (rootWithMarker.__orderCsWidgetStylesInjected) {
    return;
  }

  const cssText =
    typeof globalThis.__ORDER_CS_WIDGET_CSS__ === 'string'
      ? globalThis.__ORDER_CS_WIDGET_CSS__.trim()
      : '';
  if (!cssText) {
    return;
  }

  const styleElement: {
    textContent: string;
    setAttribute(name: string, value: string): void;
  } =
    typeof document !== 'undefined' && typeof document.createElement === 'function'
      ? document.createElement('style')
      : {
          textContent: '',
          setAttribute() {},
        };
  styleElement.textContent = cssText;
  styleElement.setAttribute('data-order-cs-widget-styles', 'true');
  shadowRoot.appendChild(styleElement as unknown as Node);
  rootWithMarker.__orderCsWidgetStylesInjected = true;
}

export class OrderCsWidgetElement extends HTMLElementBase {
  private root: ReturnType<typeof createRoot> | null = null;

  connectedCallback() {
    const shadowRoot = this.shadowRoot ?? this.attachShadow({ mode: 'open' });
    injectWidgetStyles(shadowRoot);
    const attributeOverrides = readAttributeOverrides(this);
    const contract = resolveOrderCsWidgetHostContract(attributeOverrides);
    const widgetHost = toHostedWidgetConfig(contract);
    const widgetCapabilities = resolveHostedWidgetCapabilities(attributeOverrides);

    if (!this.root) {
      this.root = createRoot(shadowRoot);
    }

      this.root.render(
        <ChatbotFab isLoggedIn={true} host={widgetHost} capabilities={widgetCapabilities} />
      );
  }

  disconnectedCallback() {
    this.root?.unmount();
    this.root = null;
  }
}

export function registerOrderCsWidget(): typeof OrderCsWidgetElement {
  const registry = globalThis.customElements;
  if (!registry?.define || !registry?.get) {
    return OrderCsWidgetElement;
  }
  if (!registry.get(ORDER_CS_WIDGET_TAG)) {
    registry.define(ORDER_CS_WIDGET_TAG, OrderCsWidgetElement);
  }
  return OrderCsWidgetElement;
}
