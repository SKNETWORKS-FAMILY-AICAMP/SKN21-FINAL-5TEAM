import React from 'react';
import OrderListUI, { type SharedOrderData, type SharedOrderUiConfig } from './OrderListUI';
import ProductListUI, { type UiProduct } from './ProductListUI';
import styles from './chatbot-widget.module.css';

export type SharedWidgetHostConfig = {
  authBootstrapPath: string;
  chatbotApiBase: string;
  chatPath?: string;
  streamPath?: string;
};

export type SharedWidgetAuthResult = {
  authenticated: boolean;
  siteId: string;
  accessToken: string;
};

export type SharedWidgetCapability =
  | 'orders_view'
  | 'orders_cancel'
  | 'orders_exchange'
  | 'orders_return'
  | 'products_view'
  | 'products_purchase';

export type SharedWidgetCapabilities = 'full' | SharedWidgetCapability[];

export type SharedChatApiResponse = {
  answer: string;
  conversation_id: string;
  completed_tasks: string[];
  ui_action_required: string | null;
  awaiting_interrupt: boolean;
  interrupts: Array<Record<string, unknown>>;
  ui_payload?: {
    type?: string;
    message?: string;
    ui_data?: unknown[];
    requires_selection?: boolean;
    prior_action?: string | null;
    ui_config?: SharedOrderUiConfig;
  };
  state: Record<string, any>;
};

export type SharedChatBootstrap = SharedWidgetAuthResult & {
  site_id: string;
  access_token: string;
};

export type SharedChatStreamHandlers = {
  onMessage?: (message: SharedChatMessage) => void;
  onStateChange?: (state: Record<string, unknown> | null) => void;
  onStatusChange?: (status: string | null) => void;
  onStreamingText?: (text: string) => void;
  onUnhandledUiAction?: (payload: Record<string, any>) => void;
};

type FetchLikeResponse = {
  ok: boolean;
  text?: () => Promise<string>;
  json?: () => Promise<any>;
  body?: {
    getReader?: () => {
      read: () => Promise<{ done: boolean; value?: Uint8Array }>;
    };
  };
};

export type FetchLike = (
  input: string,
  init?: Record<string, unknown>,
) => Promise<FetchLikeResponse>;

type TextMessage = {
  type: 'text';
  role?: 'user' | 'bot';
  text: string;
  isStreaming?: boolean;
  showDivider?: boolean;
};

type OrderListMessage = {
  type: 'order_list';
  role?: 'bot';
  message: string;
  orders: SharedOrderData[];
  requiresSelection?: boolean;
  prior_action?: string | null;
  ui_config?: SharedOrderUiConfig;
};

type ProductListMessage = {
  type: 'product_list';
  role?: 'bot';
  message: string;
  products: UiProduct[];
};

export type SharedChatMessage = TextMessage | OrderListMessage | ProductListMessage;

type ChatbotWidgetProps<TMessage extends { type: string; role?: string } = SharedChatMessage> = {
  messages: TMessage[];
  capabilities?: SharedWidgetCapabilities;
  onOrderSelect?: (selectedOrderIds: string[], message: OrderListMessage) => void;
  onProductSelect?: (product: UiProduct, message: ProductListMessage) => void;
  renderTextMessage?: (message: TextMessage, index: number) => React.ReactNode;
  renderOrderList?: (message: OrderListMessage, index: number) => React.ReactNode;
  renderProductList?: (message: ProductListMessage, index: number) => React.ReactNode;
  renderFallback?: (message: TMessage, index: number) => React.ReactNode;
  className?: string;
  messageListClassName?: string;
};

type KeyedMessage = {
  id?: string | number;
  message_id?: string | number;
  messageKey?: string | number;
};

function _isTextMessage(message: { type: string }): message is TextMessage {
  return message.type === 'text';
}

function _isOrderListMessage(message: { type: string }): message is OrderListMessage {
  return message.type === 'order_list';
}

function _isProductListMessage(message: { type: string }): message is ProductListMessage {
  return message.type === 'product_list';
}

