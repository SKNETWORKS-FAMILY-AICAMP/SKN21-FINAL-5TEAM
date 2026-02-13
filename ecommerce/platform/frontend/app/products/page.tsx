'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Image from 'next/image';
import styles from './product.module.css';
import { PRODUCTS } from '../data/products';

const PRODUCTS_PER_PAGE = 10;

// ✅ 백엔드 주소
const API_BASE = 'http://localhost:8000';

/**
 * 카테고리 → 소분류 매핑
 * (사장님과 이미 확정한 트리구조 그대로)
 */
const CATEGORY_MAP: Record<string, string[]> = {
  상의: ['셔츠', '티셔츠', '니트', '스웨터', '후드 / 스웨트셔츠', '자켓', '블레이저'],
  하의: ['청바지', '슬랙스', '트랙 팬츠', '반바지', '스커트', '레깅스'],
  원피스: ['드레스', '점프수트'],
  이너웨어: ['브라', '팬티', '박서', '캐미솔', '보정 속옷'],
  '라운지웨어 / 나이트웨어': ['파자마', '나이트 드레스', '로브', '라운지 팬츠'],
  '의류 세트': ['의류 세트', '쿠르타 세트'],
  Saree: ['사리'],
  양말: ['부츠 양말'],

  신발: ['캐주얼 슈즈', '포멀 슈즈', '스포츠 슈즈', '플랫 슈즈'],
  슬리퍼: ['플립플랍'],
  샌들: ['샌들', '스포츠 샌들'],

  가방: ['백팩', '핸드백', '더플백', '메신저백', '트롤리백'],
  시계: ['시계'],
  지갑: ['지갑'],
  주얼리: ['반지', '목걸이', '팔찌', '귀걸이'],
  아이웨어: ['선글라스'],
  벨트: ['벨트'],
  모자: ['캡', '햇'],
  '머플러 / 스카프': ['머플러', '스카프', '숄'],
  '신발 액세서리': ['신발 끈', '신발 액세서리'],
  기타: ['장갑', '우산', '물병'],

  향수: ['데오드란트', '퍼퓸 / 바디미스트'],
  메이크업: ['파운데이션', '컨실러', '아이섀도', '마스카라', '립스틱'],
  '스킨 케어': ['토너', '크림', '선스크린', '마스크팩'],
  '바디 / 배스': ['바디로션', '바디워시'],

  '스포츠 장비': ['농구공', '축구공'],
  손목밴드: ['손목밴드'],

  '홈 패브릭': ['쿠션 커버'],

  사은품: ['사은품'],
  바우처: ['아이패드'],
};

type ProductOption = {
  id: number;
  product_id: number;
  size_name: string | null;
  color: string | null;
  quantity: number;
  is_active: boolean;
};

type MeResponseLoose = {
  id?: number;
  user_id?: number;
  ok?: boolean;
  [key: string]: unknown;
};

