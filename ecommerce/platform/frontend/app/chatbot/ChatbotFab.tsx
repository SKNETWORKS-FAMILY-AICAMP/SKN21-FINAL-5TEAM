'use client';

import { useEffect, useRef, useState } from 'react';
import styles from './chatbotfab.module.css';
import OrderListUI from './OrderListUI';

type TextMessage = { role: 'user' | 'bot'; type: 'text'; text: string };
type OrderListMessage = {
  role: 'bot';
  type: 'order_list';
  message: string;
  orders: Array<{
    order_id: string;
    date: string;
    status: string;
    product_name: string;
    amount: number;
    delivered_at?: string | null;
    can_cancel?: boolean;
    can_return?: boolean;
    can_exchange?: boolean;
  }>;
};

type ChatMsg = TextMessage | OrderListMessage;

const API_BASE_URL = 'http://localhost:8000';

export default function ChatbotFab() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([
    { role: 'bot', type: 'text', text: '안녕하세요. MOYEO 챗봇입니다.' },
  ]);
  const [conversationState, setConversationState] = useState<Record<string, unknown> | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // 메시지 추가될 때 항상 아래로 스크롤
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, open]);

  const toggle = () => setOpen((v) => !v);

  const send = async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    // 사용자 메시지 추가
    setMessages((prev) => [...prev, { role: 'user', type: 'text', text }]);
    setInput('');
    setIsLoading(true);

    try {
      // API 호출
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          user_id: 'guest',
          previous_state: conversationState,
        }),
      });

      if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
      }

      const data = await response.json();

      // 상태 업데이트
      setConversationState(data.state);

      // UI 액션 처리
      if (data.ui_action === 'show_order_list' && data.ui_data) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'bot',
            type: 'order_list',
            message: data.answer || '주문 목록입니다.',
            orders: data.ui_data,
          },
        ]);
      } else if (data.answer) {
        // 일반 텍스트 응답
        setMessages((prev) => [
          ...prev,
          { role: 'bot', type: 'text', text: data.answer },
        ]);
      }
    } catch (error) {
      console.error('Chat API error:', error);
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          type: 'text',
          text: '죄송합니다. 오류가 발생했습니다. 다시 시도해주세요.',
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOrderSelect = async (selectedOrderIds: string[]) => {
    if (selectedOrderIds.length === 0) return;

    const text = `선택한 주문: ${selectedOrderIds.join(', ')}`;
    setMessages((prev) => [...prev, { role: 'user', type: 'text', text }]);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          user_id: 'guest',
          previous_state: conversationState,
        }),
      });

      if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
      }

      const data = await response.json();
      setConversationState(data.state);

      if (data.answer) {
        setMessages((prev) => [
          ...prev,
          { role: 'bot', type: 'text', text: data.answer },
        ]);
      }
    } catch (error) {
      console.error('Chat API error:', error);
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          type: 'text',
          text: '죄송합니다. 오류가 발생했습니다. 다시 시도해주세요.',
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === 'Enter' && !isLoading) send();
  };

  return (
    <>
      {/* ✅ 우측 하단 원형 버튼 */}
      <button type="button" className={styles.fab} onClick={toggle} aria-label="챗봇 열기">
        💬
      </button>

      {/* ✅ 슬라이드 업 패널 */}
      <aside className={`${styles.panel} ${open ? styles.open : ''}`} aria-hidden={!open}>
        <header className={styles.panelHeader}>
          <div className={styles.title}>MOYEO 챗봇</div>
          <button type="button" className={styles.closeBtn} onClick={toggle} aria-label="닫기">
            ✕
          </button>
        </header>

        <div className={styles.msgList} ref={listRef}>
          {messages.map((m, i) => {
            if (m.type === 'order_list') {
              return (
                <div key={i} className={`${styles.msgRow} ${styles.botRow}`}>
                  <OrderListUI
                    message={m.message}
                    orders={m.orders}
                    onSelect={handleOrderSelect}
                  />
                </div>
              );
            }
            return (
              <div
                key={i}
                className={`${styles.msgRow} ${m.role === 'user' ? styles.userRow : styles.botRow}`}
              >
                <div className={styles.bubble}>{m.text}</div>
              </div>
            );
          })}
          {isLoading && (
            <div className={`${styles.msgRow} ${styles.botRow}`}>
              <div className={styles.bubble}>...</div>
            </div>
          )}
        </div>

        <div className={styles.inputBar}>
          <input
            className={styles.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="메시지를 입력하세요"
            disabled={isLoading}
          />
          <button
            type="button"
            className={styles.sendBtn}
            onClick={send}
            disabled={isLoading}
          >
            전송
          </button>
        </div>
      </aside>
    </>
  );
}
