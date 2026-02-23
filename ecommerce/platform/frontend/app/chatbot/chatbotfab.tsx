'use client';

import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import styles from './chatbotfab.module.css';
import OrderListUI from './OrderListUI';
import { useAuth } from '../authcontext';

type TextMessage = { role: 'user' | 'bot'; type: 'text'; text: string; isStreaming?: boolean; showDivider?: boolean };
type OrderListMessage = {
  role: 'bot';
  type: 'order_list';
  message: string;
  orders: Array<{
    order_id: string;
    date: string;
    status: string;
    status_label?: string;  // 한글 상태명
    product_name: string;
    amount: number;
    delivered_at?: string | null;
    can_exchange?: boolean;
  }>;
  requiresSelection?: boolean;
};


type ConfirmationMessage = {
  role: 'bot';
  type: 'confirmation';
  message: string;
};

type AddressSearchMessage = {
  role: 'bot';
  type: 'address_search';
  message: string;
};

type ChatMsg = TextMessage | OrderListMessage | ConfirmationMessage | AddressSearchMessage;

declare global {
  interface Window {
    daum: any;
  }
}

const API_BASE_URL = 'http://localhost:8000';

const MIN_W = 340;
const MIN_H = 420;
const MAX_W = 800;
const MAX_H = 900;

function AnimatedText({ text, className, speed = 20 }: { text: string; className?: string; speed?: number }) {
  const [displayed, setDisplayed] = useState('');

  useEffect(() => {
    if (!text) {
      setDisplayed('');
      return;
    }

    // 텍스트가 완전히 바뀐 경우 자연스럽게 처음부터 다시 표시
    setDisplayed((prev) => (text.startsWith(prev) ? prev : ''));

    const timer = window.setInterval(() => {
      setDisplayed((prev) => {
        if (prev.length >= text.length) return prev;
        const remaining = text.length - prev.length;
        const step = remaining > 24 ? 3 : remaining > 12 ? 2 : 1;
        return text.slice(0, prev.length + step);
      });
    }, speed);

    return () => window.clearInterval(timer);
  }, [text, speed]);

  return <span className={className}>{displayed}</span>;
}

