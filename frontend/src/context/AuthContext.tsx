import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  fetchMe,
  login as apiLogin,
  logoutApi,
  register as apiRegister,
  storeAccessToken,
  type User,
} from "../api/auth";
import { clearToken, getToken, refreshAccessToken } from "../lib/auth";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthContextValue["user"]>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function restoreSession() {
      try {
        if (getToken()) {
          setUser(await fetchMe());
          return;
        }

        const refreshed = await refreshAccessToken();
        if (refreshed) {
          setUser(await fetchMe());
        }
      } catch {
        clearToken();
      } finally {
        setLoading(false);
      }
    }

    void restoreSession();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await apiLogin(email, password);
    storeAccessToken(tokens);
    const me = await fetchMe();
    setUser(me);
    return me;
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    await apiRegister(email, password);
    await login(email, password);
  }, [login]);

  const logout = useCallback(async () => {
    await logoutApi();
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
