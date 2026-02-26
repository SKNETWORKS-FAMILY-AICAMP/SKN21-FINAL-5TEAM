'use client';

import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import styles from './used.module.css';

const API_BASE = 'http://localhost:8000';

type Condition = {
  id: number;
  condition_name: string;
};

type UsedProduct = {
  id: number;
  name: string;
  price: number;
  status: 'approved' | 'sold';
  condition: Condition;
};

type UsedOption = {
  id: number;
  used_product_id: number;
  size_name: string | null;
  quantity: number;
  is_active: boolean;
};

type User = {
  id: number;
  email: string;
};

export default function UsedPage() {
  const router = useRouter();

  const [products, setProducts] = useState<UsedProduct[]>([]);
  const [user, setUser] = useState<User | null>(null);

  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<UsedOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] =
    useState<Record<number, number | null>>({});

  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] =
    useState<Record<number, string>>({});

  const [warningModalOpen, setWarningModalOpen] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/users/me`, {
      credentials: 'include',
    })
      .then(async (res) => {
        if (!res.ok) return;
        const data = await res.json();
        if (data.authenticated) {
          setUser(data);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const fetchUsed = async () => {
      try {
        const res = await fetch(`${API_BASE}/products/used`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        setProducts(data);
      } catch {
        alert('중고상품 로딩 실패');
      }
    };

    fetchUsed();
  }, []);

  const openSizeModal = async (productId: number) => {
    setSizeModalOpenFor(productId);
    setOptions([]);
    setOptionsLoading(true);

    try {
      const res = await fetch(
        `${API_BASE}/products/used/${productId}/options`
      );
      if (!res.ok) throw new Error();

      const data: UsedOption[] = await res.json();
      const filtered = data.filter(
        (o) => o.is_active && o.quantity > 0
      );

      setOptions(filtered);
    } catch {
      alert('사이즈 정보를 불러오지 못했습니다.');
      setSizeModalOpenFor(null);
    } finally {
      setOptionsLoading(false);
    }
  };

  const closeSizeModal = () => {
    setSizeModalOpenFor(null);
    setOptions([]);
  };

  const uniqueSizes = useMemo(() => {
    const map = new Map<string, UsedOption>();
    options.forEach((o) => {
      const key = o.size_name ?? 'FREE';
      if (!map.has(key)) map.set(key, o);
    });
    return Array.from(map.entries()).map(([size, opt]) => ({ size, opt }));
  }, [options]);

  const selectOption = (productId: number, option: UsedOption) => {
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
    if (!user) {
      router.push('/auth/login');
      return;
    }

    const optionId = selectedOptionIdByProduct[productId];

    if (!optionId) {
      setWarningModalOpen(true);
      return;
    }

    try {
      const res = await fetch(
        `${API_BASE}/carts/${user.id}/items`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            product_option_type: 'used',
            product_option_id: optionId,
            quantity: 1,
          }),
        }
      );

      if (!res.ok) {
        const error = await res.json();
        alert(error.detail || '장바구니 추가 실패');
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
  };

  return (
    <main className={styles.main}>
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <h1>중고 상품</h1>
        </header>

        <ul className={styles.productGrid}>
          {products.map((product) => {
            const selectedLabel =
              selectedSizeLabelByProduct[product.id];

            return (
              <li key={product.id} className={styles.productCard}>
                <div className={styles.cardBody}>
                  <div className={styles.productImage}>
                    <Image
                      src={`/products/${product.id}.jpg`}
                      alt={product.name}
                      fill
                      style={{ objectFit: 'cover' }}
                    />

                    {/* 등급 배지 */}
                    <div className={styles.conditionBadge}>
                      {product.condition?.condition_name}
                    </div>
                  </div>

                  <div className={styles.productInfo}>
                    <p>{product.name}</p>
                    <p>
                      가격 {Math.round(product.price ?? 0).toLocaleString()}원
                    </p>
                  </div>
                </div>

                <div className={styles.hoverOverlay}>
                  <button
                    className={styles.hoverButton}
                    onClick={() => openSizeModal(product.id)}
                  >
                    {selectedLabel || '사이즈 선택'}
                  </button>

                  <button
                    className={styles.hoverButton}
                    onClick={() => addToCart(product.id, false)}
                  >
                    장바구니
                  </button>

                  <button
                    className={`${styles.hoverButton} ${styles.primary}`}
                    onClick={() => addToCart(product.id, true)}
                  >
                    바로 구매
                  </button>
                </div>

                {sizeModalOpenFor === product.id && (
                  <div className={styles.modalBackdrop} onClick={closeSizeModal}>
                    <div
                      className={styles.modal}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <h4>사이즈 선택</h4>

                      {optionsLoading ? (
                        <p>불러오는 중...</p>
                      ) : uniqueSizes.length === 0 ? (
                        <p>선택 가능한 사이즈가 없습니다.</p>
                      ) : (
                        <div className={styles.sizeGrid}>
                          {uniqueSizes.map(({ size, opt }) => (
                            <button
                              key={size}
                              onClick={() =>
                                selectOption(product.id, opt)
                              }
                            >
                              {size}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {warningModalOpen && (
        <div
          className={styles.modalBackdrop}
          onClick={() => setWarningModalOpen(false)}
        >
          <div
            className={styles.modal}
            onClick={(e) => e.stopPropagation()}
          >
            <h4>사이즈를 선택해주세요</h4>
            <button
              onClick={() => setWarningModalOpen(false)}
            >
              확인
            </button>
          </div>
        </div>
      )}
    </main>
  );
}