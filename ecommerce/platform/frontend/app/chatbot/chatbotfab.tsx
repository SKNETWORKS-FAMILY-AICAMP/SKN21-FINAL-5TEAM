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

export default function ChatbotFab() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([
    { role: 'bot', type: 'text', text: '안녕하세요. MOYEO 챗봇입니다.' },
  ]);
  const [conversationState, setConversationState] = useState<Record<string, unknown> | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

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

  const toggle = () => setOpen((v) => !v);

  const sendMessage = async (textOverride?: string, hidden: boolean = false) => {
    const text = typeof textOverride === 'string' ? textOverride : input.trim();
    if (!text || isLoading) return;

    // 사용자 메시지 추가 (hidden이 아닐 때만)
    if (!hidden) {
      setMessages((prev) => [...prev, { role: 'user', type: 'text', text }]);
    }
    
    setInput('');
    setIsLoading(true);
    setStatusMessage(null); // 초기화

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
        method: 'POST',
        credentials: 'include',
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

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let accumulatedText = '';
      let newState = null;
      let botMessageAdded = false;

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
                if (!botMessageAdded) {
                  // 첫 텍스트 청크 수신 시 로딩바 제거 (텍스트 작성 중에는 로딩바 안 보이게)
                  setIsLoading(false);
                  setStatusMessage(null); // 텍스트 나오면 상태 메시지 제거
                  
                  botMessageAdded = true;
                  setMessages((prev) => [
                    ...prev,
                    { role: 'bot', type: 'text', text: data.content }
                  ]);
                  accumulatedText = data.content;
                } else {
                  accumulatedText += data.content;
                  setMessages((prev) => {
                    const newMessages = [...prev];
                    const lastMsg = newMessages[newMessages.length - 1];
                    // 안전장치: 마지막 메시지가 봇 메시지인지 확인 (혹시 모를 Race Condition 방지)
                    if (lastMsg && lastMsg.role === 'bot' && lastMsg.type === 'text') {
                      lastMsg.text = accumulatedText;
                    }
                    return newMessages;
                  });
                }
              } else if (data.type === 'status_update') {
                  // 도구 실행 상태 메시지 업데이트
                  setStatusMessage(data.status);
              } else if (data.type === 'ui_action') {
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
      setStatusMessage(null);
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
    
    // sendConfirm 대신 sendMessage 사용 (hidden=true로 메시지 숨김)
    sendMessage(`주문 ${orderIdString}를 선택했어`, true);
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



  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === 'Enter' && !isLoading) sendMessage();
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
                    requiresSelection={m.requiresSelection}
                  />
                </div>
              );
            } else if (m.type === 'address_search') {
              return (
                <div key={i} className={`${styles.msgRow} ${styles.botRow}`}>
                  <div className={styles.bubble}>
                    {m.message}
                    <div style={{ marginTop: '10px' }}>
                      <button 
                        className={styles.confirmBtn}
                        onClick={openAddressSearch}
                      >
                        주소 입력하기
                      </button>
                    </div>
                    {/* 안내 메시지 추가 */}
                    <div style={{ fontSize: '12px', color: '#666', marginTop: '5px' }}>
                      * 주소 선택 후 상세 주소(동/호수)를 입력해주세요.
                    </div>
                  </div>
                </div>
              );
            }
            return (
              <div
                key={i}
                className={`${styles.msgRow} ${m.role === 'user' ? styles.userRow : styles.botRow}`}
              >
                <div className={styles.bubble}>{'text' in m ? m.text : m.message}</div>
              </div>
            );
          })}
          
          {/* 로딩 인디케이터 또는 상태 메시지 표시 */}
          {(isLoading || statusMessage) && (
            <div className={`${styles.msgRow} ${styles.botRow}`}>
              <div className={styles.bubble}>
                {statusMessage ? (
                  <div className={styles.statusMessage}>
                    <span className={styles.spinnerSmall}></span>
                    {statusMessage}
                  </div>
                ) : (
                  <div className={styles.typingIndicator}>
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <div className={styles.inputBar}>
          <input
            ref={inputRef}
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
