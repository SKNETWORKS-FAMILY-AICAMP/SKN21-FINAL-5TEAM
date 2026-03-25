'use client';

import { useEffect } from 'react';

type SharedWidgetMountMode = 'floating_launcher';

type SharedWidgetHostContract = {
  chatbotServerBaseUrl: string;
  authBootstrapPath: string;
  widgetBundlePath: string;
  widgetElementTag: string;
  mountMode: SharedWidgetMountMode;
};

function resolveChatbotServerBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_CHATBOT_API_URL || 'http://localhost:8100').replace(/\/+$/, '');
}

export default function ChatbotFabWrapper() {
  useEffect(() => {
    const chatbotServerBaseUrl = resolveChatbotServerBaseUrl();
    const hostContract: SharedWidgetHostContract = {
      chatbotServerBaseUrl,
      authBootstrapPath: `${chatbotServerBaseUrl}/api/v1/chat/auth-token`,
      widgetBundlePath: '/widget.js',
      widgetElementTag: 'order-cs-widget',
      mountMode: 'floating_launcher',
    };

    (
      globalThis as typeof globalThis & {
        __ORDER_CS_WIDGET_HOST_CONTRACT__?: SharedWidgetHostContract;
      }
    ).__ORDER_CS_WIDGET_HOST_CONTRACT__ = hostContract;

    if (document.querySelector('script[data-order-cs-widget-bundle="true"]')) {
      return;
    }

    const widgetScript = document.createElement('script');
    widgetScript.src = `${chatbotServerBaseUrl}${hostContract.widgetBundlePath}`;
    widgetScript.async = true;
    widgetScript.dataset.orderCsWidgetBundle = 'true';
    document.head.appendChild(widgetScript);
  }, []);

  return <order-cs-widget />;
}
