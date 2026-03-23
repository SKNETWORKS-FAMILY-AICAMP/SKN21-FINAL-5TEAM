import React, { useEffect, useState } from "react";
import { FOOD_API_BASE, buildFoodMediaUrl } from "../../api/api";
import layout from "../../styles/layout.module.css";
import styles from "./products.module.css";

const PRODUCTS_ENDPOINT = FOOD_API_BASE ? `${FOOD_API_BASE}/api/products/` : "/api/products/";

const PAGE_SIZE = 8;

const buildPlaceholderImage = (name = "상품") => {
  const safeName = String(name).slice(0, 24);
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
      <defs>
        <linearGradient id="bg" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stop-color="#f6fbf4" />
          <stop offset="100%" stop-color="#e3f2e8" />
        </linearGradient>
      </defs>
      <rect width="640" height="480" fill="url(#bg)" />
      <circle cx="320" cy="180" r="84" fill="#9ad27a" opacity="0.45" />
      <rect x="160" y="290" width="320" height="28" rx="14" fill="#0f8b6d" opacity="0.15" />
      <text x="320" y="205" text-anchor="middle" font-family="sans-serif" font-size="72">🥬</text>
      <text x="320" y="365" text-anchor="middle" font-family="sans-serif" font-size="32" font-weight="700" fill="#1f2937">${safeName}</text>
      <text x="320" y="404" text-anchor="middle" font-family="sans-serif" font-size="22" fill="#4b5563">YAAM FOOD</text>
    </svg>
  `;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
};

const Products = () => {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);

    fetch(PRODUCTS_ENDPOINT)
      .then((res) => {
        if (!res.ok) {
          throw new Error("상품을 불러오지 못했습니다.");
        }
        return res.json();
      })
      .then((data) => {
        if (isMounted) {
          setProducts(data);
          setPage(1);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message);
        }
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div className={layout.section}>
      <div className={styles.page}>
        <aside className={styles.sidebar}>
          <h2 className={styles.sidebarTitle}>필터</h2>

          <div className={styles.filterSection}>
            <p className={styles.filterTitle}>정렬</p>
            <button className={styles.resetButton} type="button">
              초기화
            </button>
          </div>

          <div className={styles.filterSection}>
            <p className={styles.filterTitle}>카테고리</p>
            <ul className={styles.filterList}>
              {["과일ㆍ견과ㆍ쌀", "채소", "수산ㆍ해산ㆍ건어물", "간식ㆍ과자"].map(
                (category) => (
                  <li key={category} className={styles.filterItem}>
                    <span className={styles.checkbox} /> {category}
                  </li>
                )
              )}
            </ul>
          </div>

          <div className={styles.filterSection}>
            <p className={styles.filterTitle}>가격</p>
            <ul className={styles.filterList}>
              {["5,000원 미만", "5,000원 ~ 10,000원", "10,000원 이상"].map(
                (price) => (
                  <li key={price} className={styles.filterItem}>
                    <span className={styles.checkbox} /> {price}
                  </li>
                )
              )}
            </ul>
          </div>
        </aside>

        <section className={styles.gridWrapper}>
          <header className={styles.hero}>
            <div>
              <p className={styles.heroSmall}>총 {products.length}건</p>
              <h1 className={styles.heroTitle}>추천순</h1>
            </div>

            <p className={styles.heroSubtext}>
              신상품순 · 판매량순 · 혜택순 · 높은 가격순 · 낮은 가격순
            </p>
          </header>

          {error && (
            <p className={`${styles.statusMessage} ${styles.error}`}>
              {error}
            </p>
          )}
          {!error && loading && (
            <p className={styles.statusMessage}>상품을 불러오는 중입니다...</p>
          )}
          {!error && !loading && products.length === 0 && (
            <p className={styles.statusMessage}>현재 추천 목록이 없어요.</p>
          )}

          {!loading && !error && products.length > 0 && (
            <>
              <div className={styles.grid}>
                {products
                  .slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
                  .map((product) => (
              <article key={product.id} className={styles.card}>
                  <div className={styles.imageWrapper}>
                    <img
                      src={
                        product.image
                          ? buildFoodMediaUrl(product.image)
                          : buildPlaceholderImage(product.name)
                      }
                      alt={product.name}
                      className={styles.productImage}
                      onError={(event) => {
                        event.currentTarget.onerror = null;
                        event.currentTarget.src = buildPlaceholderImage(product.name);
                      }}
                    />

                    <div className={styles.badge}>특가</div>
                  </div>

                  <div className={styles.productBody}>
                    <p className={styles.productDescription}>
                      신선한 식품을 빠르게 배송합니다
                    </p>

                    <h3 className={styles.productName}>{product.name}</h3>

                    <p className={styles.productPrice}>
                      {Number(product.price ?? 0).toLocaleString()}원
                    </p>

                    <div className={styles.productFooter}>
                      <span className={styles.coupon}>할인</span>

                      <button type="button" className={styles.cartButton}>
                        담기
                      </button>
                    </div>
                  </div>
                </article>
              ))}
              </div>
              <Pagination
                currentPage={page}
                totalItems={products.length}
                pageSize={PAGE_SIZE}
                onChange={setPage}
              />
            </>
          )}
        </section>
      </div>
    </div>
  );
};

const Pagination = ({ currentPage, totalItems, pageSize, onChange }) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const maxButtons = 10;

  if (totalPages === 1) return null;

  const goToPage = (newPage) => {
    const clamped = Math.min(Math.max(newPage, 1), totalPages);
    onChange(clamped);
  };

  let startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
  let endPage = startPage + maxButtons - 1;
  if (endPage > totalPages) {
    endPage = totalPages;
    startPage = Math.max(1, endPage - maxButtons + 1);
  }

  const visiblePages = [];
  for (let pageNum = startPage; pageNum <= endPage; pageNum += 1) {
    visiblePages.push(pageNum);
  }

  return (
    <div className={styles.pagination}>
      <button type="button" onClick={() => goToPage(1)} disabled={currentPage === 1}>
        &lt;&lt;
      </button>
      <button
        type="button"
        onClick={() => goToPage(currentPage - 1)}
        disabled={currentPage === 1}
      >
        &lt;
      </button>
      {visiblePages.map((pageNum) => (
        <button
          key={pageNum}
          type="button"
          className={
            currentPage === pageNum ? styles.pageButtonActive : styles.pageButton
          }
          onClick={() => goToPage(pageNum)}
        >
          {pageNum}
        </button>
      ))}
      <button
        type="button"
        onClick={() => goToPage(currentPage + 1)}
        disabled={currentPage === totalPages}
      >
        &gt;
      </button>
      <button
        type="button"
        onClick={() => goToPage(totalPages)}
        disabled={currentPage === totalPages}
      >
        &gt;&gt;
      </button>
    </div>
  );
};

export default Products;
