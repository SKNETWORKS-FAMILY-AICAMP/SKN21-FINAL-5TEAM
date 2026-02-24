'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import styles from './product.module.css';

const PRODUCTS_PER_PAGE = 10;
const PAGE_GROUP_SIZE = 10;
const API_BASE = 'http://localhost:8000';

const CATEGORY_MAP: Record<string, string[]> = {
  상의: [
    '티셔츠','셔츠','쿠르타','쿠르티','탑','튜닉',
    '맨투맨 / 스웨트셔츠','스웨터','자켓','블레이저',
    '슈러그','조끼','서스펜더','두파타','네루 자켓',
    '레인 자켓','레헹가 촐리','롬퍼','베이비돌'
  ],
  하의: [
    '청바지','반바지','슬랙스','트랙 팬츠','레깅스','카프리',
    '스커트','파티알라','제깅스','스타킹','살와르',
    '추리다르','트랙수트','수영복','타이즈','레인 팬츠'
  ],
  원피스: ['드레스','점프수트'],
  이너웨어: [
    '브리프','브라','캐미솔','트렁크','박서',
    '이너웨어 베스트','보정 속옷'
  ],
  '라운지웨어 / 나이트웨어': [
    '나이트드레스','나이트수트','라운지 팬츠',
    '라운지 쇼츠','라운지 티셔츠','목욕 가운','로브'
  ],
  '의류 세트': ['쿠르타 세트','의류 세트','수영 세트'],
  사리: ['사리'],
  양말: ['부티','양말'],
  슈즈: [
    '캐주얼 슈즈','스포츠 슈즈','포멀 슈즈',
    '플랫 슈즈','힐','부츠형 슈즈'
  ],
  슬리퍼: ['플립플랍'],
  샌들: ['샌들','스포츠 샌들'],
  가방: [
    '핸드백','백팩','클러치','더플백','노트북 가방',
    '메신저백','모바일 파우치','럭색','태블릿 슬리브',
    '트롤리백','웨이스트 파우치'
  ],
  시계: [],
  지갑: [],
  주얼리: [
    '귀걸이','펜던트','목걸이','반지',
    '팔찌','뱅글','주얼리 세트'
  ],
  선글라스: [],
  벨트: [],
  스카프: ['스카프','머플러','스톨'],
  장갑: [],
  모자: ['캡','햇','헤드밴드'],
  커프링크: [],
  '신발 액세서리': ['신발 끈','신발 액세서리'],
  물병: [],
  '기타 잡화': [
    '여행 액세서리','키체인','헤어 액세서리',
    '타이','타이 & 커프링크 세트','액세서리 기프트 세트'
  ],
  향수: ['퍼퓸 / 바디미스트','데오드란트','향수 기프트 세트'],
  네일: ['네일 폴리쉬','네일 용품'],
  립: ['립스틱','립글로스','립라이너','립케어','립 플럼퍼'],
  메이크업: [
    '파운데이션 & 프라이머','하이라이터 & 블러셔',
    '컴팩트','컨실러','아이섀도',
    '아이라이너 / 카잘','마스카라','메이크업 리무버'
  ],
  스킨: ['페이스 모이스처라이저','세럼 / 젤','마스크팩'],
  '스킨 케어': ['클렌저','선스크린','토너','아이크림','스크럽'],
  헤어: ['헤어 컬러','남성 그루밍 키트'],
  바디: ['바디로션','바디워시','바디 스크럽'],
  '뷰티 액세서리': ['뷰티 액세서리','미용 기프트 세트'],
  '스포츠 장비': ['농구공','축구공'],
  손목밴드: [],
  '홈 패브릭': ['쿠션 커버'],
  사은품: ['사은품'],
  바우처: ['아이패드'],
};

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

