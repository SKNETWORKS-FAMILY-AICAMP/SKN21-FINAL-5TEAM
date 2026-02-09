'use client';

import styles from './header.module.css';
import Link from 'next/link';

export default function Header() {
  return (
    <header className={styles.header}>
      {/* 좌측 */}
      <div className={styles.left}>
        <button className={styles.menu}>☰</button>
        <Link href="/" className={styles.logo}>
          MOYEO
        </Link>
      </div>

      {/* 우측 */}
      <nav className={styles.right}>
        <Link href="/search">검색</Link>
        <Link href="/like">좋아요</Link>
        <Link href="/mypage">마이</Link>
        <Link href="/cart">장바구니</Link>
        <Link href="/auth/login">로그인</Link>
      </nav>
    </header>
  );
}
