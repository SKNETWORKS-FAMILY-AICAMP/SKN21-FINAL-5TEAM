'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import styles from './header.module.css';
import Link from 'next/link';
import { useAuth } from '../authcontext';

const ADMIN_MENU = [
  { title: '유저 히스토리', href: '/admin/user-history' },
  { title: '배송정보 작성', href: '/admin/shipping' },
];

const CATEGORY = [
  {
    title: '의류',
    items: [
      '상의',
      '하의',
      '원피스',
      '이너웨어',
      '라운지웨어 / 나이트웨어',
      '의류 세트',
      'Saree',
      '양말',
    ],
  },
  {
    title: '신발',
    items: ['신발', '슬리퍼', '샌들'],
  },
  {
    title: '잡화',
    items: [
      '가방',
      '시계',
      '지갑',
      '주얼리',
      '아이웨어',
      '벨트',
      '모자',
      '스카프',
      '양말',
      '넥타이',
      '커프스',
      '숄',
      '머플러',
      '신발 액세서리',
      '장갑',
      '물병',
      '스포츠 액세서리',
      '우산',
    ],
  },
  {
    title: '퍼스널 케어',
    items: [
      '향수',
      '네일',
      '립',
      '메이크업',
      '스킨',
      '아이 메이크업',
      '스킨 케어',
      '헤어',
      '바디 / 배스',
      '뷰티 액세서리',
    ],
  },
  {
    title: '스포츠',
    items: ['스포츠 장비', '손목밴드'],
  },
  {
    title: '홈',
    items: ['홈 패브릭'],
  },
  {
    title: '기타',
    items: ['사은품', '바우처'],
  },
];

export default function Header() {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const pathname = usePathname();

  // 🔑 전역 로그인 상태 (Context)
  const { isLoggedIn } = useAuth();

  const isAdmin = pathname.startsWith('/admin');

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
                  className={pathname === item.href ? styles.adminMenuActive : ''}
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

  return (
    <>
      <header className={styles.header}>
        <div className={styles.left}>
          <button className={styles.menu} onClick={() => setOpen(true)}>
            ☰
          </button>
          <Link href="/" className={styles.logo}>
            MOYEO
          </Link>
        </div>

        <nav className={styles.right}>
          <Link href="/search">검색</Link>
          <Link href="/mypage">마이</Link>
          <Link href="/cart">장바구니</Link>

          {/* ✅ 새로고침 없이 즉시 반영 */}
          {!isLoggedIn && <Link href="/auth/login">로그인</Link>}
          {isLoggedIn && <Link href="/auth/logout">로그아웃</Link>}
        </nav>
      </header>

      {/* Overlay */}
      {open && <div className={styles.overlay} onClick={() => setOpen(false)} />}

      {/* Sidebar */}
      <aside className={`${styles.sidebar} ${open ? styles.open : ''}`}>
        <div className={styles.sidebarHeader}>
          <span>카테고리</span>
          <button onClick={() => setOpen(false)}>✕</button>
        </div>

        <ul className={styles.category}>
          {CATEGORY.map((cat, idx) => (
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
                    <li key={item}>
                      <Link
                        href={`/products?category=${encodeURIComponent(item)}`}
                        onClick={() => setOpen(false)}
                      >
                        {item}
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
