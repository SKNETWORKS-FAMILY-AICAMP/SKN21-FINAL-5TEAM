import React from 'react';

export type SharedOrderData = {
  order_id: string;
  date: string;
  status: string;
  status_label?: string;
  product_name: string;
  amount: number;
  delivered_at?: string | null;
  can_cancel?: boolean;
  can_return?: boolean;
  can_exchange?: boolean;
};

export type SharedOrderUiConfig = {
  enable_refund_button?: boolean;
  enable_exchange_button?: boolean;
  enable_cancel_button?: boolean;
  enable_selection?: boolean;
  selectable_statuses?: string[];
  action_label?: string;
};

export type OrderListUIClassNames = Partial<{
  orderListContainer: string;
  orderListMessage: string;
  orderCards: string;
  orderCard: string;
  orderCheckbox: string;
  orderContent: string;
  orderHeader: string;
  orderId: string;
  orderStatus: string;
  orderProduct: string;
  orderMeta: string;
  orderAmount: string;
  orderDelivered: string;
  orderActions: string;
  actionBadge: string;
  confirmBtn: string;
  confirmationContainer: string;
  confirmationMessage: string;
  confirmationActions: string;
  confirmationApproveBtn: string;
  confirmationRejectBtn: string;
}>;

type OrderListUIProps = {
  message: string;
  orders: SharedOrderData[];
  onSelect: (selectedOrderIds: string[]) => void;
  requiresSelection?: boolean;
  prior_action?: string | null;
  ui_config?: SharedOrderUiConfig;
  classNames?: OrderListUIClassNames;
};

export default function OrderListUI({
  message,
  orders,
  onSelect,
  requiresSelection = false,
  prior_action,
  ui_config,
  classNames,
}: OrderListUIProps) {
  const safeOrders = orders ?? [];
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const [confirmed, setConfirmed] = React.useState(false);

  const showSelection = ui_config?.enable_selection ?? requiresSelection;
  const showRefundBtn = ui_config?.enable_refund_button;
  const showExchangeBtn = ui_config?.enable_exchange_button;
  const showCancelBtn = ui_config?.enable_cancel_button;
  const selectableStatuses = ui_config?.selectable_statuses;

  const actionLabelMap: Record<string, string> = {
    refund: `환불할 주문 선택 완료 (${selectedIds.size}건)`,
    exchange: `교환할 주문 선택 완료 (${selectedIds.size}건)`,
    cancel: `취소할 주문 선택 완료 (${selectedIds.size}건)`,
    review: `리뷰 작성할 주문 선택 완료 (${selectedIds.size}건)`,
  };
  const actionLabel =
    ui_config?.action_label ||
    (prior_action ? actionLabelMap[prior_action] : null) ||
    `선택 완료 (${selectedIds.size}건)`;

  const showRefundBadge = !ui_config && (prior_action === 'refund' || prior_action == null);
  const showExchangeBadge = !ui_config && (prior_action === 'exchange' || prior_action == null);
  const showCancelBadge = !ui_config && (prior_action === 'cancel' || prior_action == null);

  const isSelectable = (order: SharedOrderData) => {
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
      setConfirmed(true);
      onSelect(Array.from(selectedIds));
    }
  };

  return (
    <div className={classNames?.orderListContainer}>
      <p className={classNames?.orderListMessage}>{message}</p>
      <div className={classNames?.orderCards}>
        {safeOrders.map((order) => (
          <div key={order.order_id} className={classNames?.orderCard}>
            {showSelection && (
              <input
                type="checkbox"
                checked={selectedIds.has(order.order_id)}
                onChange={() => toggleOrder(order.order_id)}
                className={classNames?.orderCheckbox}
                disabled={confirmed || !isSelectable(order)}
              />
            )}
            <div className={classNames?.orderContent}>
              <div className={classNames?.orderHeader}>
                <span className={classNames?.orderId}>주문번호: {order.order_id}</span>
                <span className={classNames?.orderStatus}>{order.status_label || order.status}</span>
              </div>
              <div className={classNames?.orderProduct}>{order.product_name}</div>
              <div className={classNames?.orderMeta}>
                <span>주문일: {order.date}</span>
                <span className={classNames?.orderAmount}>{order.amount.toLocaleString()}원</span>
              </div>
              {order.delivered_at && (
                <div className={classNames?.orderDelivered}>배송완료: {order.delivered_at}</div>
              )}
              <div className={classNames?.orderActions}>
                {showRefundBtn && order.can_return && <span className={classNames?.actionBadge}>환불가능</span>}
                {showExchangeBtn && order.can_exchange && <span className={classNames?.actionBadge}>교환가능</span>}
                {showCancelBtn && order.can_cancel && <span className={classNames?.actionBadge}>취소가능</span>}
                {showCancelBadge && order.can_cancel && <span className={classNames?.actionBadge}>취소가능</span>}
                {showRefundBadge && order.can_return && <span className={classNames?.actionBadge}>환불가능</span>}
                {showExchangeBadge && order.can_exchange && <span className={classNames?.actionBadge}>교환가능</span>}
              </div>
            </div>
          </div>
        ))}
      </div>
      {showSelection && (
        <button
          type="button"
          className={classNames?.confirmBtn}
          onClick={handleConfirm}
          disabled={selectedIds.size === 0 || confirmed}
        >
          {confirmed ? '선택 완료됨' : actionLabel}
        </button>
      )}
    </div>
  );
}
