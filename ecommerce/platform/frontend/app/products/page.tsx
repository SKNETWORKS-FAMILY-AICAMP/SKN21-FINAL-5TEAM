'use client';

import { useEffect, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Image from 'next/image';
import styles from './product.module.css';
import { PRODUCTS } from '../data/products';

const PRODUCTS_PER_PAGE = 10;

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

export default function ProductsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const category = searchParams.get('category') || '';
  const subCategories = CATEGORY_MAP[category] || [];

  const [activeSub, setActiveSub] = useState<string>('전체');
  const [currentPage, setCurrentPage] = useState(1);

  /** 🔑 로그인 상태 */
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null);

  useEffect(() => {
    fetch('http://localhost:8000/users/me', {
      credentials: 'include',
    })
      .then((res) => setIsLoggedIn(res.ok))
      .catch(() => setIsLoggedIn(false));
  }, []);

  /** 🔐 비회원 가드 */
  const guard = (path: string) => {
    if (isLoggedIn === null) return; // 아직 판별 중
    if (isLoggedIn === false) {
      router.push('/auth/login');
      return;
    }
    router.push(path);
  };

  /**
   * 🔹 카테고리 + 소분류 필터
   */
  const filteredProducts = PRODUCTS.filter((p) => {
    if (!category) return true;
    if (p.uiCategory !== category) return false;
    if (activeSub === '전체') return true;
    return p.uiSubCategory === activeSub;
  });

  const totalPages = Math.max(
    Math.ceil(filteredProducts.length / PRODUCTS_PER_PAGE),
    1
  );

  const startIndex = (currentPage - 1) * PRODUCTS_PER_PAGE;
  const currentProducts = filteredProducts.slice(
    startIndex,
    startIndex + PRODUCTS_PER_PAGE
  );

  return (
    <main className={styles.main}>
      {/* ===== 페이지 헤더 ===== */}
      <header className={styles.pageHeader}>
        <h1>{category || '상품 목록'}</h1>
        <p>최다 판매 순</p>
      </header>

      {/* ===== 소분류 탭 ===== */}
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
        {currentProducts.map((product) => (
          <li key={product.id} className={styles.productCard}>
            {/* 카드 본문 */}
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

              <p className={styles.productName}>
                {product.productDisplayName}
              </p>
              <p className={styles.productPrice}>
                {(product.price ?? 0).toLocaleString()}원
              </p>
            </div>

            {/* ===== hover overlay ===== */}
            <div className={styles.hoverOverlay}>
              <button
                className={styles.hoverButton}
                onClick={() => guard(`/products/${product.id}`)}
              >
                사이즈 선택
              </button>
              <button
                className={styles.hoverButton}
                onClick={() => guard('/cart')}
              >
                장바구니
              </button>
              <button
                className={`${styles.hoverButton} ${styles.primary}`}
                onClick={() => guard('/payment')}
              >
                바로 구매
              </button>
            </div>
          </li>
        ))}
      </ul>

      {/* ===== 페이지네이션 ===== */}
      <nav className={styles.pagination}>
        {Array.from({ length: totalPages }, (_, i) => (
          <button
            key={i}
            className={
              currentPage === i + 1
                ? styles.activePage
                : styles.pageButton
            }
            onClick={() => setCurrentPage(i + 1)}
          >
            {i + 1}
          </button>
        ))}
      </nav>
    </main>
  );
}
