import React, { useEffect, useMemo, useState } from "react";
import styles from "./orders.module.css";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

const ORDER_STATUS_MAP = {
  pending: "결제 대기",
  paid: "결제 완료",
  preparing: "상품 준비 중",
  shipping: "배송 중",
  shipped: "배송 완료",
  delivered: "배송 완료",
  cancelled: "주문 취소",
  refunded: "환불 완료",
};

const STATUS_COLOR_MAP = {
  pending: "#ff9800",
  paid: "#2196f3",
  preparing: "#9c27b0",
  shipping: "#00bcd4",
  shipped: "#3f51b5",
  delivered: "#4caf50",
  cancelled: "#f44336",
  refunded: "#795548",
};

const statusOptions = [
  "all",
  "pending",
  "paid",
  "preparing",
  "shipping",
  "shipped",
  "delivered",
  "cancelled",
  "refunded",
];

const Orders = () => {
  const [orders, setOrders] = useState([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [detailOrder, setDetailOrder] = useState(null);
  const [reviewOrder, setReviewOrder] = useState(null);
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewBody, setReviewBody] = useState("");

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    fetch(`${API_BASE}/api/orders/`)
      .then((response) => {
        if (!response.ok) {
          throw new Error("주문 정보를 불러오는 데 실패했습니다.");
        }
        return response.json();
      })
      .then((data) => {
        if (isMounted) {
          setOrders(
            data.map((order) => ({
              ...order,
              created_at: new Date(order.created_at),
            }))
          );
          setError(null);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const filteredOrders = useMemo(() => {
    if (statusFilter === "all") {
      return orders;
    }
    return orders.filter((order) => order.status === statusFilter);
  }, [orders, statusFilter]);

  const handleSubmitReview = () => {
    if (!reviewOrder) return;
    alert(
      `${reviewOrder.product.name} (${reviewRating}점) 리뷰가 저장되었습니다.\n내용: ${reviewBody}`
    );
    setReviewRating(0);
    setReviewBody("");
    setReviewOrder(null);
  };

  if (loading) {
    return (
      <section className={styles.wrapper}>
        <div className={styles.emptyState}>주문 정보를 불러오는 중입니다...</div>
      </section>
    );
  }

  if (error) {
    return (
      <section className={styles.wrapper}>
        <div className={styles.emptyState} style={{ color: "#c62828" }}>
          {error}
        </div>
      </section>
    );
  }

  return (
    <section className={styles.wrapper}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>주문 목록</h1>
        </div>
        <div className={styles.filterRow}>
          <label htmlFor="status-filter">상태:</label>
          <select
            id="status-filter"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            {statusOptions.map((option) => (
              <option key={option} value={option}>
                {option === "all" ? "전체" : ORDER_STATUS_MAP[option]}
              </option>
            ))}
          </select>
        </div>
      </header>

      {filteredOrders.length === 0 ? (
        <div className={styles.emptyState}>선택한 상태의 주문이 없습니다.</div>
      ) : (
        <div className={styles.ordersList}>
          {filteredOrders.map((order) => {
            const product = order.product || {};
            const orderItems = [
              {
                id: product.id,
                name: product.name,
                image: product.image_url,
                quantity: order.quantity,
                unitPrice: Number(product.price),
                subtotal: Number(order.total_price),
              },
            ];

            return (
              <article key={order.id} className={styles.orderCard}>
                <div className={styles.orderHeader}>
                  <div>
                    <p className={styles.label}>주문 번호</p>
                    <p className={styles.value}>{order.id}</p>
                  </div>
                  <div>
                    <p className={styles.label}>주문일</p>
                    <p className={styles.value}>
                      {order.created_at.toLocaleString("ko-KR", {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </p>
                  </div>
                  <div className={styles.statusWrapper}>
                    <span
                      className={styles.statusChip}
                      style={{ backgroundColor: STATUS_COLOR_MAP[order.status] }}
                    >
                      {ORDER_STATUS_MAP[order.status] || "알 수 없음"}
                    </span>
                  </div>
                </div>

                <div className={styles.orderItems}>
                  {orderItems.map((item) => (
                    <div key={item.id} className={styles.orderItem}>
                      <div className={styles.itemImage}>
                        <img
                        src={
                          item.image ||
                          "https://placehold.co/120x120?text=상품"
                        }
                          alt={item.name}
                        />
                      </div>
                      <div className={styles.itemInfo}>
                        <p className={styles.itemName}>{item.name}</p>
                        <p className={styles.itemMeta}>
                          {item.quantity}개 · {item.unitPrice.toLocaleString()}원
                        </p>
                      </div>
                      <div className={styles.itemSubtotal}>
                        {item.subtotal.toLocaleString()}원
                      </div>
                    </div>
                  ))}
                </div>

                <div className={styles.orderSummary}>
                  <div className={styles.summaryRow}>
                    <span>상품 합계</span>
                    <strong>{orderItems[0].subtotal.toLocaleString()}원</strong>
                  </div>
                  <div className={`${styles.summaryRow} ${styles.totalRow}`}>
                    <span>총 결제 금액</span>
                    <strong>{Number(order.total_price).toLocaleString()}원</strong>
                  </div>
                </div>

                <div className={styles.orderActions}>
                  <button
                    className={styles.primaryButton}
                    onClick={() => setDetailOrder(order)}
                  >
                    상세 보기
                  </button>
                  {order.status === "delivered" && (
                    <button
                      className={styles.primaryButton}
                      onClick={() => {
                        setReviewOrder(order);
                        setReviewRating(0);
                        setReviewBody("");
                      }}
                    >
                      리뷰 작성
                    </button>
                  )}
                  {["paid", "preparing", "shipping"].includes(order.status) && (
                    <button
                      className={styles.cancelButton}
                      onClick={() =>
                        alert(`${order.id}번 주문 취소 요청을 서버에 보냈습니다.`)
                      }
                    >
                      주문 취소
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {detailOrder && (
        <div className={styles.modalOverlay} onClick={() => setDetailOrder(null)}>
          <div
            className={styles.modalContent}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <h2>주문 상세</h2>
              <button
                className={styles.modalClose}
                onClick={() => setDetailOrder(null)}
              >
                닫기
              </button>
            </div>
            <p className={styles.modalRow}>
              주문 번호: <strong>{detailOrder.id}</strong>
            </p>
            <p className={styles.modalRow}>
              주문 상태:{" "}
              <strong style={{ color: STATUS_COLOR_MAP[detailOrder.status] }}>
                {ORDER_STATUS_MAP[detailOrder.status]}
              </strong>
            </p>
            <p className={styles.modalRow}>
              상품명: <strong>{detailOrder.product?.name}</strong>
            </p>
            <p className={styles.modalRow}>
              수량: <strong>{detailOrder.quantity}개</strong>
            </p>
            <p className={styles.modalRow}>
              총액: <strong>{Number(detailOrder.total_price).toLocaleString()}원</strong>
            </p>
          </div>
        </div>
      )}

      {reviewOrder && (
        <div className={styles.modalOverlay} onClick={() => setReviewOrder(null)}>
          <div
            className={styles.modalContent}
            onClick={(event) => event.stopPropagation()}
          >
            <div className={styles.modalHeader}>
              <h2>리뷰 남기기</h2>
              <button
                className={styles.modalClose}
                onClick={() => setReviewOrder(null)}
              >
                닫기
              </button>
            </div>
            <p className={styles.modalRow}>
              주문번호: <strong>{reviewOrder.id}</strong>
            </p>
            <div className={styles.starRating}>
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  key={star}
                  type="button"
                  className={`${styles.star} ${
                    star <= reviewRating ? styles.starActive : ""
                  }`}
                  onClick={() => setReviewRating(star)}
                >
                  ★
                </button>
              ))}
            </div>
            <textarea
              className={styles.reviewTextarea}
              placeholder="리뷰를 남겨주세요."
              value={reviewBody}
              onChange={(event) => setReviewBody(event.target.value)}
            />
            <div className={styles.modalActions}>
              <button
                type="button"
                className={styles.outlinedButton}
                onClick={() => setReviewOrder(null)}
              >
                취소
              </button>
              <button
                type="button"
                className={styles.primaryButton}
                onClick={handleSubmitReview}
                disabled={reviewRating === 0 || reviewBody.trim().length === 0}
              >
                제출
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default Orders;
