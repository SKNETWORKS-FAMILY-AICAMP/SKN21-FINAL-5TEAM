'use client';

import { createContext, useContext, useEffect, useState } from 'react';

type User = {
  id: number;
  email: string;
  name: string;
  phone: string;
  agree_marketing: boolean;
  agree_sms: boolean;
  agree_email: boolean;
  created_at: string;
  updated_at: string;
};

type AuthContextType = {
  isLoggedIn: boolean;
  user: User | null;
  refreshAuth: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [user, setUser] = useState<User | null>(null);

  const refreshAuth = async () => {
    try {
      const res = await fetch('http://localhost:8000/users/me', {
        credentials: 'include',
      });

      if (!res.ok) {
        setIsLoggedIn(false);
        setUser(null);
        return;
      }

      const data = await res.json();

      setIsLoggedIn(true);
      setUser(data);
    } catch {
      setIsLoggedIn(false);
      setUser(null);
    }
  };

  useEffect(() => {
    refreshAuth();
  }, []);

  return (
    <AuthContext.Provider value={{ isLoggedIn, user, refreshAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
