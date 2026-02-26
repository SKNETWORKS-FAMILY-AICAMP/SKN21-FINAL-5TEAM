"use client";

import { useState, useEffect, useCallback } from "react";
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
  product_id?: number; // 상품 ID (백엔드에서 제공)
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
  courier_company: string | null;
  tracking_number: string | null;
  shipped_at: string | null;
  delivered_at: string | null;
  created_at: string;
  updated_at: string;
}

interface ReviewData {
  id: number;
  user_id: number;
  order_item_id: number;
  rating: number;
  content: string | null;
  created_at: string;
  updated_at: string;
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
  const [showReviewModal, setShowReviewModal] = useState(false);
  const [reviewOrderItemId, setReviewOrderItemId] = useState<number | null>(null);
  const [reviewOrderItems, setReviewOrderItems] = useState<OrderItem[]>([]);
  const [reviewContent, setReviewContent] = useState("");
  const [reviewRating, setReviewRating] = useState(0);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [hoverRating, setHoverRating] = useState(0);
  const [statusFilter, setStatusFilter] = useState<OrderStatus | "all">("all");
  const { user, isLoggedIn } = useAuth();
  const [imageMap, setImageMap] = useState<Record<string, string>>({});

  // ==================== 리뷰 맵 (order_item_id → ReviewData) ====================
  const [reviewMap, setReviewMap] = useState<Record<number, ReviewData>>({});
  const [editingReviewId, setEditingReviewId] = useState<number | null>(null);

  // ==================== 커스텀 알림 상태 ====================
  const [customAlert, setCustomAlert] = useState<{
    type: 'alert' | 'confirm' | 'prompt';
    message: string;
    resolve: (value: any) => void;
  } | null>(null);
  const [promptInput, setPromptInput] = useState("");

  const API_BASE = process.env.NEXT_PUBLIC_API_URL;

  // ==================== 커스텀 알림 함수 ====================

  const showAlert = useCallback((message: string): Promise<void> => {
    return new Promise((resolve) => {
      setCustomAlert({ type: 'alert', message, resolve });
    });
  }, []);

  const showConfirm = useCallback((message: string): Promise<boolean> => {
    return new Promise((resolve) => {
      setCustomAlert({ type: 'confirm', message, resolve });
    });
  }, []);

  const showPrompt = useCallback((message: string): Promise<string | null> => {
    return new Promise((resolve) => {
      setPromptInput("");
      setCustomAlert({ type: 'prompt', message, resolve });
    });
  }, []);

  const handleAlertConfirm = () => {
    if (!customAlert) return;
    if (customAlert.type === 'alert') {
      customAlert.resolve(undefined);
    } else if (customAlert.type === 'confirm') {
      customAlert.resolve(true);
    } else if (customAlert.type === 'prompt') {
      customAlert.resolve(promptInput || null);
    }
    setCustomAlert(null);
  };

  const handleAlertCancel = () => {
    if (!customAlert) return;
    if (customAlert.type === 'confirm') {
      customAlert.resolve(false);
    } else if (customAlert.type === 'prompt') {
      customAlert.resolve(null);
    }
    setCustomAlert(null);
  };

  // ==================== 유저 리뷰 조회 ====================

  const fetchUserReviews = async () => {
    if (!user) return;
    try {
      const response = await fetch(`${API_BASE}/reviews/users/${user.id}/reviews`);
      if (!response.ok) return;
      const reviews: ReviewData[] = await response.json();
      const map: Record<number, ReviewData> = {};
      for (const review of reviews) {
        map[review.order_item_id] = review;
      }
      setReviewMap(map);
    } catch (err) {
      console.error("Failed to fetch user reviews:", err);
    }
  };

  // ==================== 주문 목록 조회 ====================

  useEffect(() => {
    if (user) {
      fetchOrders();
      fetchUserReviews();
    }
  }, [statusFilter, user]);

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

