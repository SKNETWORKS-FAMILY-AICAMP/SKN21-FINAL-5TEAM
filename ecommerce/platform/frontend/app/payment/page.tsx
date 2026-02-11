"use client";

import { useState, useEffect } from "react";
import styles from "./payment.module.css";
import { useAuth } from '../authcontext';

// ==================== 타입 정의 (Schemas 기반) ====================

type PaymentStatus = "pending" | "completed" | "failed" | "cancelled";
type OrderStatus = "pending" | "payment_completed" | "preparing" | "shipped" | "delivered" | "cancelled" | "refunded";
type ProductType = "new" | "used";

// Cart 관련
interface CartItem {
  id: number;
  user_id: number;
  product_option_type: ProductType;
  product_option_id: number;
  quantity: number;
  created_at: string;
}

// Shipping 관련
interface ShippingAddress {
  id: number;
  user_id: number;
  address_name: string;
  recipient_name: string;
  phone_number: string;
  address: string;
  detail_address: string | null;
  postal_code: string;
  is_default: boolean;
  created_at: string;
}

// Order 관련
interface OrderItemCreate {
  product_option_type: ProductType;
  product_option_id: number;
  quantity: number;
  unit_price: string;
}

interface OrderCreate {
  shipping_address_id: number;
  payment_method: string;
  shipping_request: string | null;
  points_used: string;
  items: OrderItemCreate[];
}

interface OrderDetailResponse {
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
  items: any[];
  payment: PaymentResponse | null;
  shipping_info: any | null;
}

// Payment 관련 (Schemas 기반)
interface PaymentResponse {
  id: number;
  order_id: number;
  payment_method: string;
  payment_data: string | null;
  payment_status: PaymentStatus;
  card_numbers: string | null;
  created_at: string;
  updated_at: string;
}

// Product 정보 (가격 조회용)
interface ProductOption {
  id: number;
  price: string;
  product_id: number;
}

// ==================== 메인 컴포넌트 ====================

