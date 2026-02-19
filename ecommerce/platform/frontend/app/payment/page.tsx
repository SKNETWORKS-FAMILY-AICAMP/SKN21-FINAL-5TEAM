"use client";

import { useRouter } from 'next/navigation';
import { useState, useEffect } from "react";
import styles from "./payment.module.css";
import { useAuth } from '../authcontext';

// ==================== 타입 정의 (실제 Schemas 기반) ====================

type PaymentStatus = "pending" | "completed" | "failed" | "cancelled";
type OrderStatus = "pending" | "paid" | "preparing" | "shipped" | "delivered" | "cancelled" | "refunded";
type ProductType = "new" | "used";

// ==================== Carts 모듈 타입 (실제 schemas.py 기반) ====================

interface ProductOptionInfo {
  size: string | null;
  color: string | null;
  condition: string | null;
}

interface ProductInfo {
  id: number;
  name: string;
  brand: string;
  price: string;
  original_price: string | null;
  stock: number;
  shipping_fee: string;
  shipping_text: string;
  is_used: boolean;
  image: string;
  option: ProductOptionInfo;
}

interface CartItemDetailResponse {
  id: number;
  cart_id: number;
  quantity: number;
  product_option_type: ProductType;
  product_option_id: number;
  created_at: string;
  updated_at: string;
  product: ProductInfo;
}

interface CartDetailResponse {
  id: number;
  user_id: number;
  items: CartItemDetailResponse[];
  created_at: string;
  updated_at: string;
}

interface CartSummary {
  total_items: number;
  total_quantity: number;
  total_price: string;
  total_shipping_fee: string;
  final_total: string;
}

interface CartDetailWithSummary {
  cart: CartDetailResponse;
  summary: CartSummary;
}

// ==================== Shipping 모듈 타입 (실제 schemas.py 기반) ====================

interface ShippingAddress {
  id: number;
  user_id: number;
  recipient_name: string;
  address1: string;
  address2: string | null;
  post_code: string;
  phone: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
}

// ==================== Orders 모듈 타입 ====================

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
  status : OrderStatus;
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

// ==================== Payments 모듈 타입 ====================

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

// ==================== Points 모듈 타입 ====================

interface PointBalance {
  user_id: number;
  current_balance: string;
  total_earned: string;
  total_used: string;
}

// ==================== 메인 컴포넌트 ====================

