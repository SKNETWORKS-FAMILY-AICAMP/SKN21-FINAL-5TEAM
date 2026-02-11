import React from 'react';
import styles from './chatbotfab.module.css';

type OrderData = {
  order_id: string;
  date: string;
  status: string;
  status_label?: string;  // 한글 상태명
  product_name: string;
  amount: number;
  delivered_at?: string | null;
  can_cancel?: boolean;
  can_return?: boolean;
  can_exchange?: boolean;
};

type OrderListUIProps = {
  message: string;
  orders: OrderData[];
  onSelect: (selectedOrderIds: string[]) => void;
};

export default function OrderListUI({ message, orders, onSelect }: OrderListUIProps) {
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());

  const toggleOrder = (orderId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(orderId)) {
        next.delete(orderId);
      } else {
        next.add(orderId);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    onSelect(Array.from(selectedIds));
  };

  return (
    <div className={styles.orderListContainer}>
      <p className={styles.orderListMessage}>{message}</p>
      <div className={styles.orderCards}>
        {orders.map((order) => (
          <label key={order.order_id} className={styles.orderCard}>
            <input
              type="checkbox"
              checked={selectedIds.has(order.order_id)}
              onChange={() => toggleOrder(order.order_id)}
              className={styles.orderCheckbox}
            />
            <div className={styles.orderContent}>
              <div className={styles.orderHeader}>
                <span className={styles.orderId}>주문번호: {order.order_id}</span>
                <span className={styles.orderStatus}>{order.status_label || order.status}</span>
              </div>
              <div className={styles.orderProduct}>{order.product_name}</div>
              <div className={styles.orderMeta}>
                <span>주문일: {order.date}</span>
                <span className={styles.orderAmount}>
                  {order.amount.toLocaleString()}원
                </span>
              </div>
              {order.delivered_at && (
                <div className={styles.orderDelivered}>배송완료: {order.delivered_at}</div>
              )}
              <div className={styles.orderActions}>
                {order.can_cancel && <span className={styles.actionBadge}>취소가능</span>}
                {order.can_return && <span className={styles.actionBadge}>환불가능</span>}
                {order.can_exchange && <span className={styles.actionBadge}>교환가능</span>}
              </div>
            </div>
          </label>
        ))}
      </div>
      <button
        type="button"
        className={styles.confirmBtn}
        onClick={handleConfirm}
        disabled={selectedIds.size === 0}
      >
        선택 완료 ({selectedIds.size}건)
      </button>
    </div>
  );
}
