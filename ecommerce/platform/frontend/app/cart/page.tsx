'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import styles from './cart.module.css';

// ============================================
// Types
// ============================================

enum ProductType {
  NEW = 'new',
  USED = 'used',
}

interface ProductOptionInfo {
  size?: string | null;
  color?: string | null;
  condition?: string | null;
}

interface ProductInfo {
  id: number;
  name: string;
  brand: string;
  price: number | string;  // string도 허용
  original_price?: number | string | null;  // string도 허용
  stock: number | string;  // string도 허용
  shipping_fee: number | string;  // string도 허용
  shipping_text: string;
  is_used: boolean;
  image: string;
  option: ProductOptionInfo;
}

interface CartItem {
  id: number;
  cart_id: number;
  quantity: number;
  product_option_type: ProductType;
  product_option_id: number;
  created_at: string;
  updated_at: string;
  product: ProductInfo;
}

interface CartDetail {
  id: number;
  user_id: number;
  items: CartItem[];
  created_at: string;
  updated_at: string;
}

interface CartSummary {
  total_items: number;
  total_quantity: number;
  total_price: number | string;  // string도 허용
  total_shipping_fee: number | string;  // string도 허용
  final_total: number | string;  // string도 허용
}

interface CartDetailWithSummary {
  cart: CartDetail;
  summary: CartSummary;
}

// ============================================
// API Configuration
// ============================================

const API_BASE_URL = 'http://localhost:8000';

// ============================================
// API Error Handling
// ============================================

class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    message?: string
  ) {
    super(message || statusText);
    this.name = 'ApiError';
  }
}

async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        response.statusText,
        errorData.detail || errorData.message
      );
    }

    if (response.status === 204) {
      return {} as T;
    }

    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new Error(`네트워크 오류: ${error instanceof Error ? error.message : '알 수 없는 오류'}`);
  }
}

// ============================================
// Utility Functions
// ============================================

/**
 * 문자열 또는 숫자를 숫자로 변환
 */
function toNumber(value: string | number | null | undefined): number {
  if (value === null || value === undefined) {
    return 0;
  }
  if (typeof value === 'number') {
    return value;
  }
  // 문자열인 경우 숫자로 변환
  const parsed = parseFloat(value);
  return isNaN(parsed) ? 0 : parsed;
}

/**
 * API 응답 데이터의 가격을 숫자로 변환
 */
function normalizeCartData(data: CartDetailWithSummary): CartDetailWithSummary {
  return {
    ...data,
    cart: {
      ...data.cart,
      items: data.cart.items.map(item => ({
        ...item,
        product: {
          ...item.product,
          price: toNumber(item.product.price),
          original_price: item.product.original_price 
            ? toNumber(item.product.original_price) 
            : null,
          shipping_fee: toNumber(item.product.shipping_fee),
          stock: toNumber(item.product.stock),
        }
      }))
    },
    summary: {
      ...data.summary,
      total_price: toNumber(data.summary.total_price),
      total_shipping_fee: toNumber(data.summary.total_shipping_fee),
      final_total: toNumber(data.summary.final_total),
    }
  };
}

// ============================================
// Main Component
// ============================================

const CURRENT_USER_ID = 1; // 임시 사용자 ID

export default function CartPage() {
  const router = useRouter();
  const [cartData, setCartData] = useState<CartDetailWithSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedItems, setSelectedItems] = useState<number[]>([]);
  const [allChecked, setAllChecked] = useState(false);
  const [error, setError] = useState('');
  const [actionLoading, setActionLoading] = useState(false);

  // 장바구니 데이터 로드
  const loadCartData = async () => {
    setLoading(true);
    setError('');
    
    try {
      const data = await fetchApi<CartDetailWithSummary>(`/carts/${CURRENT_USER_ID}`);
      // API에서 받은 데이터의 가격을 숫자로 변환
      const normalizedData = normalizeCartData(data);
      setCartData(normalizedData);
      setSelectedItems(normalizedData.cart.items.map(item => item.id));
    } catch (err) {
      console.error('장바구니 로드 실패:', err);
      if (err instanceof ApiError) {
        setError(`장바구니를 불러올 수 없습니다: ${err.message}`);
      } else {
        setError('장바구니를 불러오는 중 오류가 발생했습니다.');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCartData();
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

  const updateQuantity = async (itemId: number, delta: number) => {
    if (actionLoading) return;
    
    const item = cartData?.cart.items.find(i => i.id === itemId);
    if (!item) return;

    const newQuantity = item.quantity + delta;
    const stock = toNumber(item.product.stock);
    
    if (newQuantity < 1 || newQuantity > stock) {
      return;
    }

    setActionLoading(true);
    setError('');

    try {
      await fetchApi<CartItem>(`/carts/${CURRENT_USER_ID}/items/${itemId}`, {
        method: 'PATCH',
        body: JSON.stringify({ quantity: newQuantity }),
      });
      
      await loadCartData();
    } catch (err) {
      console.error('수량 업데이트 실패:', err);
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('수량 업데이트에 실패했습니다.');
      }
    } finally {
      setActionLoading(false);
    }
  };

  const deleteSelectedItems = async () => {
    if (selectedItems.length === 0) {
      setError('삭제할 상품을 선택해주세요.');
      return;
    }

    if (!confirm(`선택한 ${selectedItems.length}개 상품을 삭제하시겠습니까?`)) {
      return;
    }

    setActionLoading(true);
    setError('');

    try {
      await fetchApi<{ message: string; deleted_count: number }>(
        `/carts/${CURRENT_USER_ID}/items`,
        {
          method: 'DELETE',
          body: JSON.stringify({ item_ids: selectedItems }),
        }
      );
      
      setSelectedItems([]);
      await loadCartData();
    } catch (err) {
      console.error('삭제 실패:', err);
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('상품 삭제에 실패했습니다.');
      }
    } finally {
      setActionLoading(false);
    }
  };

  const deleteItem = async (itemId: number) => {
    if (!confirm('이 상품을 삭제하시겠습니까?')) {
      return;
    }

    setActionLoading(true);
    setError('');

    try {
      await fetchApi<void>(`/carts/${CURRENT_USER_ID}/items/${itemId}`, {
        method: 'DELETE',
      });
      
      setSelectedItems(prev => prev.filter(id => id !== itemId));
      await loadCartData();
    } catch (err) {
      console.error('삭제 실패:', err);
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('상품 삭제에 실패했습니다.');
      }
    } finally {
      setActionLoading(false);
    }
  };

  const calculateSelectedTotals = () => {
    if (!cartData?.cart?.items) {
      return { productTotal: 0, shippingTotal: 0, finalTotal: 0 };
    }

    const selectedCartItems = cartData.cart.items.filter(item =>
      selectedItems.includes(item.id)
    );

    const productTotal = selectedCartItems.reduce(
      (sum, item) => sum + toNumber(item.product.price) * item.quantity,
      0
    );

    const shippingTotal = selectedCartItems.reduce(
      (sum, item) => sum + toNumber(item.product.shipping_fee),
      0
    );

    return {
      productTotal,
      shippingTotal,
      finalTotal: productTotal + shippingTotal,
    };
  };

  const handleOrder = () => {
    if (selectedItems.length === 0) {
      setError('주문할 상품을 선택해주세요.');
      return;
    }

    const selectedCartItems = cartData?.cart.items.filter(item =>
      selectedItems.includes(item.id)
    );

    console.log('주문 진행:', {
      selectedItems,
      items: selectedCartItems,
      totals: calculateSelectedTotals(),
    });

    alert('주문 기능은 아직 구현되지 않았습니다.');
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

  if (error && !cartData) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>
          <div className={styles.errorMessage}>
            <p>{error}</p>
            <button className={styles.retryButton} onClick={loadCartData}>
              다시 시도
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!cartData?.cart?.items || cartData.cart.items.length === 0) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.container}>
          <div className={styles.emptyCart}>
            <div className={styles.emptyIcon}>🛒</div>
            <h2>장바구니에 담은 상품이 없습니다</h2>
            <p>원하는 상품을 장바구니에 담아보세요!</p>
            <button
              className={styles.continueButton}
              onClick={() => router.push('/')}
            >
              쇼핑 계속하기
            </button>
          </div>
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
          <div className={styles.itemsSection}>
            <div className={styles.selectBar}>
              <label className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={toggleAllSelection}
                  disabled={actionLoading}
                />
                <span>
                  전체선택 ({selectedItems.length}/{cartData.cart.items.length})
                </span>
              </label>
              <button
                className={styles.deleteButton}
                onClick={deleteSelectedItems}
                disabled={actionLoading || selectedItems.length === 0}
              >
                선택삭제
              </button>
            </div>

            <div className={styles.itemsList}>
              {cartData.cart.items.map(item => (
                <div key={item.id} className={styles.cartItem}>
                  <div className={styles.itemCheck}>
                    <input
                      type="checkbox"
                      checked={selectedItems.includes(item.id)}
                      onChange={() => toggleSelection(item.id)}
                      disabled={actionLoading}
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
                        <button
                          onClick={() => updateQuantity(item.id, -1)}
                          disabled={item.quantity <= 1 || actionLoading}
                        >
                          -
                        </button>
                        <span>{item.quantity}</span>
                        <button
                          onClick={() => updateQuantity(item.id, 1)}
                          disabled={item.quantity >= toNumber(item.product.stock) || actionLoading}
                        >
                          +
                        </button>
                      </div>

                      <div className={styles.itemPrice}>
                        {item.product.original_price && (
                          <p className={styles.originalPrice}>
                            {toNumber(item.product.original_price).toLocaleString()}원
                          </p>
                        )}
                        <p className={styles.currentPrice}>
                          {(toNumber(item.product.price) * item.quantity).toLocaleString()}원
                        </p>
                      </div>
                    </div>

                    <p className={styles.shippingInfo}>{item.product.shipping_text}</p>
                    {toNumber(item.product.stock) <= 3 && (
                      <p className={styles.stockWarning}>
                        ⚠️ 남은 수량: {toNumber(item.product.stock)}개
                      </p>
                    )}
                  </div>

                  <button
                    className={styles.removeButton}
                    onClick={() => deleteItem(item.id)}
                    disabled={actionLoading}
                    aria-label="상품 삭제"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>

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
                  <span>
                    {totals.shippingTotal === 0
                      ? '무료'
                      : `+${totals.shippingTotal.toLocaleString()}원`}
                  </span>
                </div>
              </div>

              <div className={styles.totalPrice}>
                <span>최종 결제 금액</span>
                <span className={styles.finalAmount}>
                  {totals.finalTotal.toLocaleString()}원
                </span>
              </div>

              {totals.productTotal < 50000 && totals.productTotal > 0 && (
                <div className={styles.freeShippingInfo}>
                  <strong>{(50000 - totals.productTotal).toLocaleString()}원</strong> 더
                  담으면 무료배송!
                </div>
              )}

              <button
                className={styles.orderButton}
                onClick={handleOrder}
                disabled={selectedItems.length === 0 || actionLoading}
              >
                {selectedItems.length > 0
                  ? `${selectedItems.length}개 상품 주문하기`
                  : '상품을 선택해주세요'}
              </button>

              <button
                className={styles.continueShoppingButton}
                onClick={() => router.push('/')}
                disabled={actionLoading}
              >
                쇼핑 계속하기
              </button>

              <div className={styles.notice}>
                <p>• 장바구니에 담긴 상품은 30일간 보관됩니다.</p>
                <p>• 주문 완료 후 취소/변경은 마이페이지에서 가능합니다.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
