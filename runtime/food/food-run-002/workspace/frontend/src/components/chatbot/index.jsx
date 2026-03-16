import React, { useEffect, useRef, useState } from "react";
import styles from "./chatbot.module.css";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

const STATUS_LABELS = {
  preparing: "상품 준비 중",
  shipping: "배송 중",
  delivered: "배송 완료",
  cancelled: "주문 취소",
  refunded: "환불 완료",
};

const PAYMENT_STATUS_LABELS = {
  pending: "결제 대기",
  paid: "결제 완료",
};

const translateStatus = (status) => STATUS_LABELS[status] ?? "알 수 없음";
const translatePaymentStatus = (status) =>
  PAYMENT_STATUS_LABELS[status] ?? "알 수 없음";

const extractOrderId = (text) => {
  const match = text.match(/(\d+)/);
  if (!match) {
    return null;
  }
  const id = Number(match[1]);
  return Number.isNaN(id) ? null : id;
};

const Chatbot = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [messages, setMessages] = useState([]);
  const [orders, setOrders] = useState([]);
  const [ordersLoading, setOrdersLoading] = useState(true);
  const [ordersError, setOrdersError] = useState(null);
  const messageAreaRef = useRef(null);
  const botTimeoutRef = useRef(null);

  useEffect(() => {
    let isMounted = true;

    const loadOrders = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/orders/`);
        if (!response.ok) {
          throw new Error("주문 정보를 불러오는 데 실패했습니다.");
        }
        const data = await response.json();
        if (isMounted) {
          setOrders(data);
          setOrdersError(null);
        }
      } catch (error) {
        if (isMounted) {
          setOrdersError(
            error?.message ?? "주문 정보를 가져오지 못했습니다."
          );
        }
      } finally {
        if (isMounted) {
          setOrdersLoading(false);
        }
      }
    };

    loadOrders();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (botTimeoutRef.current) {
        clearTimeout(botTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!messageAreaRef.current) {
      return;
    }
    messageAreaRef.current.scrollTop = messageAreaRef.current.scrollHeight;
  }, [messages, isOpen]);

  const findOrder = (orderId) => {
    if (orderId) {
      const matched = orders.find((order) => order.id === orderId);
      if (matched) {
        return matched;
      }
    }
    return orders[0] ?? null;
  };

  const updateOrderList = (updatedOrder) => {
    setOrders((prev) => {
      const index = prev.findIndex((order) => order.id === updatedOrder.id);
      if (index >= 0) {
        const next = [...prev];
        next[index] = updatedOrder;
        return next;
      }
      return [updatedOrder, ...prev];
    });
  };

  const fetchOrderDetail = async (orderId) => {
    const response = await fetch(`${API_BASE}/api/orders/${orderId}/`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.detail ?? "주문 상세를 가져오지 못했습니다.");
    }
    return payload;
  };

  const performOrderAction = async (orderId, action) => {
    const response = await fetch(`${API_BASE}/api/orders/${orderId}/actions/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ action }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload?.detail ?? "서버 요청 중 오류가 발생했습니다.");
    }
    if (payload?.order) {
      updateOrderList(payload.order);
    }
    return payload;
  };

  const describeOrderStatus = (order) => {
    if (!order) {
      return "현재 조회 가능한 주문이 없습니다.";
    }
    return `주문 ${order.id}은 ${translateStatus(
      order.status
    )} 상태이며, 결제는 ${translatePaymentStatus(
      order.payment_status
    )}입니다.`;
  };

  const handleOrderAction = async (action, text) => {
    const orderId = extractOrderId(text);
    const target = findOrder(orderId);
    if (!target) {
      return "처리할 주문이 없습니다. 주문 번호를 알려주세요.";
    }
    try {
      const payload = await performOrderAction(target.id, action);
      return (
        payload?.message ??
        `주문 ${target.id}에 대해 '${action}' 요청을 처리했습니다.`
      );
    } catch (error) {
      return error?.message ?? "요청을 처리하는 중 문제가 발생했습니다.";
    }
  };

  const handleDeliveryStatus = async (text) => {
    const orderId = extractOrderId(text);
    const target = findOrder(orderId);
    if (!target) {
      return "조회할 주문이 없습니다. 주문 번호를 알려주세요.";
    }
    try {
      const detail = await fetchOrderDetail(target.id);
      updateOrderList(detail);
      return describeOrderStatus(detail);
    } catch (error) {
      return error?.message ?? "배송 상태를 확인하는 중 오류가 발생했습니다.";
    }
  };

  const buildBotReply = async (text) => {
    if (ordersLoading) {
      return "주문 정보를 불러오는 중입니다. 잠시만 기다려 주세요.";
    }
    if (ordersError) {
      return `주문 서버와 연결할 수 없습니다: ${ordersError}`;
    }

    const normalized = text.toLowerCase();

    if (normalized.includes("결제")) {
      return handleOrderAction("pay", text);
    }
    if (normalized.includes("취소")) {
      return handleOrderAction("cancel", text);
    }
    if (normalized.includes("환불")) {
      return handleOrderAction("refund", text);
    }
    if (normalized.includes("배송")) {
      return handleDeliveryStatus(text);
    }
    if (normalized.includes("주문")) {
      return describeOrderStatus(findOrder(extractOrderId(text)));
    }
    if (normalized.includes("안녕") || normalized.includes("hi")) {
      return "안녕하세요! 결제, 주문 취소, 환불, 배송 문의를 도와드릴 수 있어요.";
    }

    return "죄송합니다. 주문/결제/배송 관련된 요청을 알려주시면 도움을 드릴게요.";
  };

  const sendMessage = () => {
    const trimmed = inputValue.trim();
    if (!trimmed) {
      return;
    }

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setInputValue("");

    if (botTimeoutRef.current) {
      clearTimeout(botTimeoutRef.current);
    }
    botTimeoutRef.current = setTimeout(() => {
      buildBotReply(trimmed)
        .then((reply) => {
          setMessages((prev) => [...prev, { role: "bot", text: reply }]);
        })
        .catch((error) => {
          setMessages((prev) => [
            ...prev,
            {
              role: "bot",
              text:
                error?.message ??
                "죄송합니다. 응답을 준비하는 중 오류가 발생했습니다.",
            },
          ]);
        });
    }, 500);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Enter") {
      sendMessage();
    }
  };

  return (
    <div className={styles.chatbotWrapper}>
      {isOpen && (
        <div className={styles.chatbotWindow}>
          <div className={styles.chatbotHeader}>
            <span>YAAM 챗봇</span>
            <button
              className={styles.chatbotClose}
              onClick={() => setIsOpen(false)}
              aria-label="챗봇 닫기"
            >
              ×
            </button>
          </div>
          <div className={styles.chatbotMessages} ref={messageAreaRef}>
            <div className={styles.chatbotWelcome}>
              안녕하세요! 무엇을 도와드릴까요?
            </div>
            {messages.map((msg, index) => {
              const messageClass =
                styles.chatbotMessage +
                " " +
                (msg.role === "user" ? styles.msgUser : styles.msgBot);
              return (
                <div key={msg.role + "-" + index} className={messageClass}>
                  {msg.text}
                </div>
              );
            })}
          </div>
          <div className={styles.chatbotInputArea}>
            <input
              type="text"
              className={styles.chatbotInput}
              placeholder="메시지를 입력하세요"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              onKeyDown={handleKeyDown}
            />
            <button
              className={styles.chatbotSend}
              type="button"
              onClick={sendMessage}
            >
              전송
            </button>
          </div>
        </div>
      )}
      <button
        className={styles.chatbotFab}
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label={isOpen ? "챗봇 닫기" : "챗봇 열기"}
      >
        {isOpen ? "×" : "💬"}
      </button>
    </div>
  );
};

export default Chatbot;
