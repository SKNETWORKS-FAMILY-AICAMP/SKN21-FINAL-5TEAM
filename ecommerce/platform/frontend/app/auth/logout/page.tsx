'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../../authcontext';

export default function LogoutPage() {
  const router = useRouter();
  const { refreshAuth } = useAuth();

  useEffect(() => {
    const logout = async () => {
      try {
        await fetch('http://localhost:8000/users/logout', {
          method: 'POST',
          credentials: 'include', // 🔑 쿠키 포함
        });
      } catch (e) {
        // 실패해도 어차피 로컬 상태는 로그아웃 처리
      } finally {
        // 🔥 AuthContext 상태 즉시 갱신
        await refreshAuth();

        // 👉 유저 입장에서는 "로그아웃 → 로그인 화면"
        router.replace('/auth/login');
      }
    };

    logout();
  }, [router, refreshAuth]);

  return null; // 화면 없음 (동작만 수행)
}
