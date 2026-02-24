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

type AddressSelectionPayload = {
  event: 'address_selected';
  action?: string | null;
  source: 'address_search_ui';
  address: {
    road_address: string | null;
    jibun_address: string | null;
    post_code: string | null;
    detail_address: string;
    full_address: string;
  };
};

type ChatMsg = TextMessage | OrderListMessage | ConfirmationMessage | AddressSearchMessage;
type LlmProvider = 'openai' | 'huggingface';
type ModelOption = { id: string; provider: LlmProvider; label: string };

type DaumPostcodeData = {
  roadAddress?: string;
  jibunAddress?: string;
  zonecode?: string;
};

declare global {
  interface Window {
    daum?: {
      Postcode: new (options: { oncomplete: (data: DaumPostcodeData) => void }) => {
        open: () => void;
      };
    };
  }
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;

const OPENAI_MODELS = ['gpt-4o-mini', 'gpt-5-mini', 'gpt-5.2'] as const;
const HF_MODELS = ['Qwen/Qwen3-0.6B', 'Qwen/Qwen2.5-1.5B-Instruct'] as const;

const MODEL_OPTIONS: ModelOption[] = [
  ...OPENAI_MODELS.map((id) => ({ id, provider: 'openai' as const, label: id })),
  ...HF_MODELS.map((id) => ({ id, provider: 'huggingface' as const, label: id })),
];

function resolveProviderByModel(modelId: string): LlmProvider {
  if (HF_MODELS.includes(modelId as (typeof HF_MODELS)[number])) {
    return 'huggingface';
  }
  return 'openai';
}

const MIN_W = 340;
const MIN_H = 420;
const MAX_W = 800;
const MAX_H = 900;
type ResizeMode = 'corner' | 'left' | 'top';

function AnimatedText({ text, className, speed = 20 }: { text: string; className?: string; speed?: number }) {
  const [displayed, setDisplayed] = useState('');

  useEffect(() => {
    if (!text) return;

    // 텍스트가 완전히 바뀐 경우 자연스럽게 처음부터 다시 표시 (동기 setState 회피)
    const resetTimer = window.setTimeout(() => {
      setDisplayed((prev) => (text.startsWith(prev) ? prev : ''));
    }, 0);

    const timer = window.setInterval(() => {
      setDisplayed((prev) => {
        if (prev.length >= text.length) return prev;
        const remaining = text.length - prev.length;
        const step = remaining > 24 ? 3 : remaining > 12 ? 2 : 1;
        return text.slice(0, prev.length + step);
      });
    }, speed);

    return () => {
      window.clearTimeout(resetTimer);
      window.clearInterval(timer);
    };
  }, [text, speed]);

  return <span className={className}>{text ? displayed : ''}</span>;
}

function parseThinkContent(rawText: string): { hasThink: boolean; reasoning: string; answer: string } {
  if (!rawText || !rawText.includes('<think>')) {
    return { hasThink: false, reasoning: '', answer: rawText };
  }

  const thinkOpenIdx = rawText.indexOf('<think>');
  const thinkCloseIdx = rawText.indexOf('</think>');

  if (thinkOpenIdx < 0) {
    return { hasThink: false, reasoning: '', answer: rawText };
  }

  const beforeThink = rawText.slice(0, thinkOpenIdx).trim();
  if (thinkCloseIdx > thinkOpenIdx) {
    const reasoning = rawText.slice(thinkOpenIdx + '<think>'.length, thinkCloseIdx).trim();
    const afterThink = rawText.slice(thinkCloseIdx + '</think>'.length).trim();
    return {
      hasThink: true,
      reasoning,
      answer: [beforeThink, afterThink].filter(Boolean).join('\n\n').trim(),
    };
  }

  const reasoningOnly = rawText.slice(thinkOpenIdx + '<think>'.length).trim();
  return {
    hasThink: true,
    reasoning: reasoningOnly,
    answer: beforeThink,
  };
}

function ReasoningAccordion({ reasoning, isStreaming }: { reasoning: string; isStreaming?: boolean }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className={styles.reasoningWrap}>
      <button
        type="button"
        className={`${styles.reasoningToggle} ${isOpen ? styles.reasoningToggleOpen : ''}`}
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
      >
        <span className={styles.reasoningToggleText}>
          {isStreaming ? '추론 과정 생성 중...' : '생각 과정 보기'}
        </span>
        <span className={`${styles.reasoningChevron} ${isOpen ? styles.reasoningChevronOpen : ''}`}>⌄</span>
      </button>

      <div className={`${styles.reasoningPanel} ${isOpen ? styles.reasoningPanelOpen : ''}`}>
        <div className={styles.reasoningInner}>
          {isStreaming ? (
            <AnimatedText text={reasoning} className={styles.reasoningStreamingText} speed={10} />
          ) : (
            <ReactMarkdown>{reasoning}</ReactMarkdown>
          )}
        </div>
      </div>
    </div>
  );
}

