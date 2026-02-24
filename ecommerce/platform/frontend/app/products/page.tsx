'use client';

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Image from 'next/image';
import styles from './product.module.css';

const PRODUCTS_PER_PAGE = 10;
const PAGE_GROUP_SIZE = 10;
const API_BASE = 'http://localhost:8000';

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
    setActiveSubId(null);
  }, [categoryId, categories, keyword]);

  // -----------------------
  // 상품 로드
  // -----------------------
  useEffect(() => {
    const fetchProducts = async () => {
      let url = `${API_BASE}/products/new?limit=1000`;

      if (keyword) {
        url += `&keyword=${encodeURIComponent(keyword)}`;
      }

      if (!keyword && categoryId && categories.length > 0) {
        const targetId = activeSubId ?? categoryId;
        url += `&category_id=${targetId}`;
      }

      const res = await fetch(url);
      const data = await res.json();
      setProducts(data);
      setCurrentPage(1);
    };

    fetchProducts();
  }, [categoryId, activeSubId, categories, keyword]);

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
          <button
            className={activeSubId === null ? styles.activeTab : styles.tab}
            onClick={() => setActiveSubId(null)}
          >
            전체
          </button>

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
        {currentProducts.map((product) => (
          <li key={product.id} className={styles.productCard}>
            <div className={styles.cardBody}>
              <div className={styles.productImage}>
                <Image
                  src={`/products/${product.id}.jpg`}
                  alt={product.name}
                  fill
                  sizes="(max-width: 1200px) 20vw, 240px"
                  style={{ objectFit: 'cover' }}
                />
              </div>

              <p className={styles.productName}>{product.name}</p>
              <p className={styles.productPrice}>
                가격 {Math.round(product.price ?? 0).toLocaleString()}원
              </p>
            </div>

            <div className={styles.hoverOverlay}>
              <button className={styles.hoverButton}>
                사이즈 선택
              </button>
              <button className={styles.hoverButton}>
                장바구니
              </button>
              <button
                className={`${styles.hoverButton} ${styles.primary}`}
              >
                바로 구매
              </button>
            </div>
          </li>
        ))}
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