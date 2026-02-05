'use client';

import { useState, useEffect } from 'react';
import styles from './cart.module.css';

interface Product {
  id: number;
  name: string;
  brand: string;
  price: number;
  original_price?: number;
  stock: number;
  shipping_fee: number;
  shipping_text: string;
  is_used?: boolean;
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

interface CartData {
  cart: {
    items: CartItem[];
  };
}

export default function CartPage() {
  const [cartData, setCartData] = useState<CartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedItems, setSelectedItems] = useState<number[]>([]);
  const [allChecked, setAllChecked] = useState(false);
  const [error, setError] = useState('');

  // 더미 데이터
  const dummyCartData: CartData = {
    cart: {
      items: [
        {
          id: 1,
          quantity: 1,
          product: {
            id: 101,
            name: '예시 상품 A',
            brand: '브랜드 A',
            price: 12000,
            original_price: 15000,
            stock: 5,
            shipping_fee: 2500,
            shipping_text: '택배 배송',
            is_used: true,
            image: 'https://via.placeholder.com/120',
            option: { size: 'M', color: '빨강', condition: '좋음' },
          },
        },
        {
          id: 2,
          quantity: 2,
          product: {
            id: 102,
            name: '예시 상품 B',
            brand: '브랜드 B',
            price: 8000,
            stock: 2,
            shipping_fee: 0,
            shipping_text: '무료배송',
            image: 'https://via.placeholder.com/120',
            option: { size: 'L' },
          },
        },
      ],
    },
  };

  useEffect(() => {
    // API 대신 더미 데이터 로딩
    setLoading(true);
    setError('');
    setTimeout(() => {
      setCartData(dummyCartData);
      setSelectedItems(dummyCartData.cart.items.map(item => item.id));
      setLoading(false);
    }, 500);
  }, []);

  useEffect(() => {
    if (cartData?.cart?.items) {
      setAllChecked(
        cartData.cart.items.length > 0 &&
          selectedItems.length === cartData.cart.items.length
      );
    }
  }, [selectedItems, cartData]);

  const toggleSelection = (itemId: number) => {
    setSelectedItems(prev =>
      prev.includes(itemId)
        ? prev.filter(id => id !== itemId)
        : [...prev, itemId]
    );
    setError('');
  };

  const toggleAllSelection = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    if (checked) {
      setSelectedItems(cartData!.cart.items.map(item => item.id));
    } else {
      setSelectedItems([]);
    }
    setError('');
  };

  const updateQuantity = (itemId: number, delta: number) => {
    setCartData(prev => {
      if (!prev) return prev;
      const newItems = prev.cart.items.map(item =>
        item.id === itemId
          ? {
              ...item,
              quantity: Math.min(
                Math.max(item.quantity + delta, 1),
                item.product.stock
              ),
            }
          : item
      );
      return { cart: { items: newItems } };
    });
  };

  const calculateSelectedTotals = () => {
    if (!cartData?.cart?.items) return { productTotal: 0, shippingTotal: 0, finalTotal: 0 };

    const selectedCartItems = cartData.cart.items.filter(item =>
      selectedItems.includes(item.id)
    );

    const productTotal = selectedCartItems.reduce(
      (sum, item) => sum + item.product.price * item.quantity,
      0
    );

    const shippingTotal = selectedCartItems.reduce(
      (sum, item) => sum + item.product.shipping_fee,
      0
    );

    return { productTotal, shippingTotal, finalTotal: productTotal + shippingTotal };
  };

  const totals = calculateSelectedTotals();

  if (loading) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>
          <div className={styles.loading}>장바구니를 불러오는 중...</div>
        </div>
      </div>
    );
  }

  if (!cartData?.cart?.items || cartData.cart.items.length === 0) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.emptyCart}>
          <div className={styles.emptyIcon}>🛒</div>
          <h2>장바구니에 담은 상품이 없습니다</h2>
          <p>원하는 상품을 장바구니에 담아보세요!</p>
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
        <h1 className={styles.title}>장바구니</h1>

        {error && <p className={styles.error}>{error}</p>}

        <div className={styles.content}>
          {/* 상품 목록 */}
          <div className={styles.itemsSection}>
            <div className={styles.selectBar}>
              <label className={styles.checkboxLabel}>
                <input type="checkbox" checked={allChecked} onChange={toggleAllSelection} />
                <span>전체선택 ({selectedItems.length}/{cartData.cart.items.length})</span>
              </label>
            </div>

            <div className={styles.itemsList}>
              {cartData.cart.items.map(item => (
                <div key={item.id} className={styles.cartItem}>
                  <div className={styles.itemCheck}>
                    <input
                      type="checkbox"
                      checked={selectedItems.includes(item.id)}
                      onChange={() => toggleSelection(item.id)}
                    />
                  </div>

                  <div className={styles.itemImage}>
                    <img src={item.product.image} alt={item.product.name} />
                  </div>

                  <div className={styles.itemInfo}>
                    {item.product.is_used && (
                      <span className={styles.usedBadge}>중고상품</span>
                    )}
                    <p className={styles.itemBrand}>{item.product.brand}</p>
                    <h3 className={styles.itemName}>{item.product.name}</h3>
                    <p className={styles.itemOption}>
                      {item.product.option.size && `사이즈: ${item.product.option.size}`}
                      {item.product.option.color && ` / 색상: ${item.product.option.color}`}
                      {item.product.option.condition && ` / 상태: ${item.product.option.condition}`}
                    </p>

                    <div className={styles.itemBottom}>
                      <div className={styles.quantityControl}>
                        <button onClick={() => updateQuantity(item.id, -1)} disabled={item.quantity <= 1}>-</button>
                        <span>{item.quantity}</span>
                        <button onClick={() => updateQuantity(item.id, 1)} disabled={item.quantity >= item.product.stock}>+</button>
                      </div>

                      <div className={styles.itemPrice}>
                        {item.product.original_price && (
                          <p className={styles.originalPrice}>{item.product.original_price.toLocaleString()}원</p>
                        )}
                        <p className={styles.currentPrice}>{(item.product.price * item.quantity).toLocaleString()}원</p>
                      </div>
                    </div>

                    <p className={styles.shippingInfo}>{item.product.shipping_text}</p>
                    {item.product.stock <= 3 && (
                      <p className={styles.stockWarning}>⚠️ 남은 수량: {item.product.stock}개</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 주문 요약 */}
          <div className={styles.summarySection}>
            <div className={styles.summary}>
              <h2>주문 예상 금액</h2>
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

              {totals.productTotal < 50000 && totals.productTotal > 0 && (
                <div className={styles.freeShippingInfo}>
                  🎁 <strong>{(50000 - totals.productTotal).toLocaleString()}원</strong> 더 담으면 무료배송!
                </div>
              )}

              <button
                className={styles.orderButton}
                onClick={() => console.log('주문하기', selectedItems)}
                disabled={selectedItems.length === 0}
              >
                {selectedItems.length > 0 ? `${selectedItems.length}개 상품 주문하기` : '상품을 선택해주세요'}
              </button>

              <button
                className={styles.continueShoppingButton}
                onClick={() => console.log('쇼핑 계속하기')}
              >
                쇼핑 계속하기
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