function _getExplicitMessageKey(message: KeyedMessage): string | undefined {
  const rawKey = message.messageKey ?? message.message_id ?? message.id;
  return rawKey === undefined || rawKey === null ? undefined : String(rawKey);
}

function _stableSerializeMessageValue(value: unknown): string {
  if (value === null) {
    return 'null';
  }

  if (value === undefined) {
    return 'undefined';
  }

  if (Array.isArray(value)) {
    return `[${value.map((item) => _stableSerializeMessageValue(item)).join(',')}]`;
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, entryValue]) => entryValue !== undefined)
      .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey));

    return `{${entries
      .map(([entryKey, entryValue]) => `${entryKey}:${_stableSerializeMessageValue(entryValue)}`)
      .join(',')}}`;
  }

  return JSON.stringify(value);
}

function _getStableMessageKey(message: KeyedMessage & { type: string; role?: string }): string {
  const explicitKey = _getExplicitMessageKey(message);
  if (explicitKey) {
    return explicitKey;
  }

  const { id: _id, message_id: _messageId, messageKey: _messageKey, ...rest } = message;
  return _stableSerializeMessageValue(rest);
}

function _hasSharedWidgetCapability(
  capabilities: SharedWidgetCapabilities | undefined,
  capability: SharedWidgetCapability,
): boolean {
  return capabilities === undefined || capabilities === 'full' || capabilities.includes(capability);
}

function _resolveChatEndpoint(host: SharedWidgetHostConfig): string {
  return `${host.chatbotApiBase.replace(/\/$/, '')}${host.chatPath ?? '/api/chat'}`;
}

function _resolveStreamEndpoint(host: SharedWidgetHostConfig): string {
  return `${host.chatbotApiBase.replace(/\/$/, '')}${host.streamPath ?? '/api/v1/chat/stream'}`;
}

async function _readJsonPayload(response: FetchLikeResponse): Promise<any> {
  if (response.json) {
    return response.json();
  }

  if (!response.text) {
    return {};
  }

  const rawBody = await response.text();
  return rawBody ? JSON.parse(rawBody) : {};
}

export async function bootstrapSharedWidgetAuth(
  fetchImpl: FetchLike,
  host: SharedWidgetHostConfig,
): Promise<SharedChatBootstrap> {
  const response = await fetchImpl(host.authBootstrapPath, {
    method: 'POST',
    credentials: 'include',
  });
  const payload = await _readJsonPayload(response);

  if (!response.ok || !payload.authenticated) {
    return {
      authenticated: false,
      siteId: String(payload.site_id ?? ''),
      accessToken: String(payload.access_token ?? ''),
      site_id: String(payload.site_id ?? ''),
      access_token: String(payload.access_token ?? ''),
    };
  }

  return {
    authenticated: true,
    siteId: String(payload.site_id ?? ''),
    accessToken: String(payload.access_token ?? ''),
    site_id: String(payload.site_id ?? ''),
    access_token: String(payload.access_token ?? ''),
  };
}

export async function bootstrapSharedChatAuth(
  host: SharedWidgetHostConfig,
  fetchImpl: FetchLike,
): Promise<SharedChatBootstrap> {
  return bootstrapSharedWidgetAuth(fetchImpl, host);
}

export async function sendSharedChatRequest(
  fetchImpl: FetchLike,
  host: SharedWidgetHostConfig,
  payload: {
    message: string;
    accessToken: string;
    siteId: string;
    previousState?: Record<string, unknown> | null;
  },
): Promise<SharedChatApiResponse> {
  const response = await fetchImpl(_resolveChatEndpoint(host), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: payload.message,
      previous_state: payload.previousState ?? null,
      site_id: payload.siteId,
      access_token: payload.accessToken,
    }),
  });

  if (!response.ok) {
    throw new Error('shared chat request failed');
  }

  return _readJsonPayload(response) as Promise<SharedChatApiResponse>;
}