      // productimages 테이블에서 이미지 가져오기
      const allItems = data.orders.flatMap(order => order.items);
      const uniqueItems = allItems.filter((item, idx, arr) =>
        item.product_id && arr.findIndex(i => i.product_id === item.product_id && i.product_option_type === item.product_option_type) === idx
      );
      const newMap: Record<string, string> = {};
      await Promise.all(
        uniqueItems.map(async (item) => {
          if (!item.product_id) return;
          try {
            const imgRes = await fetch(`${API_BASE}/products/images/${item.product_option_type}/${item.product_id}`);
            if (!imgRes.ok) return;
            const images = await imgRes.json();
            const primary = images.find((img: any) => img.is_primary);
            if (primary || images[0]) {
              newMap[`${item.product_option_type}_${item.product_id}`] = (primary || images[0]).image_url;
            }
          } catch { }
        })
      );
      setImageMap(prev => ({ ...prev, ...newMap }));
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
      showAlert("주문 상세 정보를 불러오는데 실패했습니다");
    }
  };

  // ==================== 배송 정보 조회 ====================

  const handleShowShipping = async (order: Order) => {
    try {
      const response = await fetch(`${API_BASE}/shipping/order/${order.id}`);

      if (!response.ok) {
        throw new Error("배송 정보를 불러오는데 실패했습니다");
      }

      const shipping: ShippingInfo = await response.json();
      setShippingInfo(shipping);
      setSelectedOrder(order);
      setShowShippingModal(true);
    } catch (err) {
      console.error("Failed to fetch shipping info:", err);
      showAlert("배송 정보를 불러오는데 실패했습니다");
    }
  };

  // ==================== 주문 취소 ====================

  const handleCancelOrder = async (orderId: number) => {
    const reason = await showPrompt("취소 사유를 입력해주세요:");
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

      showAlert("주문이 취소되었습니다");
      fetchOrders(); // 목록 새로고침
    } catch (err) {
      console.error("Failed to cancel order:", err);
      showAlert(err instanceof Error ? err.message : "주문 취소에 실패했습니다");
    }
  };

  // ==================== 환불 요청 ====================

  const handleRefundOrder = async (orderId: number) => {
    const reason = await showPrompt("환불 사유를 입력해주세요:");
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

      showAlert("환불이 요청되었습니다");
      fetchOrders(); // 목록 새로고침
    } catch (err) {
      console.error("Failed to refund order:", err);
      showAlert(err instanceof Error ? err.message : "환불 요청에 실패했습니다");
    }
  };

  // ==================== 주문 상태 변경 ====================

  const handleUpdateStatus = async (
    orderId: number,
    newStatus: OrderStatus
  ) => {
    const confirmed = await showConfirm(`주문 상태를 '${ORDER_STATUS_MAP[newStatus]}'(으)로 변경하시겠습니까?`);
    if (!confirmed) {
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

      showAlert("주문 상태가 변경되었습니다");
      fetchOrders();
    } catch (err) {
      console.error("Failed to update status:", err);
      showAlert(err instanceof Error ? err.message : "상태 변경에 실패했습니다");
    }
  };

  // ==================== 리뷰 작성/수정 =======================
  const handleOpenReviewModal = (order: Order) => {
    if (!user) {
      showAlert("로그인이 필요합니다");
      return;
    }
    setReviewOrderItems(order.items);
    setReviewOrderItemId(null);
    setReviewContent("");
    setReviewRating(0);
    setEditingReviewId(null);
    setShowReviewModal(true);
  };

  const handleSelectReviewItem = (orderItemId: number) => {
    setReviewOrderItemId(orderItemId);
    const existingReview = reviewMap[orderItemId];
    if (existingReview) {
      setReviewContent(existingReview.content || "");
      setReviewRating(existingReview.rating);
      setEditingReviewId(existingReview.id);
    } else {
      setReviewContent("");
      setReviewRating(0);
      setEditingReviewId(null);
    }
  };

  const handleCloseReviewModal = () => {
    setShowReviewModal(false);
    setReviewOrderItems([]);
    setReviewOrderItemId(null);
    setReviewContent("");
    setReviewRating(0);
    setEditingReviewId(null);
  };

  const handleSubmitReview = async () => {
    if (!user || reviewOrderItemId === null) return;

    if (!reviewContent.trim()) {
      showAlert("리뷰 내용을 입력해주세요");
      return;
    }
    if (reviewRating < 1 || reviewRating > 5) {
      showAlert("평점을 선택해주세요 (1~5)");
      return;
    }

    setReviewSubmitting(true);
    try {
      let response: Response;

      if (editingReviewId) {
        // 리뷰 수정 (PUT)
        response = await fetch(
          `${API_BASE}/reviews/${editingReviewId}?user_id=${user.id}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              content: reviewContent,
              rating: reviewRating,
            }),
          }
        );
      } else {
        // 리뷰 신규 작성 (POST)
        response = await fetch(
          `${API_BASE}/reviews?user_id=${user.id}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              order_item_id: reviewOrderItemId,
              content: reviewContent,
              rating: reviewRating,
            }),
          }
        );
      }

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || (editingReviewId ? "리뷰 수정 실패" : "리뷰 작성 실패"));
      }

      showAlert(editingReviewId ? "리뷰가 수정되었습니다!" : "리뷰가 등록되었습니다! (100원 적립)");
      handleCloseReviewModal();
      fetchUserReviews(); // 리뷰 맵 갱신
    } catch (err) {
      console.error(err);
      showAlert(err instanceof Error ? err.message : (editingReviewId ? "리뷰 수정 실패" : "리뷰 작성 실패"));
    } finally {
      setReviewSubmitting(false);
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
                      {imageMap[`${item.product_option_type}_${item.product_id}`] && (
                        <img
                          src={imageMap[`${item.product_option_type}_${item.product_id}`]}
                          alt={item.product_name || '상품 이미지'}
                        />
                      )}
                    </div>
                    <div className={styles.itemInfo}>
                      <div className={styles.itemBrand}>
                        {item.product_option_type === "new"
                          ? "신상품"
                          : "중고상품"}
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
                  상세보기
                </button>

                {/* 배송 조회 (배송중 또는 배송완료) */}
                {(order.status === "shipped" ||
                  order.status === "delivered") && (
                    <button
                      className={styles.deliveryBtn}
                      onClick={() => handleShowShipping(order)}
                    >
                      배송조회
                    </button>
                  )}

                {/* 결제 완료, 상품 준비중 상태에서 주문 취소 가능 */}
                {(order.status === "paid" ||
                  order.status === "preparing") && (
                    <button
                      className={styles.detailBtn}
                      onClick={() => handleCancelOrder(order.id)}
                      style={{ backgroundColor: "#f44336" }}
                    >
                      주문취소
                    </button>
                  )}

                {/* 배송중, 배송 완료 상태에서 환불 가능 */}
                {(order.status === "shipped" ||
                  order.status === "delivered") && (
                    <button
                      className={styles.detailBtn}
                      onClick={() => handleRefundOrder(order.id)}
                      style={{ backgroundColor: "#ff9800" }}
                    >
                      환불요청
                    </button>
                  )}

                {/* 배송 완료 시 리뷰 작성/수정 */}
                {order.status === "delivered" && (
                  <button
                    className={styles.reviewBtn}
                    onClick={() => handleOpenReviewModal(order)}
                  >
                    리뷰 작성
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
                  {item.product_option_type === "new" ? "[신상품]" : "[중고]"} {item.product_name || `상품 옵션 ID: ${item.product_option_id}`}
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
            {shippingInfo.courier_company && (
              <div className={styles.modalItem}>
                <strong>택배사:</strong> {shippingInfo.courier_company}
              </div>
            )}
            <div className={styles.modalItem}>
              <strong>배송 상태:</strong>{" "}
              {selectedOrder?.status === "delivered"
                ? "배송 완료"
                : selectedOrder?.status === "shipped"
                  ? "배송중"
                  : "배송 준비중"}
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

      {/* 리뷰 작성/수정 모달 */}
      {showReviewModal && (
        <div
          className={styles.modalOverlay}
          onClick={handleCloseReviewModal}
        >
          <div
            className={styles.modalContent}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className={styles.closeBtn}
              onClick={handleCloseReviewModal}
            >
              ✕
            </button>

            {reviewOrderItemId === null ? (
              /* 아이템 선택 단계 */
              <>
                <h2>리뷰 작성할 상품 선택</h2>
                <div style={{ marginTop: "15px" }}>
                  {reviewOrderItems.map((item) => (
                    <div
                      key={item.id}
                      onClick={() => handleSelectReviewItem(item.id)}
                      style={{
                        padding: "12px",
                        border: "1px solid #eee",
                        borderRadius: "6px",
                        marginBottom: "10px",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        transition: "background-color 0.2s",
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "#f5f5f5")}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "white")}
                    >
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: "500" }}>
                          {item.product_option_type === "new" ? "[신상품]" : "[중고]"}{" "}
                          {item.product_name || `상품 옵션 ID: ${item.product_option_id}`}
                        </div>
                        {(item.product_size || item.product_color || item.product_condition) && (
                          <div style={{ fontSize: "13px", color: "#666", marginTop: "4px" }}>
                            {item.product_size && `사이즈: ${item.product_size}`}
                            {item.product_size && item.product_color && " · "}
                            {item.product_color && `색상: ${item.product_color}`}
                            {item.product_condition && ` · 상태: ${item.product_condition}`}
                          </div>
                        )}
                        <div style={{ fontSize: "13px", color: "#555", marginTop: "4px" }}>
                          {Number(item.unit_price).toLocaleString()}원 x {item.quantity}개
                        </div>
                      </div>
                      <div style={{ marginLeft: "12px", flexShrink: 0 }}>
                        {reviewMap[item.id] ? (
                          <span style={{ color: "#4caf50", fontSize: "13px", fontWeight: "500" }}>
                            작성완료 ★{reviewMap[item.id].rating}
                          </span>
                        ) : (
                          <span style={{ color: "#999", fontSize: "13px" }}>미작성</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              /* 리뷰 작성/수정 단계 */
              <>
                <div style={{ display: "flex", alignItems: "center", marginBottom: "10px" }}>
                  <button
                    onClick={() => {
                      setReviewOrderItemId(null);
                      setReviewContent("");
                      setReviewRating(0);
                      setEditingReviewId(null);
                    }}
                    style={{
                      border: "none",
                      background: "none",
                      cursor: "pointer",
                      fontSize: "18px",
                      padding: "0 8px 0 0",
                    }}
                  >
                    ←
                  </button>
                  <h2 style={{ margin: 0 }}>{editingReviewId ? "리뷰 수정" : "리뷰 작성"}</h2>
                </div>

                {/* 선택한 상품 정보 */}
                {(() => {
                  const selectedItem = reviewOrderItems.find(item => item.id === reviewOrderItemId);
                  if (!selectedItem) return null;
                  return (
                    <div style={{ padding: "10px", backgroundColor: "#f9f9f9", borderRadius: "6px", marginBottom: "15px" }}>
                      <div style={{ fontWeight: "500" }}>
                        {selectedItem.product_option_type === "new" ? "[신상품]" : "[중고]"}{" "}
                        {selectedItem.product_name || `상품 옵션 ID: ${selectedItem.product_option_id}`}
                      </div>
                      {(selectedItem.product_size || selectedItem.product_color || selectedItem.product_condition) && (
                        <div style={{ fontSize: "13px", color: "#666", marginTop: "4px" }}>
                          {selectedItem.product_size && `사이즈: ${selectedItem.product_size}`}
                          {selectedItem.product_size && selectedItem.product_color && " · "}
                          {selectedItem.product_color && `색상: ${selectedItem.product_color}`}
                          {selectedItem.product_condition && ` · 상태: ${selectedItem.product_condition}`}
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* 별점 선택 */}
                <div style={{ margin: "20px 0" }}>
                  <strong>평점</strong>
                  <div
                    className={styles.starRating}
                    onMouseLeave={() => setHoverRating(0)}
                  >
                    {[1, 2, 3, 4, 5].map((star) => {
                      const activeRating = hoverRating || reviewRating;
                      return (
                        <span
                          key={star}
                          className={`${styles.star} ${star <= activeRating ? styles.starActive : ""}`}
                          onClick={() => setReviewRating(star === reviewRating ? 0 : star)}
                          onMouseEnter={() => setHoverRating(star)}
                        >
                          ★
                        </span>
                      );
                    })}
                    <span style={{ marginLeft: "8px", fontSize: "14px", color: "#666" }}>
                      {`${reviewRating}점`}
                    </span>
                  </div>
                </div>

                {/* 리뷰 내용 */}
                <div style={{ marginBottom: "20px" }}>
                  <strong>리뷰 내용</strong>
                  <textarea
                    className={styles.reviewTextarea}
                    value={reviewContent}
                    onChange={(e) => setReviewContent(e.target.value)}
                    placeholder="상품에 대한 솔직한 리뷰를 작성해주세요."
                    style={{ marginTop: "8px" }}
                  />
                </div>

                {/* 제출 버튼 */}
                <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
                  <button
                    className={styles.detailBtn}
                    onClick={handleCloseReviewModal}
                    style={{ backgroundColor: "#999" }}
                  >
                    취소
                  </button>
                  <button
                    className={styles.submitReviewBtn}
                    onClick={handleSubmitReview}
                    disabled={reviewSubmitting}
                  >
                    {reviewSubmitting
                      ? (editingReviewId ? "수정 중..." : "등록 중...")
                      : (editingReviewId ? "리뷰 수정" : "리뷰 등록")}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* 커스텀 알림 모달 */}
      {customAlert && (
        <div className={styles.customAlertOverlay}>
          <div className={styles.customAlertBox}>
            <div className={styles.customAlertMessage}>
              {customAlert.message}
            </div>

            {customAlert.type === 'prompt' && (
              <input
                type="text"
                className={styles.customAlertInput}
                value={promptInput}
                onChange={(e) => setPromptInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleAlertConfirm();
                }}
                autoFocus
                placeholder="내용을 입력해주세요"
              />
            )}

            <div className={styles.customAlertButtons}>
              {(customAlert.type === 'confirm' || customAlert.type === 'prompt') && (
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
                autoFocus={customAlert.type === 'alert'}
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
