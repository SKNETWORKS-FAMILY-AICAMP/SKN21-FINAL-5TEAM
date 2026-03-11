import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

const STORAGE_KEY = "yaam_auth_token";

const AuthContext = createContext({
  token: undefined,
  isAuthenticated: false,
  login: () => Promise.resolve({ success: false }),
  logout: () => {},
});

export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(() => {
    if (typeof window === "undefined") {
      return null;
    }
    return window.localStorage.getItem(STORAGE_KEY);
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (token) {
      window.localStorage.setItem(STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, [token]);

  const login = useCallback(async ({ email, password }) => {
    if (!email || email.toLowerCase() !== "test@example.com") {
      return {
        success: false,
        message: "test@example.com 으로만 로그인 가능합니다.",
      };
    }

    if (!password || password.length < 4) {
      return {
        success: false,
        message: "비밀번호를 4자 이상 입력해주세요.",
      };
    }

    const generatedToken = `yaam-demo-token-${Date.now()}`;
    setToken(generatedToken);

    return { success: true, token: generatedToken };
  }, []);

  const logout = useCallback(() => {
    setToken(null);
  }, []);

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: Boolean(token),
      login,
      logout,
    }),
    [token, login, logout]
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
