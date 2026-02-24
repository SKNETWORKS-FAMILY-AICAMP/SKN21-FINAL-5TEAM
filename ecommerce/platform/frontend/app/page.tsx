'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import styles from './page.module.css';

const API_BASE = process.env.NEXT_PUBLIC_API_URL;

type Product = {
  id: number;
  name: string;
  price: number;
};

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

  const [products, setProducts] = useState<Product[]>([]);

  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<ProductOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] =
    useState<Record<number, number | null>>({});

  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] =
    useState<Record<number, string>>({});

  const [imageMap, setImageMap] = useState<Record<number, string>>({});

  // ===========================
  // 상품 DB에서 불러오기
  // ===========================
  useEffect(() => {
    const fetchProducts = async () => {
      try {
        const res = await fetch(`${API_BASE}/products/new?limit=10`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        setProducts(data);
      } catch (e) {
        console.error('상품 로딩 실패', e);
      }
    };

    fetchProducts();
  }, []);

  useEffect(() => {
    const fetchImages = async () => {
      const newMap: Record<number, string> = {};
      await Promise.all(
        products.map(async (p) => {
          try {
            const res = await fetch(`${API_BASE}/products/images/new/${p.id}`);
            if (!res.ok) return;
            const images = await res.json();
            const primary = images.find((img: any) => img.is_primary);
            if (primary || images[0]) {
              newMap[p.id] = (primary || images[0]).image_url;
            }
          } catch {}
        })
      );
      setImageMap(newMap);
    };
    if (products.length > 0) fetchImages();
  }, [products]);

  // ===========================
  // 로그인 & 유저 정보
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
        if (!data.authenticated) {
          setIsLoggedIn(false);
          return;
        }
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

        const cartItem = await res.json();

        // User History에 장바구니 추가 기록
        try {
          await fetch(`${API_BASE}/user-history/users/${user!.id}/track/cart-action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              action_type: 'cart_add',
              cart_item_id: cartItem.id,
              product_option_type: 'new',
              product_option_id: optionId,
              quantity: 1,
            }),
          });
        } catch (err) {
          console.error('Failed to track cart action:', err);
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
          {products.map((product) => {
            const selectedLabel =
              selectedSizeLabelByProduct[product.id];

            return (
              <li key={product.id} className={styles.productCard}>
                <div
                  className={styles.cardBody}
                  onClick={() =>
                    requireLogin(() =>
                      router.push(`/products/${product.id}`)
                    )
                  }
                >
                  <div className={styles.productImage}>
                    {imageMap[product.id] && (
                      <img
                        src={imageMap[product.id]}
                        alt={product.name}
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      />
                    )}
                  </div>

                  <div className={styles.productInfo}>
                    <p>상품명</p>
                    <p>{product.name}</p>
                    <p>
                      가격 {product.price?.toLocaleString()}원
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
    </main>
  );
}