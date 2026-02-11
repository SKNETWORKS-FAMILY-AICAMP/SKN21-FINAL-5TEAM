'use client';

import { useState, useEffect } from 'react';
import styles from './payment.module.css';

interface Product {
  id: number;
  name: string;
  brand: string;
  price: number;
  original_price?: number;
  image: string;
  option: {
    size?: string;
    color?: string;
    condition?: string;
  };
}

interface CartItem {
  id: number;
  quantity: number;
  product: Product;
}

interface PaymentData {
  items: CartItem[];
}

interface Address {
  id: number;
  name: string;
  address: string;
  phone: string;
}

export default function PaymentPage() {
  const [paymentData, setPaymentData] = useState<PaymentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedPaymentMethod, setSelectedPaymentMethod] = useState<string>('card');

  // 배송지 상태
  const [address, setAddress] = useState<Address>({
    id: 1,
    name: '홍길동',
    address: '서울특별시 강남구 테헤란로 123',
    phone: '010-1234-5678',
  });

  // 저장된 배송지 목록
  const savedAddresses: Address[] = [
    { id: 1, name: '홍길동', address: '서울특별시 강남구 테헤란로 123', phone: '010-1234-5678' },
    { id: 2, name: '김철수', address: '서울특별시 서초구 서초대로 456', phone: '010-9876-5432' },
    { id: 3, name: '이영희', address: '서울특별시 송파구 올림픽로 789', phone: '010-5555-6666' },
  ];

  // 모달 상태
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedModalAddressId, setSelectedModalAddressId] = useState(address.id);

  // 더미 결제 데이터
  const dummyPaymentData: PaymentData = {
    items: [
      {
        id: 1,
        quantity: 2,
        product: {
          id: 101,
          name: '예시 상품 A',
          brand: '브랜드 A',
          price: 12000,
          original_price: 15000,
          image: 'https://via.placeholder.com/120',
          option: { size: 'M', color: '빨강' },
        },
      },
      {
        id: 2,
        quantity: 1,
        product: {
          id: 102,
          name: '예시 상품 B',
          brand: '브랜드 B',
          price: 8000,
          image: 'https://via.placeholder.com/120',
          option: { size: 'L' },
        },
      },
    ],
  };

  // 데이터 로딩
  useEffect(() => {
    setLoading(true);
    setTimeout(() => {
      setPaymentData(dummyPaymentData);
      setLoading(false);
    }, 500);
  }, []);

  // 총액 계산
  const calculateTotals = () => {
    const items = paymentData?.items ?? [];
    const productTotal = items.reduce(
      (sum, item) => sum + item.product.price * item.quantity,
      0
    );
    const shippingTotal = items.length > 0 ? 2500 : 0;
    return { productTotal, shippingTotal, finalTotal: productTotal + shippingTotal };
  };

  const totals = calculateTotals();

  // 배송지 선택 모달
  const AddressModal = ({
    currentAddressId,
    onClose,
    onSave,
  }: {
    currentAddressId: number;
    onClose: () => void;
    onSave: (addressId: number) => void;
  }) => {
    const [selectedId, setSelectedId] = useState(currentAddressId);

    return (
      <div className={styles.modalOverlay}>
        <div className={styles.modalContent}>
          <h2>배송지 선택</h2>
          <div className={styles.modalField}>
            {savedAddresses.map(addr => (
              <label
                key={addr.id}
                className={`${styles.addressBoxOption} ${
                  selectedId === addr.id ? styles.selectedBox : ''
                }`}
              >
                <input
                  type="radio"
                  name="address"
                  value={addr.id}
                  checked={selectedId === addr.id}
                  onChange={() => setSelectedId(addr.id)}
                />
                <div className={styles.addressDetails}>
                  <p>{addr.name}</p>
                  <p>{addr.address}</p>
                  <p>{addr.phone}</p>
                </div>
              </label>
            ))}
          </div>
          <div className={styles.modalButtons}>
            <button className={styles.cancelButton} onClick={onClose}>
              취소
            </button>
            <button
              className={styles.saveButton}
              onClick={() => {
                onSave(selectedId);
                onClose();
              }}
            >
              저장
            </button>
          </div>
        </div>
      </div>
    );
  };

  // 로딩 화면
  if (loading) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>결제 정보를 불러오는 중...</div>
      </div>
    );
  }

  // 장바구니 비었을 때
  if (!paymentData || paymentData.items.length === 0) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.emptyCart}>
          <div className={styles.emptyIcon}>🛒</div>
          <h2>결제할 상품이 없습니다</h2>
          <p>장바구니에서 상품을 담아주세요!</p>
          <button
            className={styles.continueButton}
            onClick={() => console.log('쇼핑 계속하기')}
          >
            쇼핑 계속하기
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
        <h1 className={styles.title}>결제하기</h1>

        {/* 배송 정보 */}
        <section className={styles.section}>
          <h2>배송지 정보</h2>
          <div className={styles.addressBox}>
            <div className={styles.addressInfo}>
              <p>{address.name}</p>
              <p>{address.address}</p>
              <p>{address.phone}</p>
            </div>
            <button
              className={styles.changeAddressButton}
              onClick={() => {
                setSelectedModalAddressId(address.id);
                setIsModalOpen(true);
              }}
            >
              배송지 변경
            </button>
          </div>
        </section>

        {/* 주문 상품 */}
        <section className={styles.section}>
          <h2>주문 상품</h2>
          <div className={styles.itemsList}>
            {paymentData.items.map(item => (
              <div key={item.id} className={styles.cartItem}>
                <img src={item.product.image} alt={item.product.name} />
                <div className={styles.itemInfo}>
                  <p className={styles.itemBrand}>{item.product.brand}</p>
                  <h3 className={styles.itemName}>{item.product.name}</h3>
                  <p className={styles.itemOption}>
                    {item.product.option.size && `사이즈: ${item.product.option.size}`}
                    {item.product.option.color && ` / 색상: ${item.product.option.color}`}
                    {item.product.option.condition && ` / 상태: ${item.product.option.condition}`}
                  </p>
                  <p className={styles.itemQuantity}>수량: {item.quantity}</p>
                  <p className={styles.itemPrice}>
                    {(item.product.price * item.quantity).toLocaleString()}원
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 결제 수단 */}
        <section className={styles.section}>
          <h2>결제 수단</h2>
          <div className={styles.paymentMethods}>
            <label>
              <input
                type="radio"
                value="card"
                checked={selectedPaymentMethod === 'card'}
                onChange={e => setSelectedPaymentMethod(e.target.value)}
              />
              신용카드
            </label>
            <label>
              <input
                type="radio"
                value="kakao"
                checked={selectedPaymentMethod === 'kakao'}
                onChange={e => setSelectedPaymentMethod(e.target.value)}
              />
              카카오페이
            </label>
            <label>
              <input
                type="radio"
                value="bank"
                checked={selectedPaymentMethod === 'bank'}
                onChange={e => setSelectedPaymentMethod(e.target.value)}
              />
              계좌이체
            </label>
          </div>
        </section>

        {/* 결제 요약 */}
        <section className={styles.section}>
          <h2>결제 요약</h2>
          <div className={styles.priceRows}>
            <div className={styles.priceRow}>
              <span>상품금액</span>
              <span>{totals.productTotal.toLocaleString()}원</span>
            </div>
            <div className={styles.priceRow}>
              <span>배송비</span>
              <span>{totals.shippingTotal === 0 ? '무료' : `+${totals.shippingTotal.toLocaleString()}원`}</span>
            </div>
          </div>
          <div className={styles.totalPrice}>
            <span>최종 결제 금액</span>
            <span className={styles.finalAmount}>{totals.finalTotal.toLocaleString()}원</span>
          </div>
        </section>

        <button
          className={styles.payButton}
          onClick={() => console.log('결제 완료', selectedPaymentMethod)}
        >
          결제하기
        </button>

        {/* 배송지 선택 모달 */}
        {isModalOpen && (
          <AddressModal
            currentAddressId={selectedModalAddressId}
            onClose={() => setIsModalOpen(false)}
            onSave={(id) => {
              const newAddr = savedAddresses.find(addr => addr.id === id);
              if (newAddr) setAddress(newAddr);
            }}
          />
        )}
      </div>
    </div>
  );
}
