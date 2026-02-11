'use client';

import Image from 'next/image';
import { useRouter } from 'next/navigation';
import styles from './page.module.css';

// 🔹 이미지 있는 id만 사용 (임시)
const PRODUCT_IDS = [1550, 1551, 1552, 1553, 1554, 1558, 1580, 1581, 1596, 1626];

export default function HomePage() {
  const router = useRouter();

  const products = PRODUCT_IDS;

  const goLogin = () => {
    router.push('/auth/login');
  };

  return (
    <main className={styles.main}>
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <div>
            <h2 className={styles.sectionTitle}>많이 찾는 스포티 스타일</h2>
            <p className={styles.sectionSubTitle}>스웨트셔츠</p>
          </div>

          <button className={styles.moreButton} onClick={goLogin}>
            더보기
          </button>
        </header>

        <ul className={styles.productGrid}>
          {products.map((id) => (
            <li key={id} className={styles.productCard}>
              <div className={styles.cardBody} onClick={goLogin}>
                <div className={styles.productImage}>
                  <Image
                    src={`/products/${id}.jpg`}
                    alt="상품 이미지"
                    fill
                    style={{ objectFit: 'cover' }}
                  />
                </div>

                <div className={styles.productInfo}>
                  <p className={styles.productName}>상품명</p>
                  <p className={styles.productName}>BASIC LOGO SWEATSHIRT NAVY</p>
                  <p className={styles.productPrice}>가격 5억</p>
                </div>
              </div>

              <div className={styles.hoverOverlay}>
                <button className={styles.hoverButton} onClick={goLogin}>
                  사이즈 선택
                </button>
                <button className={styles.hoverButton} onClick={goLogin}>
                  장바구니
                </button>
                <button
                  className={`${styles.hoverButton} ${styles.primary}`}
                  onClick={goLogin}
                >
                  바로 구매
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
