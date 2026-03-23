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

type OrderListUIProps = {
  message: string;
  orders: SharedOrderData[];
  onSelect: (selectedOrderIds: string[]) => void;
  requiresSelection?: boolean;
  prior_action?: string | null;
  ui_config?: SharedOrderUiConfig;
};

export default function OrderListUI({
  message,
  orders,
  onSelect,
  requiresSelection = false,
  ui_config,
}: OrderListUIProps) {
  const [selectedIds, setSelectedIds] = React.useState<Set<string>>(new Set());
  const safeOrders = orders ?? [];
  const showSelection = ui_config?.enable_selection ?? requiresSelection;

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

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <p>{message}</p>
      <div style={{ display: 'grid', gap: 12 }}>
        {safeOrders.map((order) => (
          <div
            key={order.order_id}
            style={{
              display: 'grid',
              gap: 8,
              border: '1px solid #e5e7eb',
              borderRadius: 12,
              padding: 12,
            }}
          >
            <label style={{ display: 'flex', gap: 8, alignItems: 'start' }}>
              {showSelection ? (
                <input
                  type="checkbox"
                  checked={selectedIds.has(order.order_id)}
                  onChange={() => toggleOrder(order.order_id)}
                />
              ) : null}
              <span style={{ display: 'grid', gap: 4 }}>
                <strong>{order.product_name}</strong>
                <span>주문번호: {order.order_id}</span>
                <span>{order.status_label || order.status}</span>
                <span>{Math.round(order.amount ?? 0).toLocaleString()}원</span>
              </span>
            </label>
          </div>
        ))}
      </div>
      {showSelection ? (
        <button
          type="button"
          onClick={() => onSelect(Array.from(selectedIds))}
          disabled={selectedIds.size === 0}
          style={{
            justifySelf: 'start',
            padding: '10px 14px',
            borderRadius: 10,
            border: '1px solid #111827',
            background: '#111827',
            color: '#fff',
          }}
        >
          {ui_config?.action_label || `선택 완료 (${selectedIds.size}건)`}
        </button>
      ) : null}
    </div>
  );
}