export default function PaymentPage() {
  const router = useRouter();
  const [cartData, setCartData] = useState<CartDetailWithSummary | null>(null);
  const [addresses, setAddresses] = useState<ShippingAddress[]>([]);
  const [selectedAddress, setSelectedAddress] = useState<ShippingAddress | null>(null);
  const [cardNumber, setCardNumber] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [showAddressModal, setShowAddressModal] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [addFormData, setAddFormData] = useState({
    recipient_name: '',
    address1: '',
    address2: '',
    post_code: '',
    phone: '',
  });
  const [pointBalance, setPointBalance] = useState<PointBalance | null>(null);
  const [pointsToUse, setPointsToUse] = useState<string>("0");
  const [shippingRequest, setShippingRequest] = useState<string>("");
  const { user, isLoggedIn } = useAuth();

  const API_BASE = "http://localhost:8000";
  const PAYMENT_METHOD = "card"; // 고정: 신용카드만 가능

  // ==================== User History 기록 함수 ====================

  const trackOrderAction = async (orderId: number, actionType: "payment" | "order_del") => {
    try {
      if (!user) return;

      await fetch(`${API_BASE}/user-history/users/${user.id}/track/order`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          order_id: orderId,
          action_type: actionType,
        }),
      });

      console.log(`User history tracked: ${actionType} for order ${orderId}`);
    } catch (err) {
      console.error("Failed to track order action:", err);
      // 히스토리 기록 실패는 무시 (사용자 경험에 영향 없음)
    }
  };

  // 가격 계산 (Cart Summary 기반)
  const subtotal = cartData ? Number(cartData.summary.total_price) : 0;
  const shippingFee = cartData ? Number(cartData.summary.total_shipping_fee) : 0;
  const discount = 0;
  const pointsUsed = Number(pointsToUse) || 0;
  const totalAmount = subtotal + shippingFee - discount - pointsUsed;

  // ==================== 데이터 로딩 ====================

  useEffect(() => {
    if (user) {
      loadInitialData();
    }  
  }, [user]);

  const loadInitialData = async () => {
    try {
      setLoading(true);

      // 병렬로 데이터 로드
      await Promise.all([
        loadCartWithProducts(),
        loadAddresses(),
        loadPointBalance(), // 포인트 없어도 에러 무시
      ]);
    } catch (err) {
      console.error("Failed to load data:", err);
      alert("데이터를 불러오는데 실패했습니다");
    } finally {
      setLoading(false);
    }
  };

  // ==================== 장바구니 + 상품 정보 로드 (Carts CRUD 기반) ====================

  const loadCartWithProducts = async () => {
    try {
      // GET /carts/{user_id}
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/carts/${user.id}`);

      if (!response.ok) {
        throw new Error("장바구니를 불러오는데 실패했습니다");
      }

      const data: CartDetailWithSummary = await response.json();
      setCartData(data);

      console.log("Cart loaded:", data);
    } catch (err) {
      console.error("Failed to load cart:", err);
      throw err; // 장바구니는 필수이므로 에러 전파
    }
  };

  // ==================== 배송지 목록 로드 (Shipping CRUD 기반) ====================

  const loadAddresses = async () => {
    try {
      // GET /shipping?user_id={user_id}
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/shipping?user_id=${user.id}`);

      if (!response.ok) {
        throw new Error("배송지를 불러오는데 실패했습니다");
      }

      const data: ShippingAddress[] = await response.json();
      setAddresses(data);

      // 기본 배송지 자동 선택
      const defaultAddr = data.find((addr) => addr.is_default);
      if (defaultAddr) {
        setSelectedAddress(defaultAddr);
      } else if (data.length > 0) {
        setSelectedAddress(data[0]);
      }

      console.log("Addresses loaded:", data);
    } catch (err) {
      console.error("Failed to load addresses:", err);
      // 배송지는 필수이므로 에러 전파
      throw err;
    }
  };

  // ==================== 포인트 잔액 조회 (Points CRUD 기반) ====================

  const loadPointBalance = async () => {
    try {
      // GET /points/users/{user_id}/balance
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/points/users/${user.id}/balance`);

      if (!response.ok) {
        // 포인트 시스템이 없거나 사용자에게 포인트가 없을 수 있음
        console.warn("포인트 정보를 불러올 수 없습니다");
        setPointBalance(null);
        return;
      }

      const data: PointBalance = await response.json();
      
      // 잔액이 0이면 null 처리
      if (Number(data.current_balance) === 0) {
        setPointBalance(null);
      } else {
        setPointBalance(data);
      }

      console.log("Point balance loaded:", data);
    } catch (err) {
      console.error("Failed to load point balance:", err);
      // 포인트는 선택사항이므로 에러 무시
      setPointBalance(null);
    }
  };

  // ==================== 주문 생성 (Orders CRUD 기반) ====================

  const createOrder = async (): Promise<number> => {
    try {
      if (!selectedAddress) {
        throw new Error("배송지를 선택해주세요");
      }

      if (!cartData || cartData.cart.items.length === 0) {
        throw new Error("장바구니가 비어있습니다");
      }

      // OrderCreate 스키마에 맞게 데이터 구성
      const orderItems: OrderItemCreate[] = cartData.cart.items.map((item) => ({
        product_option_type: item.product_option_type,
        product_option_id: item.product_option_id,
        quantity: item.quantity,
        unit_price: item.product.price,
      }));

      const orderData: OrderCreate = {
        shipping_address_id: selectedAddress.id,
        payment_method: PAYMENT_METHOD, // "card" 고정
        shipping_request: shippingRequest || null,
        points_used: pointsToUse,
        status : 'pending', // 결제 대기 상태로 시작
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
      console.log("Order created:", order);
      return order.id;
    } catch (err) {
      console.error("Failed to create order:", err);
      throw err;
    }
  };

  // ==================== 결제 처리 (Payments CRUD의 process_payment) ====================

  const handlePayment = async () => {
    if (!selectedAddress) {
      alert("배송지를 선택해주세요");
      return;
    }

    if (!cartData || cartData.cart.items.length === 0) {
      alert("장바구니가 비어있습니다");
      return;
    }

    if (!cardNumber) {
      alert("카드번호를 입력해주세요");
      return;
    }

    // 포인트 사용 금액 검증 (포인트가 있는 경우만)
    const pointsValue = Number(pointsToUse) || 0;
    if (pointsValue > 0 && pointBalance && pointsValue > Number(pointBalance.current_balance)) {
      alert("포인트 잔액이 부족합니다");
      return;
    }

    if (!confirm(`${totalAmount.toLocaleString()}원을 결제하시겠습니까?`)) {
      return;
    }

    try {
      setProcessing(true);

      // 1. 주문 생성 (pending 상태로)
      const orderId = await createOrder();
      console.log("Order created:", orderId);

      // 1-1. User History에 결제 기록
      await trackOrderAction(orderId, "payment");

      // 2. 결제 처리 (Payments CRUD의 process_payment)
      const maskedCard = maskCardNumber(cardNumber);

      const params = new URLSearchParams({
        payment_method: PAYMENT_METHOD, // "card" 고정
        card_numbers: maskedCard,
      });

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

      // 3. 결제 성공 - 주문 상태는 process_payment에서 이미 'paid'로 변경됨

      // 4. 포인트 사용 (Points CRUD 기반) - 포인트를 사용하는 경우만
      if (pointsValue > 0 && pointBalance) {
        await usePoints(pointsValue);
      }

      // 5. 장바구니 비우기 (Carts CRUD 기반)
      await clearCart();

      // 6. 포인트 적립 (구매 금액의 1%) - 포인트 시스템이 있는 경우만
      if (pointBalance !== null) {
        const earnPoints = Math.floor(totalAmount * 0.01);
        if (earnPoints > 0) {
          await earnPointsAfterPurchase(earnPoints, orderId);
        }
      }

      // 결제 성공
      alert("결제가 완료되었습니다!");

      // 주문 상세 페이지로 이동
      router.push('/order');
    } catch (err) {
      console.error("Payment failed:", err);
      alert(err instanceof Error ? err.message : "결제 처리 중 오류가 발생했습니다.\n주문은 '결제 대기' 상태로 주문 목록에서 확인하실 수 있습니다.");
      // 결제 실패 시 주문은 pending 상태로 유지, 장바구니도 그대로 유지
      router.push('/order'); // 주문 목록으로 이동하여 pending 상태 확인 가능
    } finally {
      setProcessing(false);
    }
  };

  // ==================== 포인트 사용 (Points CRUD 기반) ====================

  const usePoints = async (amount: number) => {
    try {
      // POST /points/users/{user_id}/use
      if (!user) throw new Error("유저 정보가 없습니다");
      const response = await fetch(`${API_BASE}/points/users/${user.id}/use`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          amount: amount.toString(),
          description: "상품 구매 시 포인트 사용",
          order_id: null,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "포인트 사용에 실패했습니다");
      }

      console.log("Points used:", amount);
    } catch (err) {
      console.error("Failed to use points:", err);
      throw err;
    }
  };

  // ==================== 포인트 적립 (Points CRUD 기반) ====================

  const earnPointsAfterPurchase = async (amount: number, orderId: number) => {
    try {
      // POST /points/users/{user_id}/earn
      if (!user) throw new Error("유저 정보가 없습니다");
      await fetch(`${API_BASE}/points/users/${user.id}/earn`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          amount: amount.toString(),
          description: `주문 ${orderId} 구매 적립`,
          order_id: orderId,
        }),
      });

      console.log("Points earned:", amount);
    } catch (err) {
      console.error("Failed to earn points:", err);
      // 포인트 적립 실패는 무시 (결제는 이미 완료됨)
    }
  };

  // ==================== 장바구니 비우기 (Carts CRUD 기반) ====================

  const clearCart = async () => {
    try {
      // DELETE /carts/{user_id}/clear
      if (!user) throw new Error("유저 정보가 없습니다");
      await fetch(`${API_BASE}/carts/${user.id}/clear`, {
        method: "DELETE",
      });

      console.log("Cart cleared");
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

  const handlePointsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value.replace(/\D/g, "");
    const numValue = Number(value);
    
    // 최대값 제한
    const maxPoints = Math.min(
      pointBalance ? Number(pointBalance.current_balance) : 0,
      subtotal // 상품금액까지만 사용 가능
    );

    if (numValue > maxPoints) {
      setPointsToUse(maxPoints.toString());
    } else {
      setPointsToUse(value);
    }
  };

  const useAllPoints = () => {
    if (!pointBalance) return;
    
    const maxPoints = Math.min(
      Number(pointBalance.current_balance),
      subtotal
    );

    setPointsToUse(maxPoints.toString());
  };

  // ==================== 배송지 선택 ====================

  const handleSelectAddress = (address: ShippingAddress) => {
    setSelectedAddress(address);
    setShowAddressModal(false);
  };

  // ==================== 배송지 추가 (Shipping CRUD 기반) ====================

  const openAddAddressForm = () => {
    setAddFormData({ recipient_name: '', address1: '', address2: '', post_code: '', phone: '' });
    setShowAddForm(true);
  };

  const saveNewAddress = async () => {
    if (!addFormData.recipient_name || !addFormData.address1 || !addFormData.phone) {
      alert("수령인 이름, 기본 주소, 전화번호는 필수입니다.");
      return;
    }

    try {
      if (!user) throw new Error("유저 정보가 없습니다");

      const payload = {
        recipient_name: addFormData.recipient_name,
        address1: addFormData.address1,
        address2: addFormData.address2 || "",
        post_code: addFormData.post_code || "",
        phone: addFormData.phone,
        is_default: addresses.length === 0,
      };

      const res = await fetch(`${API_BASE}/shipping?user_id=${user.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) throw new Error('배송지 저장 실패');

      // 배송지 목록 다시 로드
      await loadAddresses();
      setShowAddForm(false);
    } catch (err) {
      console.error(err);
      alert("배송지 저장에 실패했습니다.");
    }
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

  if (!cartData || cartData.cart.items.length === 0) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>
          <h1 className={styles.title}>결제하기</h1>
          <div style={{ textAlign: "center", padding: "50px 0" }}>
            결제할 상품이 없습니다.
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
                  <strong>{selectedAddress.recipient_name}</strong>
                  {selectedAddress.is_default && (
                    <span style={{ color: "#0070f3", marginLeft: "8px" }}>[기본]</span>
                  )}
                </p>
                <p>{selectedAddress.phone}</p>
                <p>
                  [{selectedAddress.post_code}] {selectedAddress.address1}
                </p>
                {selectedAddress.address2 && <p>{selectedAddress.address2}</p>}
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

        {/* 주문 상품 (Cart with Product Info) */}
        <div className={styles.section}>
          <h2>주문 상품 ({cartData.summary.total_items}종 / {cartData.summary.total_quantity}개)</h2>
          <div className={styles.itemsList}>
            {cartData.cart.items.map((item) => (
              <div key={item.id} className={styles.cartItem}>
                <div style={{ width: "80px", height: "80px", marginRight: "12px" }}>
                  <img
                    src={item.product.image}
                    alt={item.product.name}
                    style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "4px" }}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <div className={styles.itemInfo}>
                    <p>
                      <strong>
                        {item.product.is_used ? "♻️ 중고상품" : "🆕 신상품"} {item.product.brand}
                      </strong>
                    </p>
                    <p>{item.product.name}</p>
                    {(item.product.option.size || item.product.option.color) && (
                      <p style={{ fontSize: "13px", color: "#666" }}>
                        {item.product.option.size && `사이즈: ${item.product.option.size}`}
                        {item.product.option.color && ` / 색상: ${item.product.option.color}`}
                        {item.product.option.condition && ` / 상태: ${item.product.option.condition}`}
                      </p>
                    )}
                    <p>
                      수량: {item.quantity}개 x {Number(item.product.price).toLocaleString()}원
                    </p>
                    <p style={{ fontSize: "12px", color: "#666" }}>
                      {item.product.shipping_text}
                    </p>
                  </div>
                </div>
                <div>
                  <strong>
                    {(Number(item.product.price) * item.quantity).toLocaleString()}원
                  </strong>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 배송 요청사항 */}
        <div className={styles.section}>
          <h2>배송 요청사항</h2>
          <textarea
            value={shippingRequest}
            onChange={(e) => setShippingRequest(e.target.value)}
            placeholder="배송 시 요청사항을 입력해주세요 (예: 부재 시 문 앞에 놔주세요)"
            style={{
              width: "100%",
              minHeight: "80px",
              padding: "12px",
              borderRadius: "4px",
              border: "1px solid #ccc",
              fontSize: "14px",
              resize: "vertical",
            }}
            maxLength={200}
          />
        </div>

        {/* 포인트 사용 - 포인트가 있는 경우만 표시 */}
        {pointBalance && Number(pointBalance.current_balance) > 0 && (
          <div className={styles.section}>
            <h2>포인트 사용</h2>
            <div style={{ marginBottom: "12px" }}>
              <p>
                보유 포인트: <strong>{Number(pointBalance.current_balance).toLocaleString()}P</strong>
              </p>
            </div>
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <input
                type="text"
                value={pointsToUse}
                onChange={handlePointsChange}
                placeholder="0"
                style={{
                  flex: 1,
                  padding: "8px",
                  borderRadius: "4px",
                  border: "1px solid #ccc",
                }}
              />
              <span>P</span>
              <button
                onClick={useAllPoints}
                style={{
                  padding: "8px 16px",
                  borderRadius: "4px",
                  border: "1px solid #000",
                  backgroundColor: "#fff",
                  cursor: "pointer",
                }}
              >
                전액 사용
              </button>
            </div>
          </div>
        )}

        {/* 카드 결제 정보 */}
        <div className={styles.section}>
          <h2>카드 결제</h2>
          <div style={{ marginBottom: "16px" }}>
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
          <p style={{ fontSize: "13px", color: "#666" }}>
            💳 신용/체크카드로 안전하게 결제됩니다
          </p>
        </div>

        {/* 결제 금액 (Cart Summary 기반) */}
        <div className={styles.section}>
          <h2>결제 금액</h2>
          <div className={styles.priceRows}>
            <div className={styles.priceRow}>
              <span>상품금액</span>
              <span>{Number(cartData.summary.total_price).toLocaleString()}원</span>
            </div>
            <div className={styles.priceRow}>
              <span>배송비</span>
              <span>+{Number(cartData.summary.total_shipping_fee).toLocaleString()}원</span>
            </div>
            {discount > 0 && (
              <div className={styles.priceRow}>
                <span>할인</span>
                <span style={{ color: "red" }}>-{discount.toLocaleString()}원</span>
              </div>
            )}
            {pointsUsed > 0 && (
              <div className={styles.priceRow}>
                <span>포인트 사용</span>
                <span style={{ color: "#9c27b0" }}>-{pointsUsed.toLocaleString()}P</span>
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
      {showAddressModal && !showAddForm && (
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
                      <strong>{address.recipient_name}</strong>
                      {address.is_default && (
                        <span style={{ color: "#0070f3", marginLeft: "8px" }}>[기본]</span>
                      )}
                    </p>
                    <p>{address.phone}</p>
                    <p>
                      [{address.post_code}] {address.address1}
                    </p>
                    {address.address2 && <p>{address.address2}</p>}
                  </div>
                </div>
              ))
            )}

            <div className={styles.modalButtons} style={{ marginTop: "12px" }}>
              <button
                className={styles.saveButton}
                onClick={openAddAddressForm}
              >
                + 배송지 추가
              </button>
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

      {/* 배송지 추가 모달 */}
      {showAddForm && (
        <div className={styles.modalOverlay} onClick={() => setShowAddForm(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <h2>배송지 추가</h2>
            <div className={styles.newAddressForm}>
              <input
                type="text"
                placeholder="수령인 이름"
                value={addFormData.recipient_name}
                onChange={e => setAddFormData({ ...addFormData, recipient_name: e.target.value })}
              />
              <input
                type="text"
                placeholder="우편번호"
                value={addFormData.post_code}
                onChange={e => setAddFormData({ ...addFormData, post_code: e.target.value })}
              />
              <input
                type="text"
                placeholder="기본 주소"
                value={addFormData.address1}
                onChange={e => setAddFormData({ ...addFormData, address1: e.target.value })}
              />
              <input
                type="text"
                placeholder="상세 주소"
                value={addFormData.address2}
                onChange={e => setAddFormData({ ...addFormData, address2: e.target.value })}
              />
              <input
                type="text"
                placeholder="전화번호"
                value={addFormData.phone}
                onChange={e => setAddFormData({ ...addFormData, phone: e.target.value })}
              />
            </div>
            <div className={styles.modalButtons} style={{ marginTop: "12px" }}>
              <button className={styles.cancelButton} onClick={() => setShowAddForm(false)}>취소</button>
              <button className={styles.saveButton} onClick={saveNewAddress}>저장</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
