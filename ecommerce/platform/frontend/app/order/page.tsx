"use client";

import { useState, useEffect } from "react";
import styles from "./order.module.css";
import { useAuth } from '../authcontext';

// ==================== 타입 정의 ====================

type OrderStatus =
  | "pending"
  | "paid"
  | "preparing"
  | "shipped"
  | "delivered"
  | "cancelled"
  | "refunded";

type ProductType = "new" | "used";

interface OrderItem {
  id: number;
  order_id: number;
  product_option_type: ProductType;
  product_option_id: number;
  quantity: number;
  unit_price: string;
  subtotal: string;
  created_at: string;
  product_name?: string; // 상품명 (백엔드에서 제공)
  product_brand?: string; // 브랜드 (카테고리명)
  product_size?: string; // 사이즈
  product_color?: string; // 색상
  product_condition?: string; // 중고상품 상태
}

interface Order {
  id: number;
  user_id: number;
  order_number: string;
  shipping_address_id: number;
  subtotal: string;
  discount_amount: string;
  shipping_fee: string;
  total_amount: string;
  points_used: string;
  status: OrderStatus;
  payment_method: string;
  shipping_request: string | null;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
}

interface OrderListResponse {
  orders: Order[];
  total: number;
  page: number;
  page_size: number;
}

interface ShippingInfo {
  id: number;
  order_id: number;
  tracking_number: string | null;
  carrier: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  status: string;
}

// ==================== 상태 표시 유틸 ====================

const ORDER_STATUS_MAP: Record<OrderStatus, string> = {
  pending: "결제 대기",
  paid: "결제 완료",
  preparing: "상품 준비중",
  shipped: "배송중",
  delivered: "배송 완료",
  cancelled: "주문 취소",
  refunded: "환불 완료",
};

const STATUS_COLOR_MAP: Record<OrderStatus, string> = {
  pending: "#ff9800",
  paid: "#2196f3",
  preparing: "#9c27b0",
  shipped: "#00bcd4",
  delivered: "#4caf50",
  cancelled: "#f44336",
  refunded: "#795548",
};

