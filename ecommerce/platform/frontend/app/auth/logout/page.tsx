'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
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

export default function LogoutPage() {
  const router = useRouter();
  const { user, refreshAuth } = useAuth();
  const hasTracked = useRef(false); // 중복 실행 방지

  useEffect(() => {
    const logout = async () => {
      try {
        // User History에 로그아웃 기록 (로그아웃 전에 기록, 한 번만)
        if (user?.id && !hasTracked.current) {
          hasTracked.current = true;
          await trackAuthAction(user.id, 'logout');
        }

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
