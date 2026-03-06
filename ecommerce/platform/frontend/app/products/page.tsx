'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Image from 'next/image';
import styles from './product.module.css';

const PRODUCTS_PER_PAGE = 10;
const PAGE_GROUP_SIZE = 10;
const API_BASE = process.env.NEXT_PUBLIC_API_URL;

type Category = {
  id: number;
  name: string;
  parent_id: number | null;
};

type Product = {
  id: number;
  name: string;
  price: number;
  category_id: number;
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

function ProductsPageContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const categoryIdParam = searchParams.get('category_id');
  const keyword = searchParams.get('keyword');

  const categoryId = categoryIdParam ? Number(categoryIdParam) : null;

  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [subCategories, setSubCategories] = useState<Category[]>([]);
  const [activeSubId, setActiveSubId] = useState<number | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const [categoryTitle, setCategoryTitle] = useState<string>('상품 목록');

  // ===========================
  // (추가) 로그인 & 유저 정보 (HomePage와 동일)
  // ===========================
  const [user, setUser] = useState<User | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  useEffect(() => {
    if (!API_BASE) return;

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
  // (추가) 호버 기능용 상태 (HomePage와 동일)
  // ===========================
  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<ProductOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] =
    useState<Record<number, number | null>>({});

  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] =
    useState<Record<number, string>>({});

  // -----------------------
  // 카테고리 로드
  // -----------------------
  useEffect(() => {
    const fetchCategories = async () => {
      const res = await fetch(`${API_BASE}/products/categories?limit=1000`);
      const data = await res.json();
      setCategories(data);
    };
    fetchCategories();
  }, []);

  // -----------------------
  // 선택된 중분류 기준 처리
  // -----------------------
  useEffect(() => {
    if (keyword) {
      setCategoryTitle(`"${keyword}" 검색 결과`);
      setSubCategories([]);
      setActiveSubId(null);
      return;
    }

    if (!categoryId || categories.length === 0) return;

    const currentCategory = categories.find(c => c.id === categoryId);
    if (!currentCategory) return;

    setCategoryTitle(currentCategory.name);

    const children = categories.filter(
      c => c.parent_id === currentCategory.id
    );

    setSubCategories(children);

    if (children.length > 0) {
      setActiveSubId(children[0].id);   // ✅ 소분류1 자동 선택
    } else {
      setActiveSubId(null);            // 소분류가 없으면 기존처럼
    }
  }, [categoryId, categories, keyword]);

  // -----------------------
  // 상품 로드
  // -----------------------
  useEffect(() => {
    const fetchProducts = async () => {
      // API_BASE 없으면 호출 자체를 막음 (env 미설정 방지)
      if (!API_BASE) return;

      let url = `${API_BASE}/products/new?limit=1000`;

      // 검색이면 카테고리 로직 전부 무시
      if (keyword) {
        url += `&keyword=${encodeURIComponent(keyword)}`;
        const res = await fetch(url);
        const data = await res.json();
        setProducts(data);
        setCurrentPage(1);
        return;
      }

      // ✅ category_id로 들어왔는데 categories가 아직 로드 전이면
      //    "전체 상품"을 먼저 불러오지 말고 대기 (이게 핵심)
      if (categoryId && categories.length === 0) return;

      // ✅ 중분류로 들어오면 첫 소분류로 강제
      if (categoryId && categories.length > 0) {
        const children = categories.filter((c) => c.parent_id === categoryId);

        const targetId =
          children.length > 0 ? (activeSubId ?? children[0].id) : categoryId;

        url += `&category_id=${targetId}`;
      }

      const res = await fetch(url);
      const data = await res.json();
      setProducts(data);
      setCurrentPage(1);
    };

    fetchProducts();
  }, [categoryId, activeSubId, categories, keyword]);

  // ===========================
  // (추가) 옵션 불러오기 (HomePage와 동일)
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
  // (추가) 장바구니/결제 (HomePage와 동일)
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

  // -----------------------
  // 페이징
  // -----------------------
  const totalPages = Math.max(
    Math.ceil(products.length / PRODUCTS_PER_PAGE),
    1
  );

  const currentGroup = Math.floor((currentPage - 1) / PAGE_GROUP_SIZE);
  const startPage = currentGroup * PAGE_GROUP_SIZE + 1;
  const endPage = Math.min(startPage + PAGE_GROUP_SIZE - 1, totalPages);

  const currentProducts = useMemo(() => {
    const start = (currentPage - 1) * PRODUCTS_PER_PAGE;
    return products.slice(start, start + PRODUCTS_PER_PAGE);
  }, [products, currentPage]);

  return (
    <main className={styles.main}>
      <header>
        <h1>{categoryTitle}</h1>
        <p>최다 판매 순</p>
      </header>

      {subCategories.length > 0 && !keyword && (
        <div className={styles.tabWrapper}>
          {/* <button
            className={activeSubId === null ? styles.activeTab : styles.tab}
            onClick={() => setActiveSubId(null)}
          >
            전체
          </button> */}

          {subCategories.map((sub) => (
            <button
              key={sub.id}
              className={
                activeSubId === sub.id ? styles.activeTab : styles.tab
              }
              onClick={() => setActiveSubId(sub.id)}
            >
              {sub.name}
            </button>
          ))}
        </div>
      )}

      <ul className={styles.productGrid}>
        {currentProducts.map((product) => {
          const selectedLabel = selectedSizeLabelByProduct[product.id];

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
                  <Image
                    src={`/products/${product.id}.jpg`}
                    alt={product.name}
                    fill
                    sizes="(max-width: 1200px) 20vw, 240px"
                    style={{ objectFit: 'cover' }}
                  />
                </div>

                <div className={styles.productInfo}>
                  <p className={styles.productName}>{product.name}</p>
                  <p className={styles.productPrice}>
                    가격 {Math.round(product.price ?? 0).toLocaleString()}원
                  </p>
                </div>
              </div>

              <div className={styles.hoverOverlay}>
                <button
                  className={styles.hoverButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    openSizeModal(product.id);
                  }}
                  type="button"
                >
                  {selectedLabel || '사이즈 선택'}
                </button>

                <button
                  className={styles.hoverButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    addToCart(product.id, false);
                  }}
                  type="button"
                >
                  장바구니
                </button>

                <button
                  className={`${styles.hoverButton} ${styles.primary}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    addToCart(product.id, true);
                  }}
                  type="button"
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
                            type="button"
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

      <nav className={styles.pagination}>
        <button
          className={styles.pageButton}
          disabled={startPage === 1}
          onClick={() => setCurrentPage(startPage - PAGE_GROUP_SIZE)}
        >
          «
        </button>

        <button
          className={styles.pageButton}
          disabled={currentPage === 1}
          onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
        >
          ‹
        </button>

        {Array.from({ length: endPage - startPage + 1 }, (_, i) => {
          const page = startPage + i;
          return (
            <button
              key={page}
              className={
                currentPage === page
                  ? styles.activePage
                  : styles.pageButton
              }
              onClick={() => setCurrentPage(page)}
            >
              {page}
            </button>
          );
        })}

        <button
          className={styles.pageButton}
          disabled={currentPage === totalPages}
          onClick={() =>
            setCurrentPage(prev => Math.min(prev + 1, totalPages))
          }
        >
          ›
        </button>

        <button
          className={styles.pageButton}
          disabled={endPage === totalPages}
          onClick={() => setCurrentPage(endPage + 1)}
        >
          »
        </button>
      </nav>
    </main>
  );
}

export default function ProductsPage() {
  return (
    <Suspense fallback={null}>
      <ProductsPageContent />
    </Suspense>
  );
}