export default function PaymentPage() {
  const [cartItems, setCartItems] = useState<CartItem[]>([]);
  const [addresses, setAddresses] = useState<ShippingAddress[]>([]);
  const [selectedAddress, setSelectedAddress] = useState<ShippingAddress | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<string>("card");
  const [cardNumber, setCardNumber] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [showAddressModal, setShowAddressModal] = useState(false);
  const [productPrices, setProductPrices] = useState<Map<number, string>>(new Map());
  const {user, isLoggedIn } = useAuth();

  const API_BASE = "http://localhost:8000";

  // 가격 계산
  const subtotal = cartItems.reduce((sum, item) => {
    const price = productPrices.get(item.product_option_id) || "0";
    return sum + Number(price) * item.quantity;
  }, 0);
  const shippingFee = subtotal >= 50000 ? 0 : 3000;
  const discount = 0;
  const totalAmount = subtotal + shippingFee - discount;

  // ==================== 데이터 로딩 ====================

  useEffect(() => {
    if(user){
      loadInitialData();
    }
  }, [user]);

  const loadInitialData = async () => {
    try {
      setLoading(true);

      // 1. 장바구니 아이템 로드 (실제 DB 연동)
      await loadCartItems();

      // 2. 배송지 목록 로드 (실제 DB 연동)
      await loadAddresses();
    } catch (err) {
      console.error("Failed to load data:", err);
      alert("데이터를 불러오는데 실패했습니다");
    } finally {
      setLoading(false);
    }
  };

  // ==================== 장바구니 데이터 로드 (실제 DB) ====================

  const loadCartItems = async () => {
    try {
      // GET /carts/users/{user_id}/items
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/carts/${user.id}`);

      if (!response.ok) {
        throw new Error("장바구니를 불러오는데 실패했습니다");
      }

      const items: CartItem[] = await response.json();
      const itemsArray = Array.isArray(items) ? items : [items];
      setCartItems(itemsArray);

      // 각 상품의 가격 정보 로드
      await loadProductPrices(itemsArray);
    } catch (err) {
      console.error("Failed to load cart items:", err);
      // 에러 발생 시 빈 배열 유지
    }
  };

  // ==================== 상품 가격 정보 로드 ====================

  const loadProductPrices = async (items: CartItem[]) => {
    const pricesMap = new Map<number, string>();

    for (const item of items) {
      try {
        let price = "0";

        if (item.product_option_type === "new") {
          // GET /products/new/{product_id}/options
          // 실제로는 product_option_id로 직접 조회하는 API 필요
          // 여기서는 간단히 고정 가격 사용
          price = "100000"; // 임시 가격
        } else {
          // 중고상품 가격
          price = "50000"; // 임시 가격
        }

        pricesMap.set(item.product_option_id, price);
      } catch (err) {
        console.error(`Failed to load price for option ${item.product_option_id}:`, err);
      }
    }

    setProductPrices(pricesMap);
  };

  // ==================== 배송지 목록 로드 (실제 DB) ====================

  const loadAddresses = async () => {
    try {
      // GET /shipping/users/{user_id}/addresses
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/shipping/?user_id=${user.id}`);

      if (!response.ok) {
        throw new Error("배송지를 불러오는데 실패했습니다");
      }

      const data: ShippingAddress[] = await response.json();
      const addressArray = Array.isArray(data) ? data : (data ? [data] : []);
      
      setAddresses(addressArray);

      // 기본 배송지 자동 선택
      const defaultAddr = data.find((addr) => addr.is_default);
      if (defaultAddr) {
        setSelectedAddress(defaultAddr);
      } else if (data.length > 0) {
        setSelectedAddress(data[0]);
      }
    } catch (err) {
      console.error("Failed to load addresses:", err);
    }
  };

  // ==================== 주문 생성 (실제 DB) ====================

  const createOrder = async (): Promise<number> => {
    try {
      if (!selectedAddress) {
        throw new Error("배송지를 선택해주세요");
      }

      if (cartItems.length === 0) {
        throw new Error("장바구니가 비어있습니다");
      }

      // OrderCreate 스키마에 맞게 데이터 구성
      const orderItems: OrderItemCreate[] = cartItems.map((item) => ({
        product_option_type: item.product_option_type,
        product_option_id: item.product_option_id,
        quantity: item.quantity,
        unit_price: productPrices.get(item.product_option_id) || "0",
      }));

      const orderData: OrderCreate = {
        shipping_address_id: selectedAddress.id,
        payment_method: paymentMethod,
        shipping_request: null,
        points_used: "0",
        items: orderItems,
      };

      // POST /orders/{user_id}/orders
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/orders/${user.id}/orders`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(orderData),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "주문 생성에 실패했습니다");
      }

      const order: OrderDetailResponse = await response.json();
      return order.id;
    } catch (err) {
      console.error("Failed to create order:", err);
      throw err;
    }
  };

  // ==================== 결제 처리 (실제 DB - CRUD의 process_payment) ====================

  const handlePayment = async () => {
    if (!selectedAddress) {
      alert("배송지를 선택해주세요");
      return;
    }

    if (cartItems.length === 0) {
      alert("장바구니가 비어있습니다");
      return;
    }

    if (paymentMethod === "card" && !cardNumber) {
      alert("카드번호를 입력해주세요");
      return;
    }

    if (!confirm(`${totalAmount.toLocaleString()}원을 결제하시겠습니까?`)) {
      return;
    }

    try {
      setProcessing(true);

      // 1. 주문 생성
      const orderId = await createOrder();
      console.log("Order created:", orderId);

      // 2. 결제 처리 (CRUD의 process_payment 함수 사용)
      // POST /payments/orders/{order_id}/process
      const maskedCard = paymentMethod === "card" ? maskCardNumber(cardNumber) : null;

      const params = new URLSearchParams({
        payment_method: paymentMethod,
      });

      if (maskedCard) {
        params.append("card_numbers", maskedCard);
      }

      const paymentResponse = await fetch(
        `${API_BASE}/payments/orders/${orderId}/process?${params.toString()}`,
        {
          method: "POST",
        }
      );

      if (!paymentResponse.ok) {
        const errorData = await paymentResponse.json();
        throw new Error(errorData.detail || "결제 처리에 실패했습니다");
      }

      const payment: PaymentResponse = await paymentResponse.json();
      console.log("Payment processed:", payment);

      // 3. 장바구니 비우기 (선택사항)
      await clearCart();

      // 결제 성공
      alert("결제가 완료되었습니다!");

      // 주문 상세 페이지로 이동
      window.location.href = `/orders/${orderId}`;
    } catch (err) {
      console.error("Payment failed:", err);
      alert(err instanceof Error ? err.message : "결제 처리 중 오류가 발생했습니다");
    } finally {
      setProcessing(false);
    }
  };

  // ==================== 장바구니 비우기 ====================

  const clearCart = async () => {
    try {
      for (const item of cartItems) {
        // DELETE /carts/items/{cart_item_id}
        await fetch(`${API_BASE}/carts/items/${item.id}`, {
          method: "DELETE",
        });
      }
    } catch (err) {
      console.error("Failed to clear cart:", err);
      // 에러 무시 (결제는 완료됨)
    }
  };

  // ==================== 유틸리티 함수 ====================

  const maskCardNumber = (cardNum: string): string => {
    const cleaned = cardNum.replace(/\D/g, "");
    if (cleaned.length !== 16) return cardNum;
    return cleaned.substring(0, 4) + "-****-****-" + cleaned.substring(12, 16);
  };

  const formatCardNumber = (value: string): string => {
    const cleaned = value.replace(/\D/g, "");
    const formatted = cleaned.match(/.{1,4}/g)?.join("-") || cleaned;
    return formatted.substring(0, 19);
  };

  const handleCardNumberChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const formatted = formatCardNumber(e.target.value);
    setCardNumber(formatted);
  };

  // ==================== 배송지 선택 ====================

  const handleSelectAddress = (address: ShippingAddress) => {
    setSelectedAddress(address);
    setShowAddressModal(false);
  };

  // ==================== 로딩 처리 ====================

  if (loading) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>
          <div style={{ textAlign: "center", padding: "50px 0" }}>
            결제 정보를 불러오는 중...
          </div>
        </div>
      </div>
    );
  }

  if (cartItems.length === 0) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>
          <h1 className={styles.title}>결제하기</h1>
          <div style={{ textAlign: "center", padding: "50px 0" }}>
            장바구니가 비어있습니다
          </div>
        </div>
      </div>
    );
  }

  // ==================== 렌더링 ====================

  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
        <h1 className={styles.title}>결제하기</h1>

        {/* 배송지 정보 */}
        <div className={styles.section}>
          <h2>배송지 정보</h2>
          {selectedAddress ? (
            <div className={styles.addressBox}>
              <div className={styles.addressInfo}>
                <p>
                  <strong>{selectedAddress.address_name}</strong>
                  {selectedAddress.is_default && (
                    <span style={{ color: "#0070f3", marginLeft: "8px" }}>[기본]</span>
                  )}
                </p>
                <p>{selectedAddress.recipient_name}</p>
                <p>{selectedAddress.phone_number}</p>
                <p>
                  [{selectedAddress.postal_code}] {selectedAddress.address}
                </p>
                {selectedAddress.detail_address && <p>{selectedAddress.detail_address}</p>}
              </div>
              <button
                className={styles.changeAddressButton}
                onClick={() => setShowAddressModal(true)}
              >
                변경
              </button>
            </div>
          ) : (
            <div>
              <p>배송지가 없습니다.</p>
              <button
                className={styles.changeAddressButton}
                onClick={() => setShowAddressModal(true)}
              >
                배송지 추가
              </button>
            </div>
          )}
        </div>

        {/* 주문 상품 */}
        <div className={styles.section}>
          <h2>주문 상품</h2>
          <div className={styles.itemsList}>
            {cartItems.map((item) => {
              const price = productPrices.get(item.product_option_id) || "0";
              return (
                <div key={item.id} className={styles.cartItem}>
                  <div style={{ flex: 1 }}>
                    <div className={styles.itemInfo}>
                      <p>
                        <strong>
                          {item.product_option_type === "new" ? "🆕 신상품" : "♻️ 중고상품"}
                        </strong>
                      </p>
                      <p>옵션 ID: {item.product_option_id}</p>
                      <p>
                        수량: {item.quantity}개 x {Number(price).toLocaleString()}원
                      </p>
                    </div>
                  </div>
                  <div>
                    <strong>{(Number(price) * item.quantity).toLocaleString()}원</strong>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* 결제 수단 */}
        <div className={styles.section}>
          <h2>결제 수단</h2>
          <div className={styles.paymentMethods}>
            <label>
              <input
                type="radio"
                value="card"
                checked={paymentMethod === "card"}
                onChange={(e) => setPaymentMethod(e.target.value)}
              />
              신용/체크카드
            </label>
            <label>
              <input
                type="radio"
                value="transfer"
                checked={paymentMethod === "transfer"}
                onChange={(e) => setPaymentMethod(e.target.value)}
              />
              계좌이체
            </label>
            <label>
              <input
                type="radio"
                value="phone"
                checked={paymentMethod === "phone"}
                onChange={(e) => setPaymentMethod(e.target.value)}
              />
              휴대폰 결제
            </label>
            <label>
              <input
                type="radio"
                value="kakaopay"
                checked={paymentMethod === "kakaopay"}
                onChange={(e) => setPaymentMethod(e.target.value)}
              />
              카카오페이
            </label>
          </div>

          {/* 카드번호 입력 */}
          {paymentMethod === "card" && (
            <div style={{ marginTop: "16px" }}>
              <label>
                카드번호:
                <input
                  type="text"
                  value={cardNumber}
                  onChange={handleCardNumberChange}
                  placeholder="1234-5678-9012-3456"
                  style={{
                    marginLeft: "8px",
                    padding: "8px",
                    borderRadius: "4px",
                    border: "1px solid #ccc",
                    width: "250px",
                  }}
                />
              </label>
            </div>
          )}
        </div>

        {/* 결제 금액 */}
        <div className={styles.section}>
          <h2>결제 금액</h2>
          <div className={styles.priceRows}>
            <div className={styles.priceRow}>
              <span>상품금액</span>
              <span>{subtotal.toLocaleString()}원</span>
            </div>
            <div className={styles.priceRow}>
              <span>배송비</span>
              <span>+{shippingFee.toLocaleString()}원</span>
            </div>
            {discount > 0 && (
              <div className={styles.priceRow}>
                <span>할인</span>
                <span style={{ color: "red" }}>-{discount.toLocaleString()}원</span>
              </div>
            )}
          </div>
          <div className={styles.totalPrice}>
            <span>최종 결제 금액</span>
            <span className={styles.finalAmount}>{totalAmount.toLocaleString()}원</span>
          </div>
        </div>

        {/* 결제 버튼 */}
        <button
          className={styles.payButton}
          onClick={handlePayment}
          disabled={processing}
        >
          {processing ? "결제 처리 중..." : `${totalAmount.toLocaleString()}원 결제하기`}
        </button>
      </div>

      {/* 배송지 선택 모달 */}
      {showAddressModal && (
        <div className={styles.modalOverlay} onClick={() => setShowAddressModal(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h2>배송지 선택</h2>

            {addresses.length === 0 ? (
              <p>등록된 배송지가 없습니다.</p>
            ) : (
              addresses.map((address) => (
                <div
                  key={address.id}
                  className={`${styles.addressBoxOption} ${
                    selectedAddress?.id === address.id ? styles.selectedBox : ""
                  }`}
                  onClick={() => handleSelectAddress(address)}
                >
                  <input
                    type="radio"
                    checked={selectedAddress?.id === address.id}
                    onChange={() => {}}
                  />
                  <div className={styles.addressDetails}>
                    <p>
                      <strong>{address.address_name}</strong>
                      {address.is_default && (
                        <span style={{ color: "#0070f3", marginLeft: "8px" }}>[기본]</span>
                      )}
                    </p>
                    <p>{address.recipient_name}</p>
                    <p>{address.phone_number}</p>
                    <p>
                      [{address.postal_code}] {address.address}
                    </p>
                    {address.detail_address && <p>{address.detail_address}</p>}
                  </div>
                </div>
              ))
            )}

            <div className={styles.modalButtons}>
              <button
                className={styles.cancelButton}
                onClick={() => setShowAddressModal(false)}
              >
                취소
              </button>
              <button
                className={styles.saveButton}
                onClick={() => setShowAddressModal(false)}
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
