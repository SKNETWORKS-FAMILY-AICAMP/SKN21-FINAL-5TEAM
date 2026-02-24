"use client";

import { useState, useEffect, useCallback } from "react";
import styles from "./admin-shipping.module.css";

// ==================== 타입 정의 ====================

type OrderStatus =
  | "pending"
  | "paid"
  | "preparing"
  | "shipped"
  | "delivered"
  | "cancelled"
  | "refunded";

interface OrderItem {
  id: number;
  order_id: number;
  product_option_type: string;
  product_option_id: number;
  quantity: number;
  unit_price: string;
  subtotal: string;
  product_name?: string;
}

interface Order {
  id: number;
  user_id: number;
  order_number: string;
  status: OrderStatus;
  total_amount: string;
  created_at: string;
  items: OrderItem[];
}

interface UserInfo {
  id: number;
  name: string;
  email: string;
}

interface ShippingInfo {
  id: number;
  order_id: number;
  courier_company: string | null;
  tracking_number: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

type ShippingFilter = "all" | "preparing" | "shipped" | "delivered";

const ORDER_STATUS_MAP: Record<OrderStatus, string> = {
  pending: "결제 대기",
  paid: "결제 완료",
  preparing: "상품 준비중",
  shipped: "배송중",
  delivered: "배송 완료",
  cancelled: "주문 취소",
  refunded: "환불 완료",
};

// ==================== 메인 컴포넌트 ====================

export default function AdminShippingPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [userMap, setUserMap] = useState<Record<number, UserInfo>>({});
  const [shippingMap, setShippingMap] = useState<Record<number, ShippingInfo>>({});
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<ShippingFilter>("all");
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);

  // 모달 상태
  const [showModal, setShowModal] = useState(false);
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [editingShippingId, setEditingShippingId] = useState<number | null>(null);
  const [formCourier, setFormCourier] = useState("");
  const [formTracking, setFormTracking] = useState("");
  const [formShippedAt, setFormShippedAt] = useState("");
  const [formDeliveredAt, setFormDeliveredAt] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // 커스텀 알림
  const [customAlert, setCustomAlert] = useState<{
    type: "alert" | "confirm";
    message: string;
    resolve: (value: any) => void;
  } | null>(null);

  const API_BASE = "http://localhost:8000";

  // ==================== 커스텀 알림 함수 ====================

  const showAlert = useCallback((message: string): Promise<void> => {
    return new Promise((resolve) => {
      setCustomAlert({ type: "alert", message, resolve });
    });
  }, []);

  const showConfirm = useCallback((message: string): Promise<boolean> => {
    return new Promise((resolve) => {
      setCustomAlert({ type: "confirm", message, resolve });
    });
  }, []);

  const handleAlertConfirm = () => {
    if (!customAlert) return;
    customAlert.resolve(customAlert.type === "alert" ? undefined : true);
    setCustomAlert(null);
  };

  const handleAlertCancel = () => {
    if (!customAlert) return;
    customAlert.resolve(false);
    setCustomAlert(null);
  };

  // ==================== 데이터 로드 ====================

  const fetchData = async () => {
    setLoading(true);
    try {
      // 모든 주문 가져오기 (모든 유저)
      const usersRes = await fetch(`${API_BASE}/users/all`, { credentials: 'include' });
      if (!usersRes.ok) throw new Error("유저 목록 조회 실패");
      const users: UserInfo[] = await usersRes.json();

      // 유저 맵 생성
      const uMap: Record<number, UserInfo> = {};
      for (const u of users) {
        uMap[u.id] = u;
      }
      setUserMap(uMap);

      // 각 유저의 주문 목록 가져오기
      const allOrders: Order[] = [];
      for (const user of users) {
        try {
          const ordersRes = await fetch(`${API_BASE}/orders/${user.id}/orders?skip=0&limit=100`, { credentials: 'include' });
          if (ordersRes.ok) {
            const data = await ordersRes.json();
            allOrders.push(...data.orders);
          }
        } catch {
          // skip failed user
        }
      }

      // 주문 ID 기준 내림차순 정렬
      allOrders.sort((a, b) => b.id - a.id);
      setOrders(allOrders);

      // 배송 정보 가져오기
      const map: Record<number, ShippingInfo> = {};
      for (const order of allOrders) {
        try {
          const res = await fetch(`${API_BASE}/shipping/order/${order.id}`, { credentials: 'include' });
          if (res.ok) {
            const info: ShippingInfo = await res.json();
            map[order.id] = info;
          }
        } catch {
          // no shipping info
        }
      }
      setShippingMap(map);
    } catch (err) {
      console.error("Failed to fetch data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // ==================== 필터링 ====================

  // 주문에 포함된 유저 목록 (주문이 있는 유저만)
  const usersWithOrders = Array.from(
    new Set(orders.map((o) => o.user_id))
  ).map((id) => userMap[id]).filter(Boolean);

  const filteredOrders = orders.filter((order) => {
    // 사용자 필터
    if (selectedUserId !== null && order.user_id !== selectedUserId) return false;
    // 배송 상태 필터 (주문 status 기준)
    if (filter === "preparing") return order.status === "preparing";
    if (filter === "shipped") return order.status === "shipped";
    if (filter === "delivered") return order.status === "delivered";
    return true;
  });

  // ==================== 배송 상태 판별 ====================

  const getShippingStatusLabel = (status: OrderStatus) => {
    if (status === "delivered") return "배송 완료";
    if (status === "shipped") return "배송중";
    if (status === "preparing") return "상품 준비중";
    return ORDER_STATUS_MAP[status] || status;
  };

  const getShippingStatusClass = (status: OrderStatus) => {
    if (status === "delivered") return styles.statusDelivered;
    if (status === "shipped") return styles.statusShipped;
    if (status === "preparing") return styles.statusPreparing;
    return styles.statusNone;
  };

  // ==================== 모달 열기 ====================

  const handleOpenModal = (order: Order) => {
    const existing = shippingMap[order.id];
    setEditingOrderId(order.id);

    if (existing) {
      setEditingShippingId(existing.id);
      setFormCourier(existing.courier_company || "");
      setFormTracking(existing.tracking_number || "");
      setFormShippedAt(existing.shipped_at ? existing.shipped_at.slice(0, 10) : "");
      setFormDeliveredAt(existing.delivered_at ? existing.delivered_at.slice(0, 10) : "");
    } else {
      setEditingShippingId(null);
      setFormCourier("");
      setFormTracking("");
      setFormShippedAt("");
      setFormDeliveredAt("");
    }

    setShowModal(true);
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setEditingOrderId(null);
    setEditingShippingId(null);
  };

  // ==================== 주문 상태 변경 (관리자) ====================

  const handleChangeOrderStatus = async (orderId: number, newStatus: string, label: string) => {
    const confirmed = await showConfirm(`주문 상태를 "${label}"(으)로 변경하시겠습니까?`);
    if (!confirmed) return;

    try {
      const res = await fetch(`${API_BASE}/shipping/order/${orderId}/status?status=${newStatus}`, {
        method: "PATCH",
        credentials: "include",
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "상태 변경 실패");
      }

      // 로컬 상태 업데이트
      setOrders((prev) =>
        prev.map((o) => (o.id === orderId ? { ...o, status: newStatus as OrderStatus } : o))
      );
      showAlert(`주문 상태가 "${label}"(으)로 변경되었습니다.`);
    } catch (err) {
      console.error(err);
      showAlert(err instanceof Error ? err.message : "상태 변경에 실패했습니다.");
    }
  };

  // ==================== 배송 정보 저장 ====================

  const handleSubmit = async () => {
    if (!editingOrderId) return;

    if (!formCourier.trim() && !formTracking.trim()) {
      showAlert("택배사 또는 송장번호를 입력해주세요.");
      return;
    }

    setSubmitting(true);
    try {
      let response: Response;

      const body: any = {
        courier_company: formCourier || null,
        tracking_number: formTracking || null,
        shipped_at: formShippedAt ? new Date(formShippedAt).toISOString() : null,
        delivered_at: formDeliveredAt ? new Date(formDeliveredAt).toISOString() : null,
      };

      if (editingShippingId) {
        // 수정
        response = await fetch(`${API_BASE}/shipping/info/${editingShippingId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          credentials: 'include',
          body: JSON.stringify(body),
        });
      } else {
        // 생성 → 서버에서 자동으로 주문 상태를 '상품 준비중'으로 변경
        response = await fetch(`${API_BASE}/shipping/info`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: 'include',
          body: JSON.stringify({ ...body, order_id: editingOrderId }),
        });
      }

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "저장 실패");
      }

      const saved: ShippingInfo = await response.json();
      setShippingMap((prev) => ({ ...prev, [saved.order_id]: saved }));

      // 신규 등록 시 로컬 주문 상태도 '상품 준비중'으로 업데이트 (취소/환불 상태는 유지)
      if (!editingShippingId) {
        const currentOrder = orders.find((o) => o.id === editingOrderId);
        const isFinalStatus = currentOrder?.status === "cancelled" || currentOrder?.status === "refunded";
        if (!isFinalStatus) {
          setOrders((prev) =>
            prev.map((o) => (o.id === editingOrderId ? { ...o, status: "preparing" } : o))
          );
        }
      }

      showAlert(editingShippingId ? "배송 정보가 수정되었습니다." : "배송 정보가 등록되었습니다.");
      handleCloseModal();
    } catch (err) {
      console.error(err);
      showAlert(err instanceof Error ? err.message : "저장에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  // ==================== 렌더링 ====================

  return (
    <div className={styles.container}>
      {/* 헤더 */}
      <div className={styles.header}>
        <h1 className={styles.title}>배송 관리</h1>
        <p className={styles.subtitle}>Admin Shipping Management</p>
      </div>

      <div className={styles.content}>
        {/* 사용자 필터 */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>사용자 필터</div>
          <div className={styles.filterButtons}>
            <button
              className={`${styles.filterButton} ${selectedUserId === null ? styles.filterButtonActive : ""}`}
              onClick={() => setSelectedUserId(null)}
            >
              전체
            </button>
            {usersWithOrders.map((u) => (
              <button
                key={u.id}
                className={`${styles.filterButton} ${selectedUserId === u.id ? styles.filterButtonActive : ""}`}
                onClick={() => setSelectedUserId(u.id)}
              >
                {u.name} ({u.email})
              </button>
            ))}
          </div>
        </div>

        {/* 배송 상태 필터 */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>배송 상태 필터</div>
          <div className={styles.filterButtons}>
            {([
              { key: "all", label: "전체" },
              { key: "preparing", label: "상품 준비중" },
              { key: "shipped", label: "배송중" },
              { key: "delivered", label: "배송 완료" },
            ] as { key: ShippingFilter; label: string }[]).map((f) => (
              <button
                key={f.key}
                className={`${styles.filterButton} ${filter === f.key ? styles.filterButtonActive : ""}`}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* 주문 목록 테이블 */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>
            주문 목록
            <span className={styles.totalCount}>{filteredOrders.length}건</span>
          </div>

          {loading ? (
            <div className={styles.loading}>데이터를 불러오는 중...</div>
          ) : filteredOrders.length === 0 ? (
            <div className={styles.empty}>해당하는 주문이 없습니다.</div>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>사용자</th>
                    <th>주문번호</th>
                    <th>주문상태</th>
                    <th>결제금액</th>
                    <th>주문일</th>
                    <th>배송상태</th>
                    <th>택배사</th>
                    <th>송장번호</th>
                    <th>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOrders.map((order) => {
                    const info = shippingMap[order.id];
                    return (
                      <tr key={order.id}>
                        <td>
                          <span className={styles.userName}>
                            {userMap[order.user_id]?.name || `ID: ${order.user_id}`}
                          </span>
                        </td>
                        <td>
                          <span className={styles.orderNumber}>{order.order_number}</span>
                        </td>
                        <td>{ORDER_STATUS_MAP[order.status]}</td>
                        <td>{Number(order.total_amount).toLocaleString()}원</td>
                        <td className={styles.dateCell}>
                          {new Date(order.created_at).toLocaleDateString("ko-KR")}
                        </td>
                        <td>
                          <span className={`${styles.statusBadge} ${getShippingStatusClass(order.status)}`}>
                            {getShippingStatusLabel(order.status)}
                          </span>
                        </td>
                        <td>{info?.courier_company || <span className={styles.noData}>-</span>}</td>
                        <td>{info?.tracking_number || <span className={styles.noData}>-</span>}</td>
                        <td>
                          <button
                            className={`${styles.actionBtn} ${!info ? styles.actionBtnPrimary : ""}`}
                            onClick={() => handleOpenModal(order)}
                          >
                            {info ? "수정" : "등록"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* 배송 정보 등록/수정 모달 */}
      {showModal && (
        <div className={styles.modalOverlay} onClick={handleCloseModal}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <button className={styles.closeBtn} onClick={handleCloseModal}>
              ✕
            </button>

            <h2 className={styles.modalTitle}>
              {editingShippingId ? "배송 정보 수정" : "배송 정보 등록"}
            </h2>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>택배사</label>
              <input
                type="text"
                className={styles.formInput}
                value={formCourier}
                onChange={(e) => setFormCourier(e.target.value)}
                placeholder="CJ대한통운, 한진택배, 롯데택배 등"
              />
            </div>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>송장번호</label>
              <input
                type="text"
                className={styles.formInput}
                value={formTracking}
                onChange={(e) => setFormTracking(e.target.value)}
                placeholder="송장번호를 입력하세요"
              />
            </div>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>배송 시작일</label>
              <input
                type="date"
                className={styles.formInput}
                value={formShippedAt}
                onChange={(e) => setFormShippedAt(e.target.value)}
              />
            </div>

            <div className={styles.formGroup}>
              <label className={styles.formLabel}>배송 완료일</label>
              <input
                type="date"
                className={styles.formInput}
                value={formDeliveredAt}
                onChange={(e) => setFormDeliveredAt(e.target.value)}
              />
            </div>

            {/* 주문 상태 변경 버튼 */}
            {editingOrderId && (() => {
              const currentOrder = orders.find((o) => o.id === editingOrderId);
              if (!currentOrder) return null;
              return (
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>주문 상태 변경</label>
                  <div className={styles.statusActions}>
                    {currentOrder.status === "preparing" && (
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnShipped}`}
                        onClick={() => { handleChangeOrderStatus(currentOrder.id, "shipped", "배송중"); handleCloseModal(); }}
                      >
                        배송중으로 변경
                      </button>
                    )}
                    {currentOrder.status === "shipped" && (
                      <button
                        className={`${styles.actionBtn} ${styles.actionBtnDelivered}`}
                        onClick={() => { handleChangeOrderStatus(currentOrder.id, "delivered", "배송 완료"); handleCloseModal(); }}
                      >
                        배송완료로 변경
                      </button>
                    )}
                    {!["preparing", "shipped"].includes(currentOrder.status) && (
                      <span className={styles.noData}>현재 상태: {ORDER_STATUS_MAP[currentOrder.status]}</span>
                    )}
                  </div>
                </div>
              );
            })()}

            <div className={styles.formActions}>
              <button
                className={`${styles.actionBtn} ${styles.customAlertBtnSecondary}`}
                onClick={handleCloseModal}
              >
                취소
              </button>
              <button
                className={`${styles.actionBtn} ${styles.actionBtnPrimary}`}
                onClick={handleSubmit}
                disabled={submitting}
              >
                {submitting
                  ? (editingShippingId ? "수정 중..." : "등록 중...")
                  : (editingShippingId ? "수정" : "등록")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 커스텀 알림 모달 */}
      {customAlert && (
        <div className={styles.customAlertOverlay}>
          <div className={styles.customAlertBox}>
            <div className={styles.customAlertMessage}>{customAlert.message}</div>
            <div className={styles.customAlertButtons}>
              {customAlert.type === "confirm" && (
                <button
                  className={`${styles.customAlertBtn} ${styles.customAlertBtnSecondary}`}
                  onClick={handleAlertCancel}
                >
                  취소
                </button>
              )}
              <button
                className={`${styles.customAlertBtn} ${styles.customAlertBtnPrimary}`}
                onClick={handleAlertConfirm}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