function BotTextContent({ text, isStreaming = false }: { text: string; isStreaming?: boolean }) {
  const parsed = parseThinkContent(text);

  if (!parsed.hasThink) {
    return isStreaming ? <AnimatedText text={text} speed={14} /> : <ReactMarkdown>{text}</ReactMarkdown>;
  }

  return (
    <>
      <ReasoningAccordion reasoning={parsed.reasoning} isStreaming={isStreaming} />
      {parsed.answer ? (
        <div className={styles.finalAnswerWrap}>
          <ReactMarkdown>{parsed.answer}</ReactMarkdown>
        </div>
      ) : null}
    </>
  );
}

function AddressSearchCard({
  message,
  disabled,
  onSubmit,
}: {
  message: string;
  disabled: boolean;
  onSubmit: (payload: AddressSelectionPayload) => void;
}) {
  const [roadAddress, setRoadAddress] = useState('');
  const [jibunAddress, setJibunAddress] = useState('');
  const [postCode, setPostCode] = useState('');
  const [detailAddress, setDetailAddress] = useState('');

  const openSearch = () => {
    if (!window.daum || !window.daum.Postcode) {
      alert('주소 검색 서비스를 불러오는 중입니다. 잠시만 기다려주세요.');
      return;
    }

    new window.daum.Postcode({
      oncomplete: (data: DaumPostcodeData) => {
        const selectedRoadAddress = typeof data.roadAddress === 'string' ? data.roadAddress.trim() : '';
        const selectedJibunAddress = typeof data.jibunAddress === 'string' ? data.jibunAddress.trim() : '';
        const selectedPostCode = typeof data.zonecode === 'string' ? data.zonecode.trim() : '';

        setRoadAddress(selectedRoadAddress);
        setJibunAddress(selectedJibunAddress);
        setPostCode(selectedPostCode);
      },
    }).open();
  };

  const submitAddress = () => {
    const baseAddress = (roadAddress || jibunAddress).trim();
    const detail = detailAddress.trim();

    if (!baseAddress) {
      alert('먼저 주소 검색으로 메인 주소를 선택해주세요.');
      return;
    }

    if (!detail) {
      alert('상세 주소를 입력해주세요.');
      return;
    }

    const fullAddress = `${baseAddress} ${detail}`.trim();

    onSubmit({
      event: 'address_selected',
      source: 'address_search_ui',
      address: {
        road_address: roadAddress || null,
        jibun_address: jibunAddress || null,
        post_code: postCode || null,
        detail_address: detail,
        full_address: fullAddress,
      },
    });
  };

  return (
    <div className={styles.addressCard}>
      <div className={styles.addressCardTitle}>{message}</div>

      <button type="button" className={styles.confirmBtn} onClick={openSearch} disabled={disabled}>
        주소 검색하기
      </button>

      <div className={styles.addressFieldGroup}>
        <div className={styles.addressFieldLabel}>우편번호</div>
        <div className={styles.addressFieldValue}>{postCode || '-'}</div>
      </div>

      <div className={styles.addressFieldGroup}>
        <div className={styles.addressFieldLabel}>도로명주소</div>
        <div className={styles.addressFieldValue}>{roadAddress || '-'}</div>
      </div>

      <div className={styles.addressFieldGroup}>
        <div className={styles.addressFieldLabel}>지번주소</div>
        <div className={styles.addressFieldValue}>{jibunAddress || '-'}</div>
      </div>

      <div className={styles.addressFieldGroup}>
        <div className={styles.addressFieldLabel}>상세주소</div>
        <input
          type="text"
          className={styles.addressInput}
          value={detailAddress}
          onChange={(e) => setDetailAddress(e.target.value)}
          placeholder="동/호수 등 상세주소를 입력하세요"
          disabled={disabled}
        />
      </div>

      <button type="button" className={styles.addressSubmitBtn} onClick={submitAddress} disabled={disabled}>
        주소 정보 전송
      </button>
    </div>
  );
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
  const [panelSize, setPanelSize] = useState({ w: 550, h: 660 });
  const isResizing = useRef(false);
  const [selectedModel, setSelectedModel] = useState<string>(OPENAI_MODELS[0]);
  const [isModelModalOpen, setIsModelModalOpen] = useState(false);

  useEffect(() => {
    const storedModel = localStorage.getItem('chatbot_llm_model');

    if (storedModel && MODEL_OPTIONS.some((m) => m.id === storedModel)) {
      setSelectedModel(storedModel);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('chatbot_llm_model', selectedModel);
  }, [selectedModel]);

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

  useEffect(() => {
    const handleEscKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;

      if (isModelModalOpen) {
        setIsModelModalOpen(false);
        return;
      }

      if (open) {
        setOpen(false);
      }
    };

    window.addEventListener('keydown', handleEscKey);
    return () => window.removeEventListener('keydown', handleEscKey);
  }, [isModelModalOpen, open]);

  const handlePanelWheelCapture: React.WheelEventHandler<HTMLElement> = (e) => {
    // 챗봇 위에서의 휠 이벤트가 페이지(배경)까지 전파되지 않도록 차단
    e.stopPropagation();
  };

  /* ===== 리사이즈 드래그 핸들러 ===== */
  const onResizeStart = (e: React.MouseEvent, mode: ResizeMode) => {
    e.preventDefault();
    isResizing.current = true;
    const startX = e.clientX;
    const startY = e.clientY;
    const startW = panelSize.w;
    const startH = panelSize.h;

    const onMouseMove = (ev: MouseEvent) => {
      if (!isResizing.current) return;
      const deltaX = ev.clientX - startX;
      const deltaY = ev.clientY - startY;

      if (mode === 'left') {
        const newW = Math.min(MAX_W, Math.max(MIN_W, startW - deltaX));
        setPanelSize((prev) => ({ ...prev, w: newW }));
        return;
      }

      if (mode === 'top') {
        const newH = Math.min(MAX_H, Math.max(MIN_H, startH - deltaY));
        setPanelSize((prev) => ({ ...prev, h: newH }));
        return;
      }

      // corner
      const newW = Math.min(MAX_W, Math.max(MIN_W, startW - deltaX));
      const newH = Math.min(MAX_H, Math.max(MIN_H, startH - deltaY));
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
      const provider = resolveProviderByModel(selectedModel);
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: text,
          previous_state: conversationState,
          provider,
          model: selectedModel,
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
                      message: '최근 30일간의 주문 목록입니다.',
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

  const getInferredAction = () => {
    if (
      typeof conversationState?.current_task === 'object' &&
      conversationState?.current_task !== null &&
      'type' in conversationState.current_task
    ) {
      return String((conversationState.current_task as Record<string, unknown>).type);
    }
    return null;
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
    const inferredAction = getInferredAction();

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

  const handleAddressSubmit = (payload: AddressSelectionPayload) => {
    const inferredAction = getInferredAction();
    const finalPayload: AddressSelectionPayload = {
      ...payload,
      action: inferredAction,
    };

    setMessages((prev) => [
      ...prev,
      {
        role: 'bot',
        type: 'text',
        text: `주소 정보를 전달했습니다.\n- 우편번호: ${payload.address.post_code ?? '-'}\n- 주소: ${payload.address.full_address}`,
      },
    ]);

    // 사용자 채팅에는 숨기고 구조화된 이벤트 JSON만 백엔드로 전달
    sendMessage(JSON.stringify(finalPayload), true);
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
        onWheelCapture={handlePanelWheelCapture}
      >
        {/* 리사이즈 핸들: 좌측/상단/좌상단 */}
        <div className={styles.resizeHandleLeft} onMouseDown={(e) => onResizeStart(e, 'left')} />
        <div className={styles.resizeHandleTop} onMouseDown={(e) => onResizeStart(e, 'top')} />
        <div className={styles.resizeHandleCorner} onMouseDown={(e) => onResizeStart(e, 'corner')} />

        <header className={styles.panelHeader}>
          <div className={styles.title}>MOYEO AI 고객상담사</div>

          <button type="button" className={styles.closeBtn} onClick={toggle} aria-label="닫기">
            ✕
          </button>
        </header>

        <div className={styles.msgList} ref={listRef}>
          {messages.map((m, i) => {
            if (m.type === 'order_list') {
              return (
                <div key={i} className={`${styles.msgRow} ${styles.botRow}`}>
                  <div className={styles.botMsg}>
                    <span className={styles.botIcon}>✦</span>
                    <div className={styles.botText}>
                      <OrderListUI
                        message={m.message}
                        orders={m.orders}
                        onSelect={handleOrderSelect}
                        requiresSelection={m.requiresSelection}
                      />
                    </div>
                  </div>
                </div>
              );
            } else if (m.type === 'address_search') {
              return (
                <div key={i} className={`${styles.msgRow} ${styles.botRow}`}>
                  <div className={styles.botMsg}>
                    <span className={styles.botIcon}>✦</span>
                    <div className={styles.botText}>
                      <AddressSearchCard
                        message={m.message}
                        disabled={isLoading}
                        onSubmit={handleAddressSubmit}
                      />
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
                      {m.type === 'text' ? <BotTextContent text={text} isStreaming={Boolean(m.isStreaming)} /> : text}
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
                        <BotTextContent text={streamingText} isStreaming />
                      </div>
                    </div>
                  )}

                </div>
              </div>
            </div>
          )}
        </div>

        <div className={styles.bottomControls}>
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

          <div className={styles.modelPickerRow}>
            <button
              type="button"
              className={styles.modelPickerBtn}
              onClick={() => setIsModelModalOpen((prev) => !prev)}
              disabled={isLoading}
              aria-label="모델 선택 열기"
              title={`현재 모델: ${selectedModel}`}
            >
              {selectedModel} ▾
            </button>

            {isModelModalOpen && (
              <div className={styles.modelDropdown}>
                <div className={styles.modelDropdownTitle}>Model</div>
                <div className={styles.modelDropdownList}>
                  {MODEL_OPTIONS.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      className={`${styles.modelOptionBtn} ${selectedModel === option.id ? styles.modelOptionBtnActive : ''}`}
                      onClick={() => {
                        setSelectedModel(option.id);
                        setIsModelModalOpen(false);
                      }}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
