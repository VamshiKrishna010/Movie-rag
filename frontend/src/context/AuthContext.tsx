import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { fetchMe, login as apiLogin, register as apiRegister } from "../api/auth";
import { clearToken, getToken, setToken } from "../lib/auth";

interface AuthContextValue {
  user: { id: number; email: string } | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthContextValue["user"]>(null);
  const [loading, setLoading] = useState(() => !!getToken());

  useEffect(() => {
    const token = getToken();
    if (!token) {
      return;
    }

    fetchMe()
      .then((me) => setUser(me))
      .catch(() => clearToken())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await apiLogin(email, password);
    setToken(access_token);
    const me = await fetchMe();
    setUser(me);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    await apiRegister(email, password);
    await login(email, password);
  }, [login]);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