export default function ProductsPage() {
  const searchParams = useSearchParams();
  const category = searchParams.get('category') || '';

  const subCategories = CATEGORY_MAP[category] || [];

  const router = useRouter();

  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [activeSub, setActiveSub] = useState<string>('전체');
  const [currentPage, setCurrentPage] = useState(1);

  // ---- 로그인 / 모달 상태 ----
  const [user, setUser] = useState<any | null>(null);
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  const [sizeModalOpenFor, setSizeModalOpenFor] = useState<number | null>(null);
  const [options, setOptions] = useState<any[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const [selectedOptionIdByProduct, setSelectedOptionIdByProduct] =
    useState<Record<number, number | null>>({});

  const [selectedSizeLabelByProduct, setSelectedSizeLabelByProduct] =
    useState<Record<number, string>>({});

  const [imageMap, setImageMap] = useState<Record<number, string>>({});

  // helper
  const requireLogin = (callback: () => void) => {
    if (isLoggedIn === null) return;
    if (!isLoggedIn) {
      router.push('/auth/login');
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
        const res = await fetch(
          `${API_BASE}/products/new/${productId}/options`,
          { credentials: 'include' }
        );

        if (!res.ok) throw new Error();

        const data = await res.json();
        const filtered = data.filter(
          (o: any) => o.is_active && o.quantity > 0
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
    const map = new Map<string, any>();
    options.forEach((o: any) => {
      const key = o.size_name ?? 'FREE';
      if (!map.has(key)) map.set(key, o);
    });
    return Array.from(map.entries()).map(([size, opt]) => ({ size, opt }));
  }, [options]);

  const selectOption = (productId: number, option: any) => {
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

  // 로그인 체크
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

  useEffect(() => {
    const fetchCategories = async () => {
      try {
        const res = await fetch(`${API_BASE}/products/categories?limit=1000`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        setCategories(data);
      } catch (err) {
        console.error(err);
      }
    };
    fetchCategories();
  }, []);

  useEffect(() => {
    const fetchProducts = async () => {
      try {
        setProducts([]);

        if (!category) {
          const res = await fetch(`${API_BASE}/products/new?limit=1000`);
          const data = await res.json();
          setProducts(data);
          setCurrentPage(1);
          return;
        }

        const targetName = activeSub !== '전체' ? activeSub : category;

        const foundCategory = categories.find(
          (c) => c.name === targetName
        );

        if (!foundCategory) {
          setProducts([]);
          return;
        }

        const childIds = categories
          .filter(c => c.parent_id === foundCategory.id)
          .map(c => c.id);

        const categoryIds = [foundCategory.id, ...childIds];

        const results: Product[] = [];

        for (const id of categoryIds) {
          const res = await fetch(
            `${API_BASE}/products/new?category_id=${id}&limit=1000`
          );
          if (!res.ok) continue;
          const data = await res.json();
          results.push(...data);
        }

        setProducts(results);
        setCurrentPage(1);

      } catch (err) {
        console.error(err);
      }
    };

    if (categories.length > 0) {
      fetchProducts();
    }
  }, [category, activeSub, categories]);

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

  useEffect(() => {
    const fetchImages = async () => {
      const newMap: Record<number, string> = {};
      await Promise.all(
        currentProducts.map(async (p) => {
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
      setImageMap(prev => ({ ...prev, ...newMap }));
    };
    if (currentProducts.length > 0) fetchImages();
  }, [currentProducts]);

  return (
    <main className={styles.main}>
      <header>
        <h1>{category || '상품 목록'}</h1>
        <p>최다 판매 순</p>
      </header>

      {subCategories.length > 0 && (
        <div className={styles.tabWrapper}>
          <button
            className={activeSub === '전체' ? styles.activeTab : styles.tab}
            onClick={() => setActiveSub('전체')}
          >
            전체
          </button>

          {subCategories.map((sub) => (
            <button
              key={sub}
              className={activeSub === sub ? styles.activeTab : styles.tab}
              onClick={() => setActiveSub(sub)}
            >
              {sub}
            </button>
          ))}
        </div>
      )}

      <ul className={styles.productGrid}>
        {currentProducts.map((product) => {
          const selectedLabel = selectedSizeLabelByProduct[product.id];

          return (
            <li key={product.id} className={styles.productCard}>
              <div className={styles.cardBody}>
                <div className={styles.productImage}>
                  {imageMap[product.id] && (
                    <img
                      src={imageMap[product.id]}
                      alt={product.name}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                  )}
                </div>

                <p className={styles.productName}>{product.name}</p>
                <p className={styles.productPrice}>
                  {product.price.toLocaleString()}원
                </p>
              </div>

              {/* 🔥 overlay 위치 수정 완료 */}
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