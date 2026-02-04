'use client';

import Link from 'next/link';
import styles from './login.module.css';

export default function LoginPage() {
  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        <h1 className={styles.title}>로그인</h1>

        <form className={styles.form}>
          <input
            className={styles.input}
            type="email"
            placeholder="이메일"
          />
          <input
            className={styles.input}
            type="password"
            placeholder="비밀번호"
          />

          <button className={styles.loginButton}>로그인</button>
        </form>

        <div className={styles.bottom}>
          계정이 없으신가요?
          <Link href="/auth/signup">
            <strong>회원가입</strong>
          </Link>
        </div>
      </div>
    </div>
  );
}