export function normalizeSharedChatResponse(payload: SharedChatApiResponse): SharedChatMessage[] {
  const messages: SharedChatMessage[] = [];
  const answer = payload.answer?.trim();
  const uiPayload = payload.ui_payload;

  if (answer) {
    messages.push({
      type: 'text',
      role: 'bot',
      text: answer,
    });
  }

  if (
    payload.ui_action_required === 'show_order_list' ||
    uiPayload?.type === 'order_list'
  ) {
    const orders = uiPayload?.ui_data;
    if (Array.isArray(orders) && orders.length > 0) {
      messages.push({
        type: 'order_list',
        role: 'bot',
        message: uiPayload?.message || '최근 주문 목록입니다.',
        orders: orders as SharedOrderData[],
        requiresSelection: Boolean(uiPayload?.requires_selection),
        prior_action: uiPayload?.prior_action,
        ui_config: uiPayload?.ui_config,
      });
    }
  }

  if (
    payload.ui_action_required === 'show_product_list' ||
    uiPayload?.type === 'product_list'
  ) {
    const products = uiPayload?.ui_data ?? payload.state?.search_context?.retrieved_products;
    if (Array.isArray(products) && products.length > 0) {
      messages.push({
        type: 'product_list',
        role: 'bot',
        message: uiPayload?.message || '추천 상품',
        products: products as UiProduct[],
      });
    }
  }

  return messages;
}

export async function streamSharedChatResponse(
  args: {
    host: SharedWidgetHostConfig;
    message: string;
    previousState?: Record<string, unknown> | null;
    resumePayload?: Record<string, unknown> | null;
    provider?: string | null;
    model?: string | null;
    bootstrap: SharedChatBootstrap;
    fetchImpl: FetchLike;
  },
  callbacks: SharedChatStreamHandlers = {},
): Promise<{ state: Record<string, unknown> | null }> {
  const response = await args.fetchImpl(_resolveStreamEndpoint(args.host), {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: args.message,
      previous_state: args.previousState ?? null,
      resume_payload: args.resumePayload ?? null,
      provider: args.provider ?? undefined,
      model: args.model ?? undefined,
      site_id: args.bootstrap.site_id,
      access_token: args.bootstrap.access_token,
    }),
  });

  if (!response.ok || !response.body?.getReader) {
    const errorText = response.text ? await response.text() : '';
    throw new Error(errorText || 'shared chat stream request failed');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let accumulatedText = '';
  let nextState = (args.previousState ?? null) as Record<string, unknown> | null;
  let sseBuffer = '';
  let hasUiActionEvent = false;
  let metadataUiActionHandled = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    sseBuffer += decoder.decode(value, { stream: true });
    const rawEvents = sseBuffer.split('\n\n');
    sseBuffer = rawEvents.pop() ?? '';

    for (const rawEvent of rawEvents) {
      const dataLines = rawEvent
        .split('\n')
        .filter((line) => line.startsWith('data: '))
        .map((line) => line.slice(6));

      if (dataLines.length === 0) {
        continue;
      }

      const data = JSON.parse(dataLines.join('\n'));

      if (data.type === 'metadata') {
        nextState = (data.state ?? nextState) as Record<string, unknown> | null;
        callbacks.onStateChange?.(nextState);

        if (
          !hasUiActionEvent &&
          !metadataUiActionHandled &&
          data.ui_action_required === 'show_product_list'
        ) {
          const products = data.state?.search_context?.retrieved_products;
          if (Array.isArray(products) && products.length > 0) {
            metadataUiActionHandled = true;
            callbacks.onMessage?.({
              type: 'product_list',
              role: 'bot',
              message: '비슷한 상품을 찾아드렸습니다.',
              products: products as UiProduct[],
            });
          }
        }
        continue;
      }

      if (data.type === 'text_chunk') {
        accumulatedText += String(data.content ?? '');
        callbacks.onStreamingText?.(accumulatedText);
        continue;
      }

      if (data.type === 'status_update') {
        callbacks.onStatusChange?.(
          typeof data.status === 'string' && data.status.trim().length > 0 ? data.status : null,
        );
        continue;
      }

      if (data.type === 'ui_action') {
        hasUiActionEvent = true;
        accumulatedText = '';
        callbacks.onStreamingText?.('');

        if (data.ui_action === 'show_product_list' || data.ui_action === 'product_list') {
          callbacks.onMessage?.({
            type: 'product_list',
            role: 'bot',
            message: data.message || '추천 상품',
            products: Array.isArray(data.ui_data) ? data.ui_data : [],
          });
        } else if (data.ui_action === 'show_order_list' || data.ui_action === 'order_list') {
          const uiConfig = data.ui_config || {};
          callbacks.onMessage?.({
            type: 'order_list',
            role: 'bot',
            message:
              String(data.message || '').trim() ||
              (uiConfig.enable_selection ?? data.requires_selection
                ? '최근 주문 목록입니다. 진행하실 주문을 선택해주세요.'
                : '최근 주문 목록입니다.'),
            orders: Array.isArray(data.ui_data) ? data.ui_data : [],
            requiresSelection: uiConfig.enable_selection ?? data.requires_selection,
            prior_action: data.prior_action ?? null,
            ui_config: uiConfig,
          });
        } else {
          callbacks.onUnhandledUiAction?.(data);
        }

        if (data.state) {
          nextState = data.state as Record<string, unknown>;
          callbacks.onStateChange?.(nextState);
        }
        continue;
      }

      if (data.type === 'done') {
        callbacks.onStatusChange?.(null);
        if (accumulatedText.trim()) {
          callbacks.onMessage?.({
            type: 'text',
            role: 'bot',
            text: accumulatedText,
            isStreaming: false,
          });
          callbacks.onStreamingText?.('');
        }
        continue;
      }

      if (data.type === 'error') {
        throw new Error(String(data.message || 'shared chat stream request failed'));
      }
    }
  }

  return { state: nextState };
}

