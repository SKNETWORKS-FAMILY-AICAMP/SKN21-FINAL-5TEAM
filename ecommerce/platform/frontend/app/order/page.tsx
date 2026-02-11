'use client';

import { useState, useEffect } from 'react';
import styles from './order.module.css';

interface OrderItem {
  id: number;
  productName: string;
  productBrand: string;
  productOptionType: 'new' | 'used';
  option?: {
    size?: string;
    color?: string;
    condition?: string;
  };
  quantity: number;
  unitPrice: number;
  subtotal: number;
}

interface ShippingInfo {
  courierCompany?: string;
  trackingNumber?: string;
  shippedAt?: string;
  deliveredAt?: string;
}

interface PaymentInfo {
  paymentMethod: string;
  paymentStatus: 'pending' | 'completed' | 'failed' | 'cancelled';
}

interface Order {
  id: number;
  orderNumber: string;
  createdAt: string;
  status: 'pending' | 'paid' | 'processing' | 'shipped' | 'delivered' | 'cancelled' | 'refunded';
  subtotal: number;
  discountAmount: number;
  shippingFee: number;
  totalAmount: number;
  pointsUsed: number;
  payment: PaymentInfo;
  shipping: ShippingInfo;
  items: OrderItem[];
}

const statusMap: Record<Order['status'], string> = {
  pending: '결제 대기',
  paid: '결제 완료',
  processing: '주문 처리 중',
  shipped: '배송 시작',
  delivered: '배송 완료',
  cancelled: '주문 취소',
  refunded: '환불 완료',
};

