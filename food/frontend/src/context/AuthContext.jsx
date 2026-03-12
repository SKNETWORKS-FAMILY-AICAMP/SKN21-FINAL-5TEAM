import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { login as loginApi, logout as logoutApi, fetchMe } from "../api/api";

const AuthContext = createContext({
  user: null,
  isAuthenticated: false,
  initializing: true,
  login: () => Promise.resolve({ success: false }),
  logout: () => Promise.resolve(),
});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const data = await fetchMe();
      if (cancelled) {
        return;
      }
      if (data.authenticated) {
        setUser(data.user ?? null);
      } else {
        setUser(null);
      }
      setInitializing(false);
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async ({ email, password }) => {
    const result = await loginApi({ email, password });
    if (result.success) {
      setUser(result.user ?? null);
    }
    return result;
  }, []);

  const logout = useCallback(async () => {
    await logoutApi();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      initializing,
      login,
      logout,
    }),
    [user, initializing, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
};