type HostedChatbotWidgetProps = {
  host: SharedWidgetHostConfig;
  fetchImpl?: FetchLike;
  initialMessages?: SharedChatMessage[];
  capabilities?: SharedWidgetCapabilities;
  className?: string;
  messageListClassName?: string;
  inputPlaceholder?: string;
  sendLabel?: string;
};

export function HostedChatbotWidget({
  host,
  fetchImpl,
  initialMessages = [],
  capabilities,
  className,
  messageListClassName,
  inputPlaceholder = '메시지를 입력하세요',
  sendLabel = '전송',
}: HostedChatbotWidgetProps) {
  const effectiveFetch =
    fetchImpl ?? ((input, init) => fetch(input, init as RequestInit) as Promise<FetchLikeResponse>);
  const [status, setStatus] = React.useState<'loading' | 'unauthenticated' | 'authenticated' | 'error'>('loading');
  const [bootstrap, setBootstrap] = React.useState<SharedChatBootstrap | null>(null);
  const [messages, setMessages] = React.useState<SharedChatMessage[]>(initialMessages);
  const [conversationState, setConversationState] = React.useState<Record<string, unknown> | null>(null);
  const [input, setInput] = React.useState('');
  const [isSending, setIsSending] = React.useState(false);

  React.useEffect(() => {
    let active = true;

    async function bootstrapChatAuth() {
      try {
        const payload = await bootstrapSharedWidgetAuth(effectiveFetch, host);
        if (!active) {
          return;
        }
        if (!payload.authenticated) {
          setStatus('unauthenticated');
          return;
        }
        setBootstrap(payload);
        setStatus('authenticated');
      } catch (_error) {
        if (active) {
          setStatus('error');
        }
      }
    }

    bootstrapChatAuth();
    return () => {
      active = false;
    };
  }, [effectiveFetch, host]);

  const handleSend = async () => {
    const nextMessage = input.trim();
    if (!nextMessage || status !== 'authenticated' || !bootstrap || isSending) {
      return;
    }

    setInput('');
    setIsSending(true);
    setMessages((prev) => [...prev, { type: 'text', role: 'user', text: nextMessage }]);

    try {
      await streamSharedChatResponse(
        {
          host,
          message: nextMessage,
          previousState: conversationState,
          bootstrap,
          fetchImpl: effectiveFetch,
        },
        {
          onMessage(message) {
            setMessages((prev) => [...prev, message]);
          },
          onStateChange(state) {
            setConversationState(state);
          },
        },
      );
    } catch (_error) {
      setStatus('error');
    } finally {
      setIsSending(false);
    }
  };

  if (status === 'loading') {
    return <div data-chatbot-status="loading">Connecting chat...</div>;
  }
  if (status === 'unauthenticated') {
    return <div data-chatbot-status="unauthenticated">Login required for chat.</div>;
  }
  if (status === 'error') {
    return <div data-chatbot-status="error">Chat is temporarily unavailable.</div>;
  }

  return (
    <div
      data-chatbot-status="authenticated"
      data-site-id={bootstrap?.siteId || ''}
      data-chatbot-api-base={host.chatbotApiBase}
    >
      <ChatbotWidget
        messages={messages}
        capabilities={capabilities}
        className={className}
        messageListClassName={messageListClassName}
      />
      <div>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={inputPlaceholder}
        />
        <button type="button" onClick={handleSend} disabled={isSending}>
          {sendLabel}
        </button>
      </div>
    </div>
  );
}