export default function ChatbotFab() {
  const { isLoggedIn } = useAuth();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([
    { role: 'bot', type: 'text', text: '안녕하세요. MOYEO 챗봇입니다.' },
  ]);
  const [conversationState, setConversationState] = useState<Record<string, unknown> | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState('');
  const listRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const [panelSize, setPanelSize] = useState({ w: 400, h: 560 });
  const isResizing = useRef(false);

  useEffect(() => {
    // 메시지 추가될 때 항상 아래로 스크롤
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, open, statusMessage]);

  useEffect(() => {
    // Daum Postcode Script Load
    const script = document.createElement('script');
    script.src = '//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js';
    script.async = true;
    document.body.appendChild(script);

    return () => {
      if (document.body.contains(script)) {
        document.body.removeChild(script);
      }
    };
  }, []);

  /* ===== 리사이즈 드래그 핸들러 ===== */
  const onResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    const startX = e.clientX;
    const startY = e.clientY;
    const startW = panelSize.w;
    const startH = panelSize.h;

    const onMouseMove = (ev: MouseEvent) => {
      if (!isResizing.current) return;
      // 좌상단 핸들이므로: 왼쪽으로 가면 넓어지고, 위로 가면 높아짐
      const newW = Math.min(MAX_W, Math.max(MIN_W, startW - (ev.clientX - startX)));
      const newH = Math.min(MAX_H, Math.max(MIN_H, startH - (ev.clientY - startY)));
      setPanelSize({ w: newW, h: newH });
    };

    const onMouseUp = () => {
      isResizing.current = false;
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  };

  const toggle = () => setOpen((v) => !v);

  const sendMessage = async (textOverride?: string, hidden: boolean = false) => {
    const text = typeof textOverride === 'string' ? textOverride : input.trim();
    if (!text || isLoading) return;

    // 로그인 체크
    if (!isLoggedIn) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'bot',
          type: 'text',
          text: '챗봇을 사용하려면 로그인이 필요합니다. 로그인 후 다시 시도해주세요.',
        },
      ]);
      return;
    }

    // 사용자 메시지 추가 (hidden이 아닐 때만)
    if (!hidden) {
      setMessages((prev) => [...prev, { role: 'user', type: 'text', text }]);
    }
    
    setInput('');
    setIsLoading(true);
    setStatusMessage(null); // 초기화
    setStreamingText('');

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          previous_state: conversationState,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text();
        console.error('API Response Error:', response.status, errorText);
        throw new Error(`API Error: ${response.status} - ${errorText}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let accumulatedText = '';
      let newState = null;

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = JSON.parse(line.slice(6));

              if (data.type === 'metadata') {
                // 상태 저장
                newState = data.state;
              } else if (data.type === 'text_chunk') {
                setIsLoading(false);
                accumulatedText += data.content;
                setStreamingText(accumulatedText);
              } else if (data.type === 'status_update') {
                  // 백엔드에서 전달되는 실시간 노드/모델 상태 메시지 업데이트
                  const composedStatus =
                    typeof data.status === 'string' && data.status.trim().length > 0
                      ? data.status
                      : typeof data.node === 'string' && data.node.trim().length > 0
                      ? `${data.node} 노드를 처리하고 있습니다...`
                      : typeof data.model === 'string' && data.model.trim().length > 0
                      ? `모델 응답을 생성하고 있습니다... (${data.model})`
                      : null;

                  if (composedStatus) {
                    setStatusMessage(composedStatus);
                  }
              } else if (data.type === 'ui_action') {
                if (accumulatedText.trim()) {
                  const completedText = accumulatedText;
                  setMessages((prev) => [
                    ...prev,
                    { role: 'bot', type: 'text', text: completedText, isStreaming: false, showDivider: true },
                  ]);
                }
                accumulatedText = '';
                setStreamingText('');

                if (data.ui_action === 'show_order_list') {
                  setIsLoading(false);
                  setStatusMessage(null);
                  setMessages((prev) => [
                    ...prev,
                    {
                      role: 'bot',
                      type: 'order_list',
                      message: '주문 목록입니다.',
                      orders: data.ui_data,
                      requiresSelection: data.requires_selection,
                    },
                  ]);
                } else if (data.ui_action === 'show_address_search') {
                    setIsLoading(false);
                    setStatusMessage(null);
                    setMessages((prev) => [
                      ...prev,
                      {
                        role: 'bot',
                        type: 'address_search',
                        message: data.message || '주소 검색 버튼을 눌러주세요.',
                      },
                    ]);
                }
                
                newState = data.state;
                if (newState) setConversationState(newState);
              } else if (data.type === 'done') {
                if (newState) setConversationState(newState);
                setStatusMessage(null); // 완료 시 상태 메시지 확실히 제거
                if (accumulatedText.trim()) {
                  const completedText = accumulatedText;
                  setMessages((prev) => [
                    ...prev,
                    { role: 'bot', type: 'text', text: completedText, isStreaming: false, showDivider: true },
                  ]);
                }
                setStreamingText('');
              } else if (data.type === 'error') {
                throw new Error(data.message);
              }
            }
          }
        }
      }
    } catch (error) {
      console.error('Chat API error:', error);
      setStatusMessage(null);
      setStreamingText('');
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

  const handleOrderSelect = (selectedOrderIds: string[]) => {
    if (selectedOrderIds.length === 0) return;

    // State만 업데이트 - 그래프 실행 안 함
    const orderIdString = selectedOrderIds.join(', ');
    
    setConversationState((prev) => ({
      ...prev,
      order_id: orderIdString,
    }));

    // 선택 이벤트를 구조화된 JSON으로 전송 (백엔드 deterministic 파싱)
    const inferredAction =
      typeof conversationState?.current_task === 'object' &&
      conversationState?.current_task !== null &&
      'type' in conversationState.current_task
        ? String((conversationState.current_task as Record<string, unknown>).type)
        : null;

    const selectionPayload = {
      event: 'order_selected',
      selected_order_id: selectedOrderIds[0],
      selected_order_ids: selectedOrderIds,
      action: inferredAction,
      source: 'order_list_ui',
    };

    // 사용자 채팅에는 숨기고 상태 전송만 수행
    sendMessage(JSON.stringify(selectionPayload), true);
  };

  const openAddressSearch = () => {
    if (!window.daum || !window.daum.Postcode) {
      alert("주소 검색 서비스를 불러오는 중입니다. 잠시만 기다려주세요.");
      return;
    }
    
    new window.daum.Postcode({
      oncomplete: function(data: any) {
        // 도로명 주소
        let fullAddr = data.roadAddress;
        let extraAddr = '';

        // 법정동명이 있을 경우 추가한다. (법정리는 제외)
        // 법정동의 경우 마지막 문자가 "동/로/가"로 끝난다.
        if(data.bname !== '' && /[동|로|가]$/g.test(data.bname)){
            extraAddr += data.bname;
        }
        // 건물명이 있고, 공동주택일 경우 추가한다.
        if(data.buildingName !== '' && data.apartment === 'Y'){
            extraAddr += (extraAddr !== '' ? ', ' + data.buildingName : data.buildingName);
        }
        // 표시할 참고항목이 있을 경우, 괄호까지 추가한 최종 문자열을 만든다.
        if(extraAddr !== ''){
            extraAddr = ' (' + extraAddr + ')';
        }
        // 조합된 참고항목을 해당 필드에 넣는다.
        fullAddr += extraAddr;
        
        // [MODIFIED] 자동으로 전송하지 않고, 입력창에 채워넣음
        setInput(fullAddr + ' '); // 뒤에 상세주소 입력 편하게 공백 추가
        inputRef.current?.focus(); // 입력창 포커스
      }
    }).open();
  };



  const onKeyDown: React.KeyboardEventHandler<HTMLTextAreaElement> = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !isLoading) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <>
      {/* ✅ 우측 하단 원형 버튼 */}
      <button type="button" className={styles.fab} onClick={toggle} aria-label="챗봇 열기">
        💬
      </button>

      {/* ✅ 슬라이드 업 패널 */}
      <aside
        ref={panelRef}
        className={`${styles.panel} ${open ? styles.open : ''}`}
        aria-hidden={!open}
        style={{ width: panelSize.w, height: panelSize.h }}
      >
        {/* 좌상단 리사이즈 핸들 */}
        <div className={styles.resizeHandle} onMouseDown={onResizeStart} />

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
                    requiresSelection={m.requiresSelection}
                  />
                </div>
              );
            } else if (m.type === 'address_search') {
              return (
                <div key={i} className={`${styles.msgRow} ${styles.botRow}`}>
                  <div className={styles.botMsg}>
                    <span className={styles.botIcon}>✦</span>
                    <div className={styles.botText}>
                      {m.message}
                      <div style={{ marginTop: '10px' }}>
                        <button
                          className={styles.confirmBtn}
                          onClick={openAddressSearch}
                        >
                          주소 입력하기
                        </button>
                      </div>
                      <div style={{ fontSize: '12px', color: '#999', marginTop: '5px' }}>
                        * 주소 선택 후 상세 주소(동/호수)를 입력해주세요.
                      </div>
                    </div>
                  </div>
                </div>
              );
            } else if (m.role === 'user') {
              return (
                <div key={i} className={`${styles.msgRow} ${styles.userRow}`}>
                  <div className={styles.bubble}>
                    {m.type === 'text' && <ReactMarkdown>{m.text}</ReactMarkdown>}
                  </div>
                </div>
              );
            } else {
              const text = m.type === 'text' ? m.text : m.message;
              return (
                <div key={i} className={`${styles.msgRow} ${styles.botRow}`}>
                  <div className={styles.botMsg}>
                    <span className={styles.botIcon}>✦</span>
                    <div
                      className={`${styles.botText} ${
                        m.type === 'text' && m.isStreaming ? styles.streaming : ''
                      } ${m.type === 'text' && m.showDivider ? styles.persistentDivider : ''}`}
                    >
                      {m.type === 'text' ? <ReactMarkdown>{text}</ReactMarkdown> : text}
                    </div>
                  </div>
                </div>
              );
            }
          })}
          
          {/* 생성 중 상태 + 스트리밍 프리뷰 */}
          {(isLoading || statusMessage || streamingText) && (
            <div className={`${styles.msgRow} ${styles.botRow}`}>
              <div className={styles.botMsg}>
                <span className={styles.botIcon}>✦</span>
                <div className={styles.botText}>
                  {statusMessage ? (
                    <div className={styles.statusMessageSoft}>
                      <span className={styles.spinnerSmall}></span>
                      <AnimatedText text={statusMessage} className={styles.statusTypewriter} speed={28} />
                    </div>
                  ) : isLoading && !streamingText ? (
                    <div className={styles.statusMessageSoft}>
                      <span className={styles.spinnerSmall}></span>
                    </div>
                  ) : null}

                  {streamingText && (
                    <div className={styles.streamingPreviewWrap}>
                      <div className={styles.streamingPreviewText}>
                        <AnimatedText text={streamingText} speed={14} />
                      </div>
                    </div>
                  )}

                </div>
              </div>
            </div>
          )}
        </div>

        <div className={styles.inputBar}>
          <textarea
            ref={inputRef}
            className={styles.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="메시지를 입력하세요"
            disabled={isLoading}
            rows={1}
          />
          <button
            type="button"
            className={styles.sendBtn}
            onClick={() => sendMessage()}
            disabled={isLoading}
          >
            전송
          </button>
        </div>
      </aside>
    </>
  );
}
