// app/authcontext.tsx

'use client';

import { createContext, useContext, useEffect, useState } from 'react';

type AuthContextType = {
  isLoggedIn: boolean;
  refreshAuth: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  const refreshAuth = async () => {
    try {
      const res = await fetch('http://localhost:8000/users/me', {
        credentials: 'include',
      });
      setIsLoggedIn(res.ok);
    } catch {
      setIsLoggedIn(false);
    }
  };

  // 최초 1회 체크
  useEffect(() => {
    refreshAuth();
  }, []);

  return (
    <AuthContext.Provider value={{ isLoggedIn, refreshAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