export default function OrderPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [loading, setLoading] = useState(true);

  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [modalType, setModalType] = useState<'detail' | 'shipping' | 'review' | null>(null);
  const [reviews, setReviews] = useState<Record<number, string>>({});
  const [isEditingReview, setIsEditingReview] = useState(false);

  const dummyOrders: Order[] = [
    {
      id: 1,
      orderNumber: 'ORD20260205001',
      createdAt: '2026-02-01',
      status: 'shipped',
      subtotal: 24000,
      discountAmount: 0,
      shippingFee: 2500,
      totalAmount: 26500,
      pointsUsed: 0,
      payment: { paymentMethod: '카드', paymentStatus: 'completed' },
      shipping: { courierCompany: 'CJ대한통운', trackingNumber: '1234567890', shippedAt: '2026-02-02' },
      items: [
        { id: 1, productName: '예시 상품 A', productBrand: '브랜드 A', productOptionType: 'used', option: { size: 'M', color: '빨강', condition: '좋음' }, quantity: 2, unitPrice: 12000, subtotal: 24000 }
      ]
    },
    {
      id: 2,
      orderNumber: 'ORD20260205002',
      createdAt: '2026-01-28',
      status: 'delivered',
      subtotal: 53000,
      discountAmount: 5000,
      shippingFee: 0,
      totalAmount: 48000,
      pointsUsed: 2000,
      payment: { paymentMethod: '계좌이체', paymentStatus: 'completed' },
      shipping: { courierCompany: '한진택배', trackingNumber: '0987654321', shippedAt: '2026-01-29', deliveredAt: '2026-01-30' },
      items: [
        { id: 2, productName: '예시 상품 B', productBrand: '브랜드 B', productOptionType: 'new', option: { size: 'L' }, quantity: 1, unitPrice: 8000, subtotal: 8000 },
        { id: 3, productName: '예시 상품 C', productBrand: '브랜드 C', productOptionType: 'new', quantity: 3, unitPrice: 15000, subtotal: 45000 }
      ]
    }
  ];

  useEffect(() => {
    setTimeout(() => {
      setOrders(dummyOrders);
      setLoading(false);
    }, 500);
  }, []);

  if (loading) return <div className={styles.loading}>주문 목록을 불러오는 중...</div>;

  if (!orders || orders.length === 0) {
    return (
      <div className={styles.emptyOrders}>
        <div className={styles.emptyIcon}>📦</div>
        <h2>주문한 내역이 없습니다</h2>
        <p>원하는 상품을 주문해보세요!</p>
      </div>
    );
  }

  /* ----------------- 모달 ----------------- */
  const Modal = () => {
    if (!selectedOrder || !modalType) return null;

    const closeModal = () => {
      setSelectedOrder(null);
      setModalType(null);
      setIsEditingReview(false);
    };

    const handleSubmitReview = () => {
      if (!selectedOrder) return;
      const orderId = selectedOrder.id;
      const reviewText = (document.getElementById('reviewTextarea') as HTMLTextAreaElement)?.value || '';
      setReviews(prev => ({ ...prev, [orderId]: reviewText }));
      setIsEditingReview(false);
      closeModal(); // 모달 닫기만 하고 알림 제거
    };

    return (
      <div className={styles.modalOverlay} onClick={closeModal}>
        <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
          <button className={styles.closeBtn} onClick={closeModal}>✖</button>

          {modalType === 'detail' && (
            <>
              <h2>주문 상세보기</h2>
              {selectedOrder.items.map(item => (
                <div key={item.id} className={styles.modalItem}>
                  <p>{item.productBrand} - {item.productName}</p>
                  <p>옵션: {item.option?.size || ''} {item.option?.color ? `/ ${item.option.color}` : ''} {item.option?.condition ? `/ ${item.option.condition}` : ''}</p>
                  <p>수량: {item.quantity}</p>
                  <p>가격: {item.subtotal.toLocaleString()}원</p>
                </div>
              ))}
            </>
          )}

          {modalType === 'shipping' && (
            <>
              <h2>배송 정보</h2>
              <p>배송사: {selectedOrder.shipping.courierCompany}</p>
              <p>송장번호: {selectedOrder.shipping.trackingNumber}</p>
              <p>발송일: {selectedOrder.shipping.shippedAt}</p>
              {selectedOrder.shipping.deliveredAt && <p>배송완료일: {selectedOrder.shipping.deliveredAt}</p>}
            </>
          )}

          {modalType === 'review' && (
            <>
              <h2>{reviews[selectedOrder.id] ? '리뷰 확인' : '리뷰 작성'}</h2>

              {reviews[selectedOrder.id] && !isEditingReview && (
                <>
                  <p>{reviews[selectedOrder.id]}</p>
                  <button className={styles.submitReviewBtn} onClick={() => setIsEditingReview(true)}>수정</button>
                </>
              )}

              {(!reviews[selectedOrder.id] || isEditingReview) && (
                <>
                  <textarea
                    id="reviewTextarea"
                    className={styles.reviewTextarea}
                    defaultValue={reviews[selectedOrder.id] || ''}
                    placeholder="리뷰를 작성해주세요."
                  />
                  <button className={styles.submitReviewBtn} onClick={handleSubmitReview}>제출</button>
                </>
              )}
            </>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={styles.wrapper}>
      <h1 className={styles.title}>주문목록</h1>
      <div className={styles.ordersList}>
        {orders.map(order => (
          <div key={order.id} className={styles.orderCard}>
            <div className={styles.orderHeader}>
              <span>주문번호: {order.orderNumber}</span>
              <span>주문일: {order.createdAt}</span>
              <span className={`${styles.status}`}>{statusMap[order.status]}</span>
            </div>

            <div className={styles.orderItems}>
              {order.items.map(item => (
                <div key={item.id} className={styles.orderItem}>
                  <div className={styles.itemImage}>
                    <img src={`https://via.placeholder.com/80`} alt={item.productName} />
                  </div>
                  <div className={styles.itemInfo}>
                    <p className={styles.itemBrand}>{item.productBrand}</p>
                    <h3 className={styles.itemName}>{item.productName}</h3>
                    <p className={styles.itemOption}>
                      {item.option?.size && `사이즈: ${item.option.size}`}
                      {item.option?.color && ` / 색상: ${item.option.color}`}
                      {item.option?.condition && ` / 상태: ${item.option.condition}`}
                    </p>
                    <p className={styles.itemQuantity}>수량: {item.quantity}</p>
                    <p className={styles.itemPrice}>{item.subtotal.toLocaleString()}원</p>
                  </div>
                </div>
              ))}
            </div>

            <div className={styles.orderSummary}>
              <span>상품금액: {order.subtotal.toLocaleString()}원</span>
              {order.discountAmount > 0 && <span>할인금액: -{order.discountAmount.toLocaleString()}원</span>}
              {order.pointsUsed > 0 && <span>포인트사용: -{order.pointsUsed.toLocaleString()}원</span>}
              <span>배송비: {order.shippingFee === 0 ? '무료' : `+${order.shippingFee.toLocaleString()}원`}</span>
              <span className={styles.finalAmount}>총 결제금액: {order.totalAmount.toLocaleString()}원</span>
              <span>결제수단: {order.payment.paymentMethod}</span>
              <span>결제상태: {order.payment.paymentStatus === 'completed' ? '결제 완료' : order.payment.paymentStatus}</span>
              {order.shipping.courierCompany && (
                <span>배송: {order.shipping.courierCompany} / 송장번호: {order.shipping.trackingNumber}</span>
              )}
            </div>

            <div className={styles.orderActions}>
              <button className={styles.detailBtn} onClick={() => { setSelectedOrder(order); setModalType('detail'); }}>주문 상세조회</button>
              {order.status === 'shipped' && (
                <button className={styles.deliveryBtn} onClick={() => { setSelectedOrder(order); setModalType('shipping'); }}>배송조회</button>
              )}
              {order.status === 'delivered' && (
                <button className={styles.reviewBtn} onClick={() => { setSelectedOrder(order); setModalType('review'); setIsEditingReview(false); }}>
                  {reviews[order.id] ? '리뷰 확인' : '리뷰작성'}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <Modal />
    </div>
  );
}
