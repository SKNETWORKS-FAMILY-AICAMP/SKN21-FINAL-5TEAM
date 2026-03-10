import React, { useEffect, useState } from "react";
import layout from "../../styles/layout.module.css";
import styles from "./products.module.css";

const PRODUCTS_ENDPOINT = "/api/products/";

const Products = () => {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
            <div className={styles.grid}>
              {products.map((product) => (
                <article key={product.id} className={styles.card}>
                  <div className={styles.imageWrapper}>
                    <img
                      src={
                        product.image
                          ? `http://127.0.0.1:8000/media/${product.image}`
                          : `https://via.placeholder.com/400x300?text=${encodeURIComponent(
                              product.name ?? "상품"
                            )}`
                      }
                      alt={product.name}
                      className={styles.productImage}
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
          )}
        </section>
      </div>
    </div>
  );
};

export default Products;
