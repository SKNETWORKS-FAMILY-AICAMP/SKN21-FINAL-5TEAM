'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../../authcontext';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL;

export default function LogoutPage() {
  const router = useRouter();
  const { refreshAuth } = useAuth();
  const hasLoggedOut = useRef(false); // 중복 실행 방지

  useEffect(() => {
    const logout = async () => {
      if (hasLoggedOut.current) return;
      hasLoggedOut.current = true;

      try {
        await fetch(`${API_BASE_URL}/users/logout`, {
          method: 'POST',
          credentials: 'include', // 쿠키 포함
        });
      } catch (e) {
        // 실패해도 어차피 로컬 상태는 로그아웃 처리
      } finally {
        // AuthContext 상태 즉시 갱신
        await refreshAuth();

        // 👉 유저 입장에서는 "로그아웃 → 로그인 화면"
        router.replace('/auth/login');
      }
    };

    logout();
  }, [router, refreshAuth]);

  return null; // 화면 없음 (동작만 수행)
}