export function ChatbotWidget<TMessage extends { type: string; role?: string }>({
  messages,
  capabilities,
  onOrderSelect,
  onProductSelect,
  renderTextMessage,
  renderOrderList,
  renderProductList,
  renderFallback,
  className,
  messageListClassName,
}: ChatbotWidgetProps<TMessage>) {
  const productPurchaseEnabled = _hasSharedWidgetCapability(capabilities, 'products_purchase');
  const messageKeyCounts = new Map<string, number>();

  return (
    <div className={[styles.widgetRoot, className].filter(Boolean).join(' ')}>
      <div className={[styles.widgetMessageList, messageListClassName].filter(Boolean).join(' ')}>
      {messages.map((message, index) => {
        const keyBase = _getStableMessageKey(message as TMessage & KeyedMessage & { type: string; role?: string });
        const occurrence = messageKeyCounts.get(keyBase) ?? 0;
        messageKeyCounts.set(keyBase, occurrence + 1);
        const renderKey = `${keyBase}:${occurrence}`;

        if (_isOrderListMessage(message)) {
          return (
            <React.Fragment key={renderKey}>
              {renderOrderList ? (
                renderOrderList(message, index)
              ) : (
                <OrderListUI
                  message={message.message}
                  orders={message.orders}
                  requiresSelection={message.requiresSelection}
                  prior_action={message.prior_action}
                  ui_config={message.ui_config}
                  onSelect={(selectedOrderIds) => onOrderSelect?.(selectedOrderIds, message)}
                />
              )}
            </React.Fragment>
          );
        }

        if (_isProductListMessage(message)) {
          return (
            <React.Fragment key={renderKey}>
              {productPurchaseEnabled && renderProductList ? (
                renderProductList(message, index)
              ) : (
                <ProductListUI
                  message={message.message}
                  products={message.products}
                  purchaseEnabled={productPurchaseEnabled}
                  onAddToCart={(productId) => {
                    const product = message.products.find((item) => item.id === productId);
                    if (product) {
                      onProductSelect?.(product, message);
                    }
                  }}
                />
              )}
            </React.Fragment>
          );
        }

        if (_isTextMessage(message)) {
          return (
            <React.Fragment key={renderKey}>
              {renderTextMessage ? (
                renderTextMessage(message, index)
              ) : message.role === 'user' ? (
                <span className={styles.widgetTextMessage}>{message.text}</span>
              ) : (
                <p className={styles.widgetTextMessage}>{message.text}</p>
              )}
            </React.Fragment>
          );
        }

        return (
          <React.Fragment key={renderKey}>
            {capabilities === undefined || capabilities === 'full'
              ? renderFallback?.(message, index) ?? null
              : null}
          </React.Fragment>
        );
      })}
      </div>
    </div>
  );
}

export default ChatbotWidget;
