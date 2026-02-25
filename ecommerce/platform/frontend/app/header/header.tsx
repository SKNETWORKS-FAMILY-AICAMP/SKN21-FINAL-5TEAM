'use client';

import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import styles from './header.module.css';
import Link from 'next/link';
import { useAuth } from '../authcontext';

const ADMIN_MENU = [
  { title: '유저 히스토리', href: '/admin/user-history' },
  { title: '배송정보 작성', href: '/admin/shipping' },
];

interface CategoryItem {
  id: number;
  name: string;
}

interface CategoryGroup {
  id: number;
  name: string;
  children: CategoryItem[];
}

interface UiCategory {
  title: string;
  items: CategoryItem[];
}

export default function Header() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const [categories, setCategories] = useState<UiCategory[]>([]);
  const [keyword, setKeyword] = useState('');
  const pathname = usePathname();
  const router = useRouter();

  const { isLoggedIn } = useAuth();
  const isAdmin = pathname.startsWith('/admin');

  /* =========================
     카테고리 DB 연동
  ========================== */

  useEffect(() => {
    const fetchCategories = async () => {
      try {
        const res = await fetch(
          'http://localhost:8000/products/categories/menu'
        );

        if (!res.ok) {
          throw new Error('카테고리 응답 실패');
        }

        const data: CategoryGroup[] = await res.json();

        // 기존 CATEGORY 구조와 동일하게 변환
        const mapped: UiCategory[] = data.map((parent) => ({
          title: parent.name,
          items: parent.children ?? [],
        }));

        setCategories(mapped);
      } catch (err) {
        console.error('카테고리 로딩 실패:', err);
      }
    };

    fetchCategories();
  }, []);

  /* =========================
     검색 처리
  ========================== */

  const handleSearch = () => {
    if (!keyword.trim()) return;
    router.push(`/products?keyword=${encodeURIComponent(keyword)}`);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  /* =========================
     관리자 헤더
  ========================== */

  if (isAdmin) {
    return (
      <>
        <header className={styles.header}>
          <div className={styles.left}>
            <button className={styles.menu} onClick={() => setOpen(true)}>
              ☰
            </button>
            <Link href="/admin/user-history" className={styles.logo}>
              MOYEO
            </Link>
          </div>

          <div className={styles.right}>
            <Link href="/auth/logout" className={styles.adminLogout}>
              로그아웃
            </Link>
          </div>
        </header>

        {open && <div className={styles.overlay} onClick={() => setOpen(false)} />}

        <aside className={`${styles.sidebar} ${open ? styles.open : ''}`}>
          <div className={styles.sidebarHeader}>
            <span>관리자 메뉴</span>
            <button onClick={() => setOpen(false)}>✕</button>
          </div>

          <ul className={styles.adminMenu}>
            {ADMIN_MENU.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={
                    pathname === item.href ? styles.adminMenuActive : ''
                  }
                  onClick={() => setOpen(false)}
                >
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        </aside>
      </>
    );
  }

  /* =========================
     일반 헤더
  ========================== */

  return (
    <>
      <header className={styles.header}>
        <div className={styles.left}>
          <button className={styles.menu} onClick={() => setOpen(true)}>
            ☰
          </button>

          <div className={styles.brand}>
            <Link
              href="/"
              className={`${styles.logo} ${
                !pathname.startsWith('/used') ? styles.activeBrand : ''
              }`}
            >
              MOYEO
            </Link>

            <span className={styles.divider}>|</span>

            <Link
              href="/used"
              className={`${styles.logo} ${
                pathname.startsWith('/used') ? styles.activeBrand : ''
              }`}
            >
              USED
            </Link>
          </div>
        </div>

        {/* 검색창 추가 */}
        <div className={styles.searchWrapper}>
          <input
            type="text"
            placeholder="상품명을 검색하세요"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={handleKeyDown}
            className={styles.searchInput}
          />
        </div>

        <nav className={styles.right}>
          <Link href="/mypage">마이</Link>
          <Link href="/cart">장바구니</Link>

          {!isLoggedIn && <Link href="/auth/login">로그인</Link>}
          {isLoggedIn && <Link href="/auth/logout">로그아웃</Link>}
        </nav>
      </header>

      {open && <div className={styles.overlay} onClick={() => setOpen(false)} />}

      <aside className={`${styles.sidebar} ${open ? styles.open : ''}`}>
        <div className={styles.sidebarHeader}>
          <span>카테고리</span>
          <button onClick={() => setOpen(false)}>✕</button>
        </div>

        <ul className={styles.category}>
          {categories.map((cat, idx) => (
            <li key={cat.title}>
              <button
                className={styles.categoryTitle}
                onClick={() => setActive(active === idx ? null : idx)}
              >
                {cat.title}
                <span>{active === idx ? '▴' : '▾'}</span>
              </button>

              {active === idx && (
                <ul className={styles.subCategory}>
                  {cat.items.map((item) => (
                    <li key={item.id}>
                      <Link
                        href={`/products?category_id=${item.id}`}
                        onClick={() => setOpen(false)}
                      >
                        {item.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </aside>
    </>
  );
}