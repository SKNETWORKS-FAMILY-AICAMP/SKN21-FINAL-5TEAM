'use client';

import Image from 'next/image';
import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../authcontext';
import styles from './productlist.module.css';

const API_BASE = process.env.NEXT_PUBLIC_API_URL;

export type UiProduct = {
  id: number;
  name: string;
  price: number;
  category?: string;
  color?: string;
  season?: string;
  image_url?: string;
};

type ProductOption = {
  id: number;
  product_id: number;
  size_name: string | null;
  color: string | null;
  quantity: number;
  is_active: boolean;
};

type ProductListUIProps = {
  products?: UiProduct[];
  message?: string;
};

export default function ProductListUI({ products = [], message }: ProductListUIProps) {
  const router = useRouter();
  const { isLoggedIn } = useAuth();
  
  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<ProductOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  
  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] =
    useState<Record<number, number | null>>({});

  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] =
    useState<Record<number, string>>({});

  const requireLogin = (callback: () => void) => {
    if (isLoggedIn === null) return;
    if (!isLoggedIn) {
      alert('로그인이 필요한 기능입니다.');
      // 챗봇 내부에서 로그인 창으로 보내면 불편할 수 있어 경고만 띄우거나 이동
      // router.push('/auth/login'); 
      return;
    }
    callback();
  };

  const openSizeModal = (productId: number) => {
    requireLogin(async () => {
      setSizeModalOpenFor(productId);
      setOptions([]);
      setOptionsLoading(true);

      try {
        const res = await fetch(`${API_BASE}/products/new/${productId}/options`, {
          credentials: 'include',
        });

        if (!res.ok) throw new Error();

        const data: ProductOption[] = await res.json();
        const filtered = data.filter((o) => o.is_active && o.quantity > 0);
        setOptions(filtered);
      } catch {
        alert('사이즈 정보를 불러오지 못했습니다.');
        setSizeModalOpenFor(null);
      } finally {
        setOptionsLoading(false);
      }
    });
  };

  const closeSizeModal = () => {
    setSizeModalOpenFor(null);
    setOptions([]);
  };

  const uniqueSizes = useMemo(() => {
    const map = new Map<string, ProductOption>();
    options.forEach((o) => {
      const key = o.size_name ?? 'FREE';
      if (!map.has(key)) map.set(key, o);
    });
    return Array.from(map.entries()).map(([size, opt]) => ({ size, opt }));
  }, [options]);

  const selectOption = (productId: number, option: ProductOption) => {
    setSelectedOptionIdByProduct((prev) => ({
      ...prev,
      [productId]: option.id,
    }));
    setSelectedSizeLabelByProduct((prev) => ({
      ...prev,
      [productId]: option.size_name || '선택됨',
    }));
    closeSizeModal();
  };

  const addToCart = async (productId: number, goPayment: boolean) => {
    requireLogin(async () => {
      const optionId = selectedOptionIdByProduct[productId];

      if (!optionId) {
        openSizeModal(productId);
        return;
      }

      try {
        // me 정보 가져와서 user.id 확보
        const userRes = await fetch(`${API_BASE}/users/me`, { credentials: 'include' });
        const userData = await userRes.json();
        const userId = userData.id;

        const res = await fetch(`${API_BASE}/carts/${userId}/items`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            product_option_type: 'new',
            product_option_id: optionId,
            quantity: 1,
          }),
        });

        if (!res.ok) {
          alert('장바구니 추가 실패');
          return;
        }

        if (goPayment) {
          router.push('/payment');
        } else {
          alert('장바구니에 담았습니다.');
        }
      } catch {
        alert('요청 실패');
      }
    });
  };

  return (
    <div className={styles.container}>
      {message && <div className={styles.message}>{message}</div>}
      <div className={styles.productList}>
        {products.map((product) => {
          const selectedLabel = selectedSizeLabelByProduct[product.id];
          // Mocking Image path for missing images inside chatbot 
          // (Can use fallback UI if image fails to load, or just the same logic as page.tsx)
          const imgUrl = product.image_url || `/products/${product.id}.jpg`;
          
          return (
            <div key={product.id} className={styles.productCard}>
              <div 
                className={styles.productImageWrap} 
              >
                 <Image
                    src={imgUrl}
                    alt={product.name}
                    fill
                    style={{ objectFit: 'cover' }}
                    unoptimized
                    onError={(e) => {
                        // Fallback image handling
                        (e.target as HTMLImageElement).src = '/logo.png'; 
                    }}
                  />
              </div>

              <div className={styles.productInfo}>
                <div>
                  <h4 
                    className={styles.productName}
                  >
                    {product.name}
                  </h4>
                  <p className={styles.productMeta}>
                    {product.category && `${product.category} | `}
                    {product.color && `${product.color} `}
                  </p>
                  <p className={styles.productPrice}>
                    {Math.round(product.price ?? 0).toLocaleString()}원
                  </p>
                </div>
                
                <div className={styles.actionRow}>
                  <button
                    className={styles.btn}
                    onClick={() => openSizeModal(product.id)}
                  >
                    {selectedLabel || '사이즈 선택'}
                  </button>
                  <button
                    className={styles.btn}
                    onClick={() => addToCart(product.id, false)}
                  >
                    장바구니
                  </button>
                  <button
                    className={`${styles.btn} ${styles.primary}`}
                    onClick={() => addToCart(product.id, true)}
                  >
                    바로 구매
                  </button>
                </div>
              </div>

              {sizeModalOpenFor === product.id && (
                <div className={styles.modalOverlay} onClick={closeSizeModal}>
                  <button className={styles.closeModalBtn} onClick={closeSizeModal}>✕</button>
                  <div onClick={(e) => e.stopPropagation()} style={{ width: '100%', maxWidth: '240px' }}>
                    <h4 className={styles.modalTitle}>사이즈 선택</h4>
                    {optionsLoading ? (
                      <p style={{ fontSize: '12px' }}>불러오는 중...</p>
                    ) : uniqueSizes.length === 0 ? (
                      <p style={{ fontSize: '12px', color: '#666' }}>선택 가능한 사이즈가 없습니다.</p>
                    ) : (
                      <div className={styles.sizeGrid}>
                        {uniqueSizes.map(({ size, opt }) => (
                          <button
                            key={size}
                            className={styles.sizeBtn}
                            onClick={() => selectOption(product.id, opt)}
                          >
                            {size}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
