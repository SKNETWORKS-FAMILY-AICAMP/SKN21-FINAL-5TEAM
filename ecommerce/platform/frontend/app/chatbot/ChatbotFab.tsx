'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import styles from './ChatbotFab.module.css';

type ChatMsg = { role: 'user' | 'bot'; text: string };

function isLoggedInSimple() {
  // ✅ 임시 로그인 판별 (사장님 프로젝트 상황에 맞춰 나중에 교체)
  // 1) localStorage에 "access_token" 같은게 있으면 로그인으로 간주
  // 2) 또는 쿠키 기반이면 여기 로직을 cookie 체크로 교체
  try {
    return !!localStorage.getItem('access_token');
  } catch {
    return false;
  }
}

export default function ChatbotFab() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<ChatMsg[]>([
    { role: 'bot', text: '안녕하세요. MOYEO 챗봇입니다.' },
  ]);

  const loggedIn = useMemo(() => isLoggedInSimple(), []);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // 메시지 추가될 때 항상 아래로 스크롤
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages, open]);

  const toggle = () => setOpen((v) => !v);

  const send = () => {
    const text = input.trim();
    if (!text) return;

    setMessages((prev) => [...prev, { role: 'user', text }]);
    setInput('');

    // 🔐 로그인 안했으면: 유저가 질문 보낸 “후” 봇이 응답으로 안내
    if (!loggedIn) {
      setMessages((prev) => [
        ...prev,
        { role: 'bot', text: '로그인 후 이용 가능합니다.' },
      ]);
      return;
    }

    // ✅ 로그인 했을 때: (임시) 더미 답변
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        { role: 'bot', text: '접수했습니다. (추후 AI/백엔드 연동 예정)' },
      ]);
    }, 200);
  };

  const onKeyDown: React.KeyboardEventHandler<HTMLInputElement> = (e) => {
    if (e.key === 'Enter') send();
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
          {messages.map((m, i) => (
            <div
              key={i}
              className={`${styles.msgRow} ${m.role === 'user' ? styles.userRow : styles.botRow}`}
            >
              <div className={styles.bubble}>{m.text}</div>
            </div>
          ))}
        </div>

        <div className={styles.inputBar}>
          <input
            className={styles.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="메시지를 입력하세요"
          />
          <button type="button" className={styles.sendBtn} onClick={send}>
            전송
          </button>
        </div>
      </aside>
    </>
  );
}