export default function ProductsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const category = searchParams.get('category') || '';
  const subCategories = CATEGORY_MAP[category] || [];

  const [activeSub, setActiveSub] = useState<string>('전체');
  const [currentPage, setCurrentPage] = useState(1);

  /** 🔑 로그인 상태 */
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  /** 🔑 (가능하면) 로그인 유저 ID */
  const [userId, setUserId] = useState<number | null>(null);

  /** 사이즈 모달 상태 */
  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [options, setOptions] = useState<ProductOption[]>([]);

  /** 상품별 선택된 옵션(사이즈) */
  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] = useState<
    Record<number, number | null>
  >({});
  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] = useState<
    Record<number, string>
  >({});

  // ✅ 로그인 체크 + userId 확보(가능하면)
  useEffect(() => {
    const run = async () => {
      try {
        const res = await fetch(`${API_BASE}/users/me`, { credentials: 'include' });

        if (!res.ok) {
          setIsLoggedIn(false);
          setUserId(null);
          return;
        }

        const data: MeResponseLoose = await res.json();

        if (!data.authenticated) {
          setIsLoggedIn(false);
          setUserId(null);
          return;
        }

        setIsLoggedIn(true);
        const maybeId =
          (typeof data.id === 'number' && data.id) ||
          (typeof data.user_id === 'number' && data.user_id) ||
          null;
        setUserId(maybeId);
      } catch {
        setIsLoggedIn(false);
        setUserId(null);
      }
    };

    run();
  }, []);

  /** 🔐 비회원 가드 */
  const requireLoginOr = (fn: () => void) => {
    if (isLoggedIn === null) return;
    if (isLoggedIn === false) {
      router.push('/auth/login');
      return;
    }
    fn();
  };

  /**
   * 🔹 카테고리 + 소분류 필터 (원본 그대로)
   */
  const filteredProducts = PRODUCTS.filter((p) => {
    if (!category) return true;
    if (p.uiCategory !== category) return false;
    if (activeSub === '전체') return true;
    return p.uiSubCategory === activeSub;
  });

  const totalPages = Math.max(Math.ceil(filteredProducts.length / PRODUCTS_PER_PAGE), 1);

  const startIndex = (currentPage - 1) * PRODUCTS_PER_PAGE;
  const currentProducts = filteredProducts.slice(startIndex, startIndex + PRODUCTS_PER_PAGE);

  // ✅ 옵션(사이즈) 로드
  const openSizeModal = (productId: number) => {
    requireLoginOr(async () => {
      setSizeModalOpenFor(productId);
      setOptions([]);
      setOptionsLoading(true);

      try {
        const res = await fetch(`${API_BASE}/products/new/${productId}/options`, {
          credentials: 'include',
        });

        if (!res.ok) {
          throw new Error(`options fetch failed: ${res.status}`);
        }

        const data: ProductOption[] = await res.json();

        // 활성 + 재고 있는 옵션만
        const filtered = (data ?? []).filter(
          (o) => o.is_active !== false && (o.quantity ?? 0) > 0
        );

        setOptions(filtered);
      } catch (e) {
        console.error(e);
        alert('사이즈 정보를 불러오지 못했습니다. (옵션 API / 상품ID 매핑 확인 필요)');
        setSizeModalOpenFor(null);
      } finally {
        setOptionsLoading(false);
      }
    });
  };

  const closeSizeModal = () => {
    setSizeModalOpenFor(null);
    setOptions([]);
    setOptionsLoading(false);
  };

  // ✅ 같은 size_name 중 1개만 노출(메인과 동일 UX)
  const uniqueSizes = useMemo(() => {
    const map = new Map<string, ProductOption>();
    for (const o of options) {
      const key = o.size_name ?? 'FREE';
      if (!map.has(key)) map.set(key, o);
    }
    return Array.from(map.entries()).map(([size, opt]) => ({ size, opt }));
  }, [options]);

  const selectOption = (productId: number, option: ProductOption) => {
    setSelectedOptionIdByProduct((prev) => ({ ...prev, [productId]: option.id }));
    setSelectedSizeLabelByProduct((prev) => ({
      ...prev,
      [productId]: option.size_name || '선택됨',
    }));
    closeSizeModal();
  };

  // ✅ 카트 담기 (carts router.py 기준)
  const addToCart = async (productId: number, goPayment: boolean) => {
    requireLoginOr(async () => {
      const optionId = selectedOptionIdByProduct[productId];

      if (!optionId) {
        openSizeModal(productId);
        return;
      }

      // /users/me에서 id를 못 받는 프로젝트도 있어서 임시 fallback
      const resolvedUserId = userId ?? 1;

      try {
        const res = await fetch(`${API_BASE}/carts/${resolvedUserId}/items`, {
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
          const text = await res.text().catch(() => '');
          console.error('addToCart failed:', res.status, text);
          alert('장바구니 담기에 실패했습니다. (carts POST 경로/권한/userId 확인 필요)');
          return;
        }

        const cartItem = await res.json();

        // User History에 장바구니 추가 기록
        try {
          await fetch(`${API_BASE}/user-history/users/${resolvedUserId}/track/cart-action`, {
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
          console.error('Failed to track cart_add:', err);
        }

        if (goPayment) {
          router.push('/payment');
        } else {
          alert('장바구니에 담았습니다.');
        }
      } catch (e) {
        console.error(e);
        alert('장바구니 요청 중 오류가 발생했습니다.');
      }
    });
  };

  return (
    <main className={styles.main}>
      {/* ===== 페이지 헤더 (원본 그대로) ===== */}
      <header className={styles.pageHeader}>
        <h1>{category || '상품 목록'}</h1>
        <p>최다 판매 순</p>
      </header>

      {/* ===== 소분류 탭 (원본 그대로) ===== */}
      {subCategories.length > 0 && (
        <div className={styles.tabWrapper}>
          <button
            className={activeSub === '전체' ? styles.activeTab : styles.tab}
            onClick={() => {
              setActiveSub('전체');
              setCurrentPage(1);
            }}
          >
            전체
          </button>

          {subCategories.map((sub) => (
            <button
              key={sub}
              className={activeSub === sub ? styles.activeTab : styles.tab}
              onClick={() => {
                setActiveSub(sub);
                setCurrentPage(1);
              }}
            >
              {sub}
            </button>
          ))}
        </div>
      )}

      {/* ===== 상품 리스트 ===== */}
      <ul className={styles.productGrid}>
        {currentProducts.map((product) => {
          const selectedLabel = selectedSizeLabelByProduct[product.id];

          return (
            <li key={product.id} className={styles.productCard}>
              {/* 카드 본문 (원본 유지: UI만) */}
              <div className={styles.cardBody}>
                <div className={styles.productImage}>
                  <Image
                    src={`/products/${product.id}.jpg`}
                    alt={product.productDisplayName}
                    fill
                    sizes="(max-width: 768px) 50vw, 20vw"
                    style={{ objectFit: 'cover' }}
                  />
                </div>

                <p className={styles.productName}>{product.productDisplayName}</p>
                <p className={styles.productPrice}>
                  {(product.price ?? 0).toLocaleString()}원
                </p>
              </div>

              {/* ===== hover overlay (메인과 동일 로직) ===== */}
              <div className={styles.hoverOverlay}>
                <button
                  className={styles.hoverButton}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    openSizeModal(product.id);
                  }}
                >
                  {selectedLabel ? selectedLabel : '사이즈 선택'}
                </button>

                <button
                  className={styles.hoverButton}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    addToCart(product.id, false);
                  }}
                >
                  장바구니
                </button>

                <button
                  className={`${styles.hoverButton} ${styles.primary}`}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    addToCart(product.id, true);
                  }}
                >
                  바로 구매
                </button>
              </div>

              {/* ===== 사이즈 선택 모달 (UI 영향 최소: 인라인 스타일) ===== */}
              {sizeModalOpenFor === product.id && (
                <div
                  onClick={(e) => {
                    e.stopPropagation();
                    closeSizeModal();
                  }}
                  style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0,0,0,0.35)',
                    zIndex: 9999,
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    padding: '16px',
                  }}
                >
                  <div
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      width: 'min(420px, 100%)',
                      background: '#fff',
                      borderRadius: '10px',
                      padding: '16px',
                      boxShadow: '0 10px 30px rgba(0,0,0,0.15)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '12px',
                      }}
                    >
                      <strong style={{ fontSize: '14px' }}>사이즈 선택</strong>
                      <button
                        onClick={closeSizeModal}
                        style={{
                          border: 'none',
                          background: 'transparent',
                          cursor: 'pointer',
                          fontSize: '16px',
                          lineHeight: 1,
                        }}
                        aria-label="닫기"
                      >
                        ✕
                      </button>
                    </div>

                    {optionsLoading ? (
                      <p style={{ fontSize: '13px', margin: 0 }}>불러오는 중…</p>
                    ) : uniqueSizes.length === 0 ? (
                      <p style={{ fontSize: '13px', margin: 0 }}>
                        선택 가능한 사이즈가 없습니다.
                      </p>
                    ) : (
                      <div
                        style={{
                          display: 'grid',
                          gridTemplateColumns: 'repeat(4, 1fr)',
                          gap: '8px',
                        }}
                      >
                        {uniqueSizes.map(({ size, opt }) => (
                          <button
                            key={size}
                            onClick={() => selectOption(product.id, opt)}
                            style={{
                              height: '38px',
                              border: '1px solid #ddd',
                              background: '#fff',
                              borderRadius: '8px',
                              cursor: 'pointer',
                              fontSize: '13px',
                            }}
                          >
                            {size}
                          </button>
                        ))}
                      </div>
                    )}

                    <p style={{ fontSize: '12px', color: '#666', marginTop: '12px' }}>
                      * 사이즈 선택 후 장바구니/바로구매가 가능합니다.
                    </p>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {/* ===== 페이지네이션 (원본 그대로) ===== */}
      <nav className={styles.pagination}>
        {Array.from({ length: totalPages }, (_, i) => (
          <button
            key={i}
            className={currentPage === i + 1 ? styles.activePage : styles.pageButton}
            onClick={() => setCurrentPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
      </nav>
    </main>
  );
}
