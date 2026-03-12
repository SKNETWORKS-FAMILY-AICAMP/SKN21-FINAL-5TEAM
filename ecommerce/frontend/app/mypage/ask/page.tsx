'use client';

import { useState } from 'react';
import styles from './ask.module.css';

/* ===== 타입 ===== */
interface Message {
  sender: 'user' | 'ai';
  text: string;
  time: string;
}

interface Room {
  id: number;
  title: string;
  messages: Message[];
}

/* ===== 유틸 ===== */
const now = () =>
  new Date().toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  });

const initialAiMessage: Message = {
  sender: 'ai',
  text: '안녕하세요. SK옷 챗봇입니다.\n무엇을 도와드릴까요.',
  time: now(),
};

export default function AskPage() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState('');
  const [deleteMode, setDeleteMode] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);

  const activeRoom = rooms.find((r) => r.id === activeId);

  /* ===== 새 문의 ===== */
  const createRoom = () => {
    const room: Room = {
      id: Date.now(),
      title: '새 1:1 문의',
      messages: [initialAiMessage],
    };
    setRooms([room, ...rooms]);
    setActiveId(room.id);
    setDeleteMode(false);
    setSelected([]);
  };

  /* ===== 삭제 ===== */
  const toggleSelect = (id: number) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]
    );
  };

  const deleteRooms = () => {
    setRooms(rooms.filter((r) => !selected.includes(r.id)));
    setSelected([]);
    setDeleteMode(false);
    setActiveId(null);
  };

  /* ===== AI 응답 ===== */
  const aiReply = (text: string) => {
    if (text.includes('배송')) {
      return '배송 지연으로 불편을 드려 죄송합니다.\n현재 택배사 확인 후 안내드리겠습니다.';
    }
    if (text.includes('교환') || text.includes('환불')) {
      return '교환/반품은 마이페이지 주문내역에서 신청 가능합니다.\n필요 시 상담사 연결을 눌러주세요.';
    }
    return '문의 내용을 확인했습니다.\n상담사 연결을 원하시면 버튼을 눌러주세요.';
  };

  /* ===== 전송 ===== */
  const sendMessage = () => {
    if (!input.trim() || !activeRoom) return;

    const userMsg: Message = {
      sender: 'user',
      text: input,
      time: now(),
    };

    const aiMsg: Message = {
      sender: 'ai',
      text: aiReply(input),
      time: now(),
    };

    setRooms(
      rooms.map((r) =>
        r.id === activeRoom.id
          ? { ...r, messages: [...r.messages, userMsg, aiMsg] }
          : r
      )
    );
    setInput('');
  };

  return (
    <div className={styles.layout}>
      {/* ===== 좌측 ===== */}
      <aside className={styles.sidebar}>
        <div className={styles.search}>
          <input placeholder="대화방 프로필명 검색" />
        </div>

        <ul className={styles.roomList}>
          {rooms.map((room) => (
            <li
              key={room.id}
              className={`${styles.roomItem} ${activeId === room.id ? styles.active : ''
                }`}
              onClick={() => !deleteMode && setActiveId(room.id)}
            >
              {deleteMode && (
                <input
                  type="checkbox"
                  checked={selected.includes(room.id)}
                  onChange={() => toggleSelect(room.id)}
                />
              )}
              <span>{room.title}</span>
            </li>
          ))}
        </ul>

        <div className={styles.sidebarFooter}>
          <button onClick={() => setDeleteMode(!deleteMode)}>🗑</button>
          {deleteMode ? (
            <button onClick={deleteRooms}>삭제</button>
          ) : (
            <button onClick={createRoom}>1:1 문의하기 &gt;</button>
          )}
        </div>
      </aside>

      {/* ===== 우측 ===== */}
      <section className={styles.chat}>
        {activeRoom ? (
          <>
            <header className={styles.chatHeader}>
              <div>
                <h2>1:1 문의</h2>
                <p>보통 40분 내 응답 · 응답률 100%</p>
              </div>
              <button className={styles.agentBtn}>상담사 연결</button>
            </header>

            <div className={styles.chatBody}>
              {activeRoom.messages.map((m, i) => (
                <div
                  key={i}
                  className={
                    m.sender === 'user'
                      ? styles.userMessage
                      : styles.aiMessage
                  }
                >
                  <div className={styles.bubble}>
                    {m.text.split('\n').map((t, idx) => (
                      <p key={idx}>{t}</p>
                    ))}
                    <span className={styles.time}>{m.time}</span>
                  </div>
                </div>
              ))}
            </div>

            <footer className={styles.inputArea}>
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="메시지를 입력하세요."
                onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
              />
              <button onClick={sendMessage}>보내기</button>
            </footer>
          </>
        ) : (
          <div className={styles.empty}>대화내역이 없습니다.</div>
        )}
      </section>
    </div>
  );
}
