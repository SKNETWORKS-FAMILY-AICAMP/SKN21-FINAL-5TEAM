'use client';

import { useState } from 'react';
import styles from './product.module.css';

const PRODUCTS_PER_PAGE = 10;

export default function ProductsPage() {
  const products = Array.from({ length: 30 }, (_, i) => ({
    id: i + 1,
    name: `상품 ${i + 1}`,
    price: '가격',
  }));

  const [currentPage, setCurrentPage] = useState(1);

  const totalPages = Math.ceil(products.length / PRODUCTS_PER_PAGE);

  const startIndex = (currentPage - 1) * PRODUCTS_PER_PAGE;
  const currentProducts = products.slice(
    startIndex,
    startIndex + PRODUCTS_PER_PAGE
  );

  return (
    <main className={styles.main}>
      {/* ===== 헤더 ===== */}
      <header className={styles.pageHeader}>
        <h1>스웨트셔츠</h1>
        <p>최다 판매 순</p>
      </header>

      {/* ===== 상품 리스트 ===== */}
      <ul className={styles.productGrid}>
        {currentProducts.map((product) => (
          <li key={product.id} className={styles.productCard}>
            <div className={styles.productImage} />
            <p>{product.name}</p>
            <p>{product.price}</p>
          </li>
        ))}
      </ul>

      {/* ===== 페이지네이션 ===== */}
      <nav className={styles.pagination}>
        {Array.from({ length: totalPages }, (_, i) => (
          <button
            key={i}
            className={
              currentPage === i + 1 ? styles.activePage : styles.pageButton
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
