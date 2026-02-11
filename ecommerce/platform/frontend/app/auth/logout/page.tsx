'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function LogoutPage() {
  const router = useRouter();

  useEffect(() => {
    fetch('http://localhost:8000/users/logout', {
      method: 'POST',
      credentials: 'include', // JWT 쿠키 포함
    }).finally(() => {
      router.replace('/auth/login'); // 로그인 페이지로 이동
    });
  }, [router]);

  return null; // 화면 없음
}