// ==================== 메인 컴포넌트 ====================

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [shippingInfo, setShippingInfo] = useState<ShippingInfo | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showShippingModal, setShowShippingModal] = useState(false);
  const [statusFilter, setStatusFilter] = useState<OrderStatus | "all">("all");
  const {user, isLoggedIn } = useAuth();

  const API_BASE = "http://localhost:8000";

  // ==================== 주문 목록 조회 ====================

  useEffect(() => {
    if(user){
      fetchOrders();
    }
  }, [statusFilter,user]);

  const fetchOrders = async () => {
    try {
      setLoading(true);
      setError(null);
      if (!user) throw new Error("유저 정보가 없습니다");
      let url = `${API_BASE}/orders/${user.id}/orders?skip=0&limit=20`;
      
      if (statusFilter !== "all") {
        url += `&status=${statusFilter}`;
      }

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error("주문 목록을 불러오는데 실패했습니다");
      }

      const data: OrderListResponse = await response.json();
      setOrders(data.orders);
    } catch (err) {
      console.error("Failed to fetch orders:", err);
      setError(err instanceof Error ? err.message : "알 수 없는 오류");
    } finally {
      setLoading(false);
    }
  };

  // ==================== 주문 상세 조회 ====================

  const handleShowDetail = async (orderId: number) => {
    try {
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/orders/${user.id}/orders/${orderId}`);

      if (!response.ok) {
        throw new Error("주문 상세 정보를 불러오는데 실패했습니다");
      }

      const orderDetail: Order = await response.json();
      setSelectedOrder(orderDetail);
      setShowDetailModal(true);
    } catch (err) {
      console.error("Failed to fetch order detail:", err);
      alert("주문 상세 정보를 불러오는데 실패했습니다");
    }
  };

  // ==================== 배송 정보 조회 ====================

  const handleShowShipping = async (orderId: number) => {
    try {
      // ✅ 수정된 URL: /shipping/order/{order_id}
      const response = await fetch(`${API_BASE}/shipping/order/${orderId}`);

      if (!response.ok) {
        throw new Error("배송 정보를 불러오는데 실패했습니다");
      }

      const shipping: ShippingInfo = await response.json();
      setShippingInfo(shipping);
      setShowShippingModal(true);
    } catch (err) {
      console.error("Failed to fetch shipping info:", err);
      alert("배송 정보를 불러오는데 실패했습니다");
    }
  };

  // ==================== 주문 취소 ====================

  const handleCancelOrder = async (orderId: number) => {
    const reason = prompt("취소 사유를 입력해주세요:");
    if (!reason) {
      return;
    }

    try {
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(
        `${API_BASE}/orders/${user.id}/orders/${orderId}/cancel?reason=${encodeURIComponent(
          reason
        )}`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "주문 취소에 실패했습니다");
      }

      // User History에 주문 취소 기록
      try {
        await fetch(`${API_BASE}/user-history/users/${user.id}/track/order`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order_id: orderId, action_type: "order_del" }),
        });
      } catch (err) {
        console.error("Failed to track order_del:", err);
      }

      alert("주문이 취소되었습니다");
      fetchOrders(); // 목록 새로고침
    } catch (err) {
      console.error("Failed to cancel order:", err);
      alert(err instanceof Error ? err.message : "주문 취소에 실패했습니다");
    }
  };

  // ==================== 환불 요청 ====================

  const handleRefundOrder = async (orderId: number) => {
    const reason = prompt("환불 사유를 입력해주세요:");
    if (!reason) {
      return;
    }

    try {
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(
        `${API_BASE}/orders/${user.id}/orders/${orderId}/refund?reason=${encodeURIComponent(
          reason
        )}`,
        {
          method: "POST",
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "환불 요청에 실패했습니다");
      }

      // User History에 환불 요청 기록
      try {
        await fetch(`${API_BASE}/user-history/users/${user.id}/track/refund`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ order_id: orderId }),
        });
      } catch (err) {
        console.error("Failed to track order_re:", err);
      }

      alert("환불이 요청되었습니다");
      fetchOrders(); // 목록 새로고침
    } catch (err) {
      console.error("Failed to refund order:", err);
      alert(err instanceof Error ? err.message : "환불 요청에 실패했습니다");
    }
  };

  // ==================== 주문 상태 변경 ====================

  const handleUpdateStatus = async (
    orderId: number,
    newStatus: OrderStatus
  ) => {
    if (!confirm(`주문 상태를 '${ORDER_STATUS_MAP[newStatus]}'(으)로 변경하시겠습니까?`)) {
      return;
    }

    try {
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(
        `${API_BASE}/orders/${user.id}/orders/${orderId}/status`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ status: newStatus }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "상태 변경에 실패했습니다");
      }

      alert("주문 상태가 변경되었습니다");
      fetchOrders();
    } catch (err) {
      console.error("Failed to update status:", err);
      alert(err instanceof Error ? err.message : "상태 변경에 실패했습니다");
    }
  };

    // ==================== 리뷰 작성 =======================
    const handleCreateReview = async (orderItemId: number) => {
    if (!user) {
      alert("로그인이 필요합니다");
      return;
    }

    const content = prompt("리뷰 내용을 입력하세요:");
    if (!content) return;

    const ratingInput = prompt("평점을 입력하세요 (1~5):");
    if (!ratingInput) return;

    const rating = Number(ratingInput);
    if (rating < 1 || rating > 5) {
      alert("평점은 1~5 사이여야 합니다");
      return;
    }

    try {
      const response = await fetch(
        `http://localhost:8000/reviews?user_id=${user.id}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            order_item_id: orderItemId,
            content,
            rating,
          }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "리뷰 작성 실패");
      }

      alert("리뷰가 등록되었습니다 🎉 (100원 적립)");

    } catch (err) {
      console.error(err);
      alert(err instanceof Error ? err.message : "리뷰 작성 실패");
    }
  };

    // ==================== 로딩 및 에러 처리 ====================

    if (loading) {
      return (
        <div className={styles.wrapper}>
          <div className={styles.loading}>주문 목록을 불러오는 중...</div>
        </div>
      );
    }

    if (error) {
      return (
        <div className={styles.wrapper}>
          <div className={styles.loading} style={{ color: "red" }}>
            에러: {error}
          </div>
          <button onClick={fetchOrders} className={styles.detailBtn}>
            다시 시도
          </button>
        </div>
      );
    }

  // ==================== 렌더링 ====================

  return (
    <div className={styles.wrapper}>
      <h1 className={styles.title}>주문 내역</h1>

      {/* 상태 필터 */}
      <div style={{ marginBottom: "20px" }}>
        <label style={{ marginRight: "10px" }}>주문 상태: </label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as OrderStatus | "all")}
          style={{
            padding: "8px 12px",
            borderRadius: "4px",
            border: "1px solid #ccc",
          }}
        >
          <option value="all">전체</option>
          <option value="pending">결제 대기</option>
          <option value="paid">결제 완료</option>
          <option value="preparing">상품 준비중</option>
          <option value="shipped">배송중</option>
          <option value="delivered">배송 완료</option>
          <option value="cancelled">주문 취소</option>
          <option value="refunded">환불 완료</option>
        </select>
      </div>

      {orders.length === 0 ? (
        <div className={styles.emptyOrders}>
          <div className={styles.emptyIcon}>📦</div>
          <p>주문 내역이 없습니다</p>
        </div>
      ) : (
        <div className={styles.ordersList}>
          {orders.map((order) => (
            <div key={order.id} className={styles.orderCard}>
              {/* 주문 헤더 */}
              <div className={styles.orderHeader}>
                <div>
                  <strong>주문번호:</strong> {order.order_number}
                </div>
                <div>
                  <strong>주문일:</strong>{" "}
                  {new Date(order.created_at).toLocaleDateString("ko-KR", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </div>
                <div
                  className={styles.status}
                  style={{
                    backgroundColor: STATUS_COLOR_MAP[order.status],
                  }}
                >
                  {ORDER_STATUS_MAP[order.status]}
                </div>
              </div>

              {/* 주문 항목 */}
              <div className={styles.orderItems}>
                {order.items.map((item) => (
                  <div key={item.id} className={styles.orderItem}>
                    <div className={styles.itemImage}>
                      <img
                        src="/placeholder-product.png"
                        alt="상품 이미지"
                        onError={(e) => {
                          e.currentTarget.src =
                            "https://via.placeholder.com/80";
                        }}
                      />
                    </div>
                    <div className={styles.itemInfo}>
                      <div className={styles.itemBrand}>
                        {item.product_option_type === "new"
                          ? "🆕 신상품"
                          : "♻️ 중고상품"}
                        {item.product_brand && ` · ${item.product_brand}`}
                      </div>
                      <div className={styles.itemName}>
                        {item.product_name || `상품 옵션 ID: ${item.product_option_id}`}
                      </div>
                      {/* 옵션 정보 표시 */}
                      {(item.product_size || item.product_color || item.product_condition) && (
                        <div style={{ fontSize: "13px", color: "#666", marginTop: "4px" }}>
                          {item.product_size && `사이즈: ${item.product_size}`}
                          {item.product_size && item.product_color && " · "}
                          {item.product_color && `색상: ${item.product_color}`}
                          {item.product_condition && ` · 상태: ${item.product_condition}`}
                        </div>
                      )}
                      <div className={styles.itemQuantity}>
                        수량: {item.quantity}개
                      </div>
                      <div className={styles.itemPrice}>
                        {Number(item.unit_price).toLocaleString()}원 x{" "}
                        {item.quantity}개 ={" "}
                        <strong>
                          {Number(item.subtotal).toLocaleString()}원
                        </strong>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              {/* 주문 요약 */}
              <div className={styles.orderSummary}>
                <div>
                  상품금액: {Number(order.subtotal).toLocaleString()}원
                </div>
                {Number(order.discount_amount) > 0 && (
                  <div style={{ color: "#f44336" }}>
                    할인: -{Number(order.discount_amount).toLocaleString()}원
                  </div>
                )}
                <div>
                  배송비: +{Number(order.shipping_fee).toLocaleString()}원
                </div>
                {Number(order.points_used) > 0 && (
                  <div style={{ color: "#9c27b0" }}>
                    포인트: -{Number(order.points_used).toLocaleString()}원
                  </div>
                )}
                <div className={styles.finalAmount}>
                  최종결제: {Number(order.total_amount).toLocaleString()}원
                </div>
              </div>

              {/* 결제 수단 */}
              <div style={{ fontSize: "13px", color: "#666", marginTop: "10px" }}>
                결제수단: {order.payment_method}
              </div>

              {/* 액션 버튼 */}
              <div className={styles.orderActions}>
                <button
                  className={styles.detailBtn}
                  onClick={() => handleShowDetail(order.id)}
                >
                  📋 상세보기
                </button>

                {/* 배송 조회 (배송중 또는 배송완료) */}
                {(order.status === "shipped" ||
                  order.status === "delivered") && (
                  <button
                    className={styles.deliveryBtn}
                    onClick={() => handleShowShipping(order.id)}
                  >
                    🚚 배송조회
                  </button>
                )}

                {/* 결제 대기 상태에서만 취소 가능 */}
                {order.status === "pending" && (
                  <button
                    className={styles.detailBtn}
                    onClick={() => handleCancelOrder(order.id)}
                    style={{ backgroundColor: "#f44336" }}
                  >
                    ❌ 주문취소
                  </button>
                )}

                {/* 결제 완료 ~ 배송중 상태에서 환불 가능 */}
                {(order.status === "paid" ||
                  order.status === "preparing" ||
                  order.status === "shipped") && (
                  <button
                    className={styles.detailBtn}
                    onClick={() => handleRefundOrder(order.id)}
                    style={{ backgroundColor: "#ff9800" }}
                  >
                    💰 환불요청
                  </button>
                )}

                {/* 배송 완료 시 리뷰 작성 가능 */}
                {order.status === "delivered" && (
                  <button
                    className={styles.reviewBtn}
                    // onClick={() => alert("리뷰 작성 기능은 준비중입니다")}
                    onClick={() => handleCreateReview(order.items[0].id)}
                  >
                    ⭐ 리뷰 작성
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 상세보기 모달 */}
      {showDetailModal && selectedOrder && (
        <div
          className={styles.modalOverlay}
          onClick={() => setShowDetailModal(false)}
        >
          <div
            className={styles.modalContent}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className={styles.closeBtn}
              onClick={() => setShowDetailModal(false)}
            >
              ✕
            </button>

            <h2>주문 상세 정보</h2>

            <div className={styles.modalItem}>
              <strong>주문번호:</strong> {selectedOrder.order_number}
            </div>
            <div className={styles.modalItem}>
              <strong>주문상태:</strong>{" "}
              <span
                style={{
                  color: STATUS_COLOR_MAP[selectedOrder.status],
                  fontWeight: "bold",
                }}
              >
                {ORDER_STATUS_MAP[selectedOrder.status]}
              </span>
            </div>
            <div className={styles.modalItem}>
              <strong>결제수단:</strong> {selectedOrder.payment_method}
            </div>
            <div className={styles.modalItem}>
              <strong>주문일시:</strong>{" "}
              {new Date(selectedOrder.created_at).toLocaleString("ko-KR")}
            </div>
            {selectedOrder.shipping_request && (
              <div className={styles.modalItem}>
                <strong>배송요청:</strong> {selectedOrder.shipping_request}
              </div>
            )}

            <h3 style={{ marginTop: "20px", marginBottom: "10px" }}>
              주문 항목
            </h3>
            {selectedOrder.items.map((item, idx) => (
              <div
                key={item.id}
                className={styles.modalItem}
                style={{
                  backgroundColor: idx % 2 === 0 ? "#f9f9f9" : "white",
                  padding: "10px",
                  borderRadius: "4px",
                }}
              >
                <div style={{ marginBottom: "6px", fontWeight: "500" }}>
                  {item.product_option_type === "new" ? "🆕" : "♻️"} {item.product_name || `상품 옵션 ID: ${item.product_option_id}`}
                </div>
                {item.product_brand && (
                  <div style={{ fontSize: "13px", color: "#666", marginBottom: "4px" }}>
                    브랜드: {item.product_brand}
                  </div>
                )}
                {(item.product_size || item.product_color || item.product_condition) && (
                  <div style={{ fontSize: "13px", color: "#666", marginBottom: "4px" }}>
                    {item.product_size && `사이즈: ${item.product_size}`}
                    {item.product_size && item.product_color && " · "}
                    {item.product_color && `색상: ${item.product_color}`}
                    {item.product_condition && ` · 상태: ${item.product_condition}`}
                  </div>
                )}
                <div>
                  수량: {item.quantity}개 x{" "}
                  {Number(item.unit_price).toLocaleString()}원 ={" "}
                  <strong>{Number(item.subtotal).toLocaleString()}원</strong>
                </div>
              </div>
            ))}

            <div
              className={styles.modalItem}
              style={{
                marginTop: "20px",
                padding: "15px",
                backgroundColor: "#f5f5f5",
                borderRadius: "6px",
              }}
            >
              <div style={{ marginBottom: "8px" }}>
                상품금액: {Number(selectedOrder.subtotal).toLocaleString()}원
              </div>
              <div style={{ marginBottom: "8px" }}>
                할인: -{Number(selectedOrder.discount_amount).toLocaleString()}
                원
              </div>
              <div style={{ marginBottom: "8px" }}>
                배송비: +{Number(selectedOrder.shipping_fee).toLocaleString()}원
              </div>
              <div style={{ marginBottom: "8px" }}>
                포인트: -{Number(selectedOrder.points_used).toLocaleString()}원
              </div>
              <div
                style={{
                  fontSize: "18px",
                  fontWeight: "bold",
                  color: "#e53935",
                  marginTop: "10px",
                  paddingTop: "10px",
                  borderTop: "2px solid #ddd",
                }}
              >
                최종 결제금액:{" "}
                {Number(selectedOrder.total_amount).toLocaleString()}원
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 배송 정보 모달 */}
      {showShippingModal && shippingInfo && (
        <div
          className={styles.modalOverlay}
          onClick={() => setShowShippingModal(false)}
        >
          <div
            className={styles.modalContent}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className={styles.closeBtn}
              onClick={() => setShowShippingModal(false)}
            >
              ✕
            </button>

            <h2>배송 정보</h2>

            <div className={styles.modalItem}>
              <strong>주문 ID:</strong> {shippingInfo.order_id}
            </div>
            {shippingInfo.tracking_number && (
              <div className={styles.modalItem}>
                <strong>운송장 번호:</strong> {shippingInfo.tracking_number}
              </div>
            )}
            {shippingInfo.carrier && (
              <div className={styles.modalItem}>
                <strong>택배사:</strong> {shippingInfo.carrier}
              </div>
            )}
            <div className={styles.modalItem}>
              <strong>배송 상태:</strong> {shippingInfo.status}
            </div>
            {shippingInfo.shipped_at && (
              <div className={styles.modalItem}>
                <strong>발송일:</strong>{" "}
                {new Date(shippingInfo.shipped_at).toLocaleString("ko-KR")}
              </div>
            )}
            {shippingInfo.delivered_at && (
              <div className={styles.modalItem}>
                <strong>배송완료일:</strong>{" "}
                {new Date(shippingInfo.delivered_at).toLocaleString("ko-KR")}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
