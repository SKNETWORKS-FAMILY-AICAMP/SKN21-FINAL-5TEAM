from __future__ import annotations

import json

from .shared_chatbot_assets import SharedChatbotAssetConfig


def build_default_react_shared_widget(config: SharedChatbotAssetConfig) -> str:
    auth_bootstrap_path = json.dumps(config.auth_bootstrap_path)
    stream_path = json.dumps(config.stream_path)
    chatbot_api_base_default = json.dumps(config.chatbot_api_base_default)
    return f"""'use client';

import React, {{ useEffect, useState }} from 'react';

const sharedWidgetHost = {{
  authBootstrapPath: {auth_bootstrap_path},
  streamPath: {stream_path},
  chatbotApiBase:
    (typeof window !== 'undefined' && window.__CHATBOT_API_BASE__) ||
    (typeof process !== 'undefined' &&
      process.env &&
      (process.env.REACT_APP_CHATBOT_API_BASE || process.env.NEXT_PUBLIC_CHATBOT_API_BASE)) ||
    {chatbot_api_base_default},
}};

function buildTextMessage(role, text) {{
  return {{ type: 'text', role, text }};
}}

function buildProductListMessage(message, items) {{
  return {{ type: 'product_list', role: 'bot', message, items }};
}}

function buildOrderListMessage(message, items) {{
  return {{ type: 'order_list', role: 'bot', message, items }};
}}

function resolveStreamUrl() {{
  return `${{sharedWidgetHost.chatbotApiBase.replace(/\\/$/, '')}}${{sharedWidgetHost.streamPath}}`;
}}

function renderOrderLabel(order) {{
  if (!order || typeof order !== 'object') {{
    return '주문 항목';
  }}
  return order.order_number || order.product_name || order.status || order.id || '주문 항목';
}}

function renderProductLabel(product) {{
  if (!product || typeof product !== 'object') {{
    return '추천 상품';
  }}
  return product.name || product.title || product.id || '추천 상품';
}}

export default function SharedChatbotWidget() {{
  const [status, setStatus] = useState('loading');
  const [bootstrap, setBootstrap] = useState(null);
  const [messages, setMessages] = useState([]);
  const [conversationState, setConversationState] = useState(null);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [sendError, setSendError] = useState('');

  useEffect(() => {{
    let cancelled = false;

    async function bootstrapChat() {{
      try {{
        const response = await fetch(sharedWidgetHost.authBootstrapPath, {{
          method: 'POST',
          credentials: 'include',
        }});
        const rawBody = await response.text();
        const payload = rawBody ? JSON.parse(rawBody) : {{}};
        if (!response.ok || !payload.authenticated) {{
          if (!cancelled) {{
            setStatus('unauthenticated');
          }}
          return;
        }}
        if (!cancelled) {{
          setBootstrap({{
            siteId: payload.site_id || '',
            accessToken: payload.access_token || '',
          }});
          setStatus('authenticated');
        }}
      }} catch (_error) {{
        if (!cancelled) {{
          setStatus('error');
        }}
      }}
    }}

    bootstrapChat();
    return () => {{
      cancelled = true;
    }};
  }}, []);

  async function handleSend() {{
    const nextMessage = input.trim();
    if (!nextMessage || !bootstrap || status !== 'authenticated' || isSending) {{
      return;
    }}

    setInput('');
    setIsSending(true);
    setSendError('');
    setStreamingText('');
    setMessages((previous) => [...previous, buildTextMessage('user', nextMessage)]);

    let nextState = conversationState;
    let accumulatedText = '';
    let eventBuffer = '';

    try {{
      const response = await fetch(resolveStreamUrl(), {{
        method: 'POST',
        credentials: 'include',
        headers: {{
          'Content-Type': 'application/json',
        }},
        body: JSON.stringify({{
          message: nextMessage,
          previous_state: conversationState,
          site_id: bootstrap.siteId,
          access_token: bootstrap.accessToken,
        }}),
      }});

      if (!response.ok || !response.body || !response.body.getReader) {{
        const detail = response.text ? await response.text() : '';
        throw new Error(detail || 'shared chat stream request failed');
      }}

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {{
        const {{ done, value }} = await reader.read();
        if (done) {{
          break;
        }}

        eventBuffer += decoder.decode(value, {{ stream: true }});
        const rawEvents = eventBuffer.split('\\n\\n');
        eventBuffer = rawEvents.pop() || '';

        for (const rawEvent of rawEvents) {{
          const dataLines = rawEvent
            .split('\\n')
            .filter((line) => line.startsWith('data: '))
            .map((line) => line.slice(6));

          if (dataLines.length === 0) {{
            continue;
          }}

          const data = JSON.parse(dataLines.join('\\n'));

          if (data.type === 'text_chunk') {{
            accumulatedText += String(data.content || '');
            setStreamingText(accumulatedText);
            continue;
          }}

          if (data.type === 'metadata' && data.state) {{
            nextState = data.state;
            setConversationState(data.state);
            continue;
          }}

          if (data.type === 'ui_action') {{
            if (data.state) {{
              nextState = data.state;
              setConversationState(data.state);
            }}
            if (data.ui_action === 'show_product_list' || data.ui_action === 'product_list') {{
              setMessages((previous) => [
                ...previous,
                buildProductListMessage(data.message || '추천 상품', Array.isArray(data.ui_data) ? data.ui_data : []),
              ]);
              continue;
            }}
            if (data.ui_action === 'show_order_list' || data.ui_action === 'order_list') {{
              setMessages((previous) => [
                ...previous,
                buildOrderListMessage(data.message || '최근 주문 목록입니다.', Array.isArray(data.ui_data) ? data.ui_data : []),
              ]);
              continue;
            }}
          }}

          if (data.type === 'error') {{
            throw new Error(String(data.message || 'shared chat stream request failed'));
          }}
        }}
      }}

      if (accumulatedText.trim()) {{
        setMessages((previous) => [...previous, buildTextMessage('bot', accumulatedText.trim())]);
      }}
      setConversationState(nextState);
    }} catch (_error) {{
      setSendError('Chat is temporarily unavailable.');
    }} finally {{
      setStreamingText('');
      setIsSending(false);
    }}
  }}

  if (status === 'loading') {{
    return <div data-chatbot-status="loading">Connecting chat...</div>;
  }}
  if (status === 'unauthenticated') {{
    return <div data-chatbot-status="unauthenticated">Login required for chat.</div>;
  }}
  if (status === 'error') {{
    return <div data-chatbot-status="error">Chat is temporarily unavailable.</div>;
  }}

  return (
    <div
      data-chatbot-status="authenticated"
      data-site-id={{bootstrap?.siteId || ''}}
      data-chatbot-api-base={{sharedWidgetHost.chatbotApiBase}}
    >
      <div>
        {{messages.map((message, index) => {{
          if (message.type === 'product_list') {{
            return (
              <div key={{`product-${{index}}`}} data-chatbot-role="bot">
                <p>{{message.message}}</p>
                <ul>
                  {{(message.items || []).map((item, itemIndex) => (
                    <li key={{`product-item-${{index}}-${{itemIndex}}`}}>{{renderProductLabel(item)}}</li>
                  ))}}
                </ul>
              </div>
            );
          }}
          if (message.type === 'order_list') {{
            return (
              <div key={{`order-${{index}}`}} data-chatbot-role="bot">
                <p>{{message.message}}</p>
                <ul>
                  {{(message.items || []).map((item, itemIndex) => (
                    <li key={{`order-item-${{index}}-${{itemIndex}}`}}>{{renderOrderLabel(item)}}</li>
                  ))}}
                </ul>
              </div>
            );
          }}
          return (
            <p key={{`text-${{index}}`}} data-chatbot-role={{message.role || 'bot'}}>
              {{message.text}}
            </p>
          );
        }})}}
        {{streamingText ? (
          <p data-chatbot-role="bot" data-streaming="true">
            {{streamingText}}
          </p>
        ) : null}}
      </div>
      {{sendError ? <div data-chatbot-send-error="true">{{sendError}}</div> : null}}
      <div>
        <input
          value={{input}}
          onChange={{(event) => setInput(event.target.value)}}
          placeholder="메시지를 입력하세요"
        />
        <button type="button" onClick={{handleSend}} disabled={{isSending}}>
          {{isSending ? '전송 중...' : '전송'}}
        </button>
      </div>
    </div>
  );
}}
"""
