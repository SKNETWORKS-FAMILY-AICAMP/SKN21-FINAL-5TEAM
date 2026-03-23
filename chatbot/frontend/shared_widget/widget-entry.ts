import { DEFAULT_SHARED_WIDGET_HOST_CONTRACT } from './index';
import { registerOrderCsWidget } from './web-component';

const existingGlobalContract = (globalThis as typeof globalThis & {
  __ORDER_CS_WIDGET_HOST_CONTRACT__?: Record<string, unknown>;
}).__ORDER_CS_WIDGET_HOST_CONTRACT__;

const SHARED_WIDGET_HOST_CONTRACT = existingGlobalContract
  ? {
      ...DEFAULT_SHARED_WIDGET_HOST_CONTRACT,
      ...existingGlobalContract,
      widgetElementTag: DEFAULT_SHARED_WIDGET_HOST_CONTRACT.widgetElementTag,
    }
  : {
      ...DEFAULT_SHARED_WIDGET_HOST_CONTRACT,
    };

if (typeof globalThis === 'object') {
  globalThis.__ORDER_CS_WIDGET_HOST_CONTRACT__ = existingGlobalContract
    ? Object.assign(existingGlobalContract, SHARED_WIDGET_HOST_CONTRACT)
    : SHARED_WIDGET_HOST_CONTRACT;
}

registerOrderCsWidget();

export { SHARED_WIDGET_HOST_CONTRACT };
export { OrderCsWidgetElement, registerOrderCsWidget, resolveOrderCsWidgetHostContract } from './web-component';
