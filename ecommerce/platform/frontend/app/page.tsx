'use client';

import Image from 'next/image';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import styles from './page.module.css';

const API_BASE = 'http://localhost:8000';
const PRODUCT_IDS = [1,2,3,4,5,6,7,8,9,1550];

type ProductOption = {
  id: number;
  product_id: number;
  size_name: string | null;
  color: string | null;
  quantity: number;
  is_active: boolean;
};

type User = {
  id: number;
  email: string;
};

export default function HomePage() {
  const router = useRouter();

  const [user, setUser] = useState<User | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<ProductOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] =
    useState<Record<number, number | null>>({});

  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] =
    useState<Record<number, string>>({});

  // ===========================
  // 로그인 & 유저 정보 가져오기
  // ===========================
  useEffect(() => {
    fetch(`${API_BASE}/users/me`, {
      credentials: 'include',
    })
      .then(async (res) => {
        if (!res.ok) {
          setIsLoggedIn(false);
          return;
        }
        const data = await res.json();
        setUser(data);
        setIsLoggedIn(true);
      })
      .catch(() => setIsLoggedIn(false));
  }, []);

  const requireLogin = (callback: () => void) => {
    if (isLoggedIn === null) return;
    if (!isLoggedIn) {
      router.push('/auth/login');
      return;
    }
    callback();
  };

  // ===========================
  // 옵션 불러오기
  // ===========================
  const openSizeModal = (productId: number) => {
    requireLogin(async () => {
      setSizeModalOpenFor(productId);
      setOptions([]);
      setOptionsLoading(true);

      try {
        const res = await fetch(
          `${API_BASE}/products/new/${productId}/options`,
          { credentials: 'include' }
        );

        if (!res.ok) throw new Error();

        const data: ProductOption[] = await res.json();

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

  // ===========================
  // 장바구니
  // ===========================
  const addToCart = async (productId: number, goPayment: boolean) => {
    requireLogin(async () => {
      const optionId = selectedOptionIdByProduct[productId];

      if (!optionId) {
        openSizeModal(productId);
        return;
      }

      try {
        const res = await fetch(
          `${API_BASE}/carts/${user!.id}/items`,
          {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              product_option_type: 'new',
              product_option_id: optionId,
              quantity: 1,
            }),
          }
        );

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
    <main className={styles.main}>
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <div>
            <h2>많이 찾는 스포티 스타일</h2>
            <p>스웨트셔츠</p>
          </div>

          <button
            onClick={() => requireLogin(() => router.push('/products'))}
          >
            더보기
          </button>
        </header>

        <ul className={styles.productGrid}>
          {PRODUCT_IDS.map((id) => {
            const selectedLabel = selectedSizeLabelByProduct[id];

            return (
              <li key={id} className={styles.productCard}>
                <div
                  className={styles.cardBody}
                  onClick={() =>
                    requireLogin(() => router.push(`/products/${id}`))
                  }
                >
                  <div className={styles.productImage}>
                    <Image
                      src={`/products/${id}.jpg`}
                      alt="상품"
                      fill
                      style={{ objectFit: 'cover' }}
                    />
                  </div>

                  <div className={styles.productInfo}>
                    <p>상품명</p>
                    <p>BASIC LOGO SWEATSHIRT NAVY</p>
                    <p>가격 5억</p>
                  </div>
                </div>

                <div className={styles.hoverOverlay}>
                  <button
                    className={styles.hoverButton}
                    onClick={() => openSizeModal(id)}
                  >
                    {selectedLabel || '사이즈 선택'}
                  </button>

                  <button
                    className={styles.hoverButton}
                    onClick={() => addToCart(id, false)}
                  >
                    장바구니
                  </button>

                  <button
                    className={`${styles.hoverButton} ${styles.primary}`}
                    onClick={() => addToCart(id, true)}
                  >
                    바로 구매
                  </button>
                </div>


                {sizeModalOpenFor === id && (
                  <div
                    style={{
                      position: 'fixed',
                      inset: 0,
                      background: 'rgba(0,0,0,0.4)',
                      display: 'flex',
                      justifyContent: 'center',
                      alignItems: 'center',
                      zIndex: 9999,
                    }}
                    onClick={closeSizeModal}
                  >
                    <div
                      onClick={(e) => e.stopPropagation()}
                      style={{
                        width: 400,
                        background: '#fff',
                        padding: 20,
                        borderRadius: 10,
                      }}
                    >
                      <h4>사이즈 선택</h4>

                      {optionsLoading ? (
                        <p>불러오는 중...</p>
                      ) : uniqueSizes.length === 0 ? (
                        <p>선택 가능한 사이즈가 없습니다.</p>
                      ) : (
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(4,1fr)',
                            gap: 8,
                          }}
                        >
                          {uniqueSizes.map(({ size, opt }) => (
                            <button
                              key={size}
                              onClick={() => selectOption(id, opt)}
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
    </main>
  );
}
