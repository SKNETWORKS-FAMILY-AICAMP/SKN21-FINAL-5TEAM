'use client';
import { useRouter } from 'next/navigation';

import { useState } from 'react';
import Link from 'next/link';
import styles from './login.module.css';
import { useAuth } from '../../authcontext';

const API_BASE_URL = 'http://localhost:8000';

/**
 * 인증 액션을 user history에 기록
 */
async function trackAuthAction(
  userId: number,
  actionType: 'login' | 'logout' | 'register'
): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/user-history/users/${userId}/track/auth`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        action_type: actionType,
      }),
    });
    console.log(`User history tracked: ${actionType} for user ${userId}`);
  } catch (err) {
    console.error('Failed to track auth action:', err);
    // 히스토리 기록 실패는 무시 (사용자 경험에 영향 없음)
  }
}

export default function LoginPage() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleGoogleLogin = () => {
    window.location.href = 'http://localhost:8000/auth/google/login';
  };

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('이메일과 비밀번호를 입력해 주세요.');
      return;
    }

    try {
      const res = await fetch('http://localhost:8000/users/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      if (!res.ok) {
        const data = await res.json();
        setError(data?.detail || '로그인에 실패했습니다.');
        return;
      }
      const data = await res.json();

      // User History에 로그인 기록
      if (data.user_id || data.id) {
        await trackAuthAction(data.user_id || data.id, 'login');
      }

      await refreshAuth();

      // admin 사용자는 user-history로 이동
      if (data.role === 'admin') {
        router.push('/admin/user-history');
      } else {
        router.push('/');
      }
      
    } catch (err) {
      setError('서버와 통신할 수 없습니다.');
    }
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        <h1 className={styles.title}>로그인</h1>

        <form className={styles.form} onSubmit={handleSubmit}>
          <input
            className={styles.input}
            type="email"
            placeholder="이메일"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className={styles.input}
            type="password"
            placeholder="비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />

          {error && <p className={styles.error}>{error}</p>}

          <button className={styles.loginButton} type="submit">
            로그인
          </button>
        </form>

        <div className={styles.social}>
          <button
            type="button"
            className={styles.googleButton}
            onClick={handleGoogleLogin}
          >
            Google로 시작하기
          </button>
        </div>

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
