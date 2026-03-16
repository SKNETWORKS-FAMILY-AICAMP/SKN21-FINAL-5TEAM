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

type UiConfig = {
  enable_refund_button?: boolean;
  enable_exchange_button?: boolean;
  enable_cancel_button?: boolean;
  enable_selection?: boolean;
  selectable_statuses?: string[];
  action_label?: string;
};

type OrderListUIProps = {
  message: string;
  orders: OrderData[];
  onSelect: (selectedOrderIds: string[]) => void;
  requiresSelection?: boolean;
  prior_action?: string | null;
  ui_config?: UiConfig;
};

export default function OrderListUI({ message, orders, onSelect, requiresSelection = false, prior_action, ui_config }: OrderListUIProps) {
  const safeOrders = orders ?? [];
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = React.useState(false);  // 선택 완료 상태

  // ui_config가 있으면 그걸 우선 사용, 없으면 prior_action → requiresSelection 폴백
  const showSelection = ui_config?.enable_selection ?? requiresSelection;
  const showRefundBtn = ui_config?.enable_refund_button;
  const showExchangeBtn = ui_config?.enable_exchange_button;
  const showCancelBtn = ui_config?.enable_cancel_button;
  const selectableStatuses = ui_config?.selectable_statuses;

  // prior_action에 따라 action_label 동적 생성
  const actionLabelMap: Record<string, string> = {
    refund:   `환불할 주문 선택 완료 (${selectedIds.size}건)`,
    exchange: `교환할 주문 선택 완료 (${selectedIds.size}건)`,
    cancel:   `취소할 주문 선택 완료 (${selectedIds.size}건)`,
    review:   `리뷰 작성할 주문 선택 완료 (${selectedIds.size}건)`,
  };
  const actionLabel =
    ui_config?.action_label ||
    (prior_action ? actionLabelMap[prior_action] : null) ||
    `선택 완료 (${selectedIds.size}건)`;

  // prior_action 기반 배지 표시 여부 (ui_config 없을 때 사용)
  const showRefundBadge  = !ui_config && (prior_action === 'refund'   || prior_action == null);
  const showExchangeBadge = !ui_config && (prior_action === 'exchange' || prior_action == null);
  const showCancelBadge  = !ui_config && (prior_action === 'cancel'   || prior_action == null);

  const isSelectable = (order: OrderData) => {
    if (!selectableStatuses) return true;
    return selectableStatuses.includes(order.status);
  };

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
    if (selectedIds.size > 0) {
      setConfirmed(true);  // 선택 완료 표시
      onSelect(Array.from(selectedIds));
    }
  };

  return (
    <div className={styles.orderListContainer}>
      <p className={styles.orderListMessage}>{message}</p>
      <div className={styles.orderCards}>
        {safeOrders.map((order) => (
          <div key={order.order_id} className={styles.orderCard}>
            {showSelection && (
              <input
                type="checkbox"
                checked={selectedIds.has(order.order_id)}
                onChange={() => toggleOrder(order.order_id)}
                className={styles.orderCheckbox}
                disabled={confirmed || !isSelectable(order)}  // 선택 불가 상태 비활성화
              />
            )}
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
                {/* ui_config 기반 동적 버튼 (있을 때) */}
                {showRefundBtn && order.can_return && <span className={styles.actionBadge}>환불가능</span>}
                {showExchangeBtn && order.can_exchange && <span className={styles.actionBadge}>교환가능</span>}
                {showCancelBtn && order.can_cancel && <span className={styles.actionBadge}>취소가능</span>}
                {/* prior_action 기반 배지 (ui_config 없을 때) */}
                {showCancelBadge  && order.can_cancel   && <span className={styles.actionBadge}>취소가능</span>}
                {showRefundBadge  && order.can_return    && <span className={styles.actionBadge}>환불가능</span>}
                {showExchangeBadge && order.can_exchange && <span className={styles.actionBadge}>교환가능</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
      {showSelection && (
        <button
          type="button"
          className={styles.confirmBtn}
          onClick={handleConfirm}
          disabled={selectedIds.size === 0 || confirmed}
        >
          {confirmed ? '선택 완료됨' : actionLabel}
        </button>
      )}
    </div>
  );
}
