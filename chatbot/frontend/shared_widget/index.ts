export type SharedWidgetMountMode = 'floating_launcher';

export type SharedWidgetHostContract = {
  chatbotServerBaseUrl: string;
  authBootstrapPath: string;
  widgetBundlePath: string;
  widgetElementTag: string;
  mountMode: SharedWidgetMountMode;
};

export const DEFAULT_SHARED_WIDGET_HOST_CONTRACT: SharedWidgetHostContract = {
  chatbotServerBaseUrl: '',
  authBootstrapPath: '/api/chat/auth-token',
  widgetBundlePath: '/widget.js',
  widgetElementTag: 'order-cs-widget',
  mountMode: 'floating_launcher',
};

export { default as ChatbotWidget } from './ChatbotWidget';
export * from './ChatbotWidget';
export { default as ChatbotFab } from './chatbotfab';
export { default as OrderListUI } from './OrderListUI';
export { default as ProductListUI } from './ProductListUI';
export * from './ProductListUI';
export { default as ReviewFormUI } from './ReviewFormUI';
export { default as UsedSaleFormUI } from './UsedSaleFormUI';
