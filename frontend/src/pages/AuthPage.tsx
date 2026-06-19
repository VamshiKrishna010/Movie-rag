import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

type Mode = "login" | "register";

interface AuthPageProps {
  adminOnly?: boolean;
  redirectTo?: string;
}

export default function AuthPage({
  adminOnly = false,
  redirectTo = "/",
}: AuthPageProps) {
  const { login, register, logout } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "login" || adminOnly) {
        const me = await login(email, password);
        if (adminOnly && me.role !== "admin") {
          await logout();
          throw new Error("This account is not an admin.");
        }
        navigate(adminOnly ? "/admin" : redirectTo);
      } else {
        await register(email, password);
        navigate(redirectTo);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const title = adminOnly
    ? "Admin sign in"
    : mode === "login"
      ? "Sign in"
      : "Create account";

  const subtitle = adminOnly
    ? "Sign in with your admin account to access the dashboard."
    : mode === "login"
      ? "Sign in to use semantic search and RAG queries."
      : "Register to unlock semantic search and RAG queries.";

  return (
    <main className="mx-auto flex min-h-[calc(100vh-6rem)] max-w-md flex-col justify-center px-4 py-8">
      <div className="rounded-2xl border border-border bg-surface p-6 shadow-bar">
        <h1 className="text-xl font-semibold text-text">{title}</h1>
        <p className="mt-1 text-sm text-muted">{subtitle}</p>

        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          <label className="block">
            <span className="text-sm text-muted">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-xl border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />
          </label>

          <label className="block">
            <span className="text-sm text-muted">Password</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete={mode === "login" || adminOnly ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 w-full rounded-xl border border-border bg-bg px-3 py-2 text-sm text-text outline-none focus:border-accent"
            />
          </label>

          {error && (
            <p className="text-sm text-red-500" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-xl bg-text px-4 py-2.5 text-sm font-medium text-bg transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? "Please wait…" : adminOnly || mode === "login" ? "Sign in" : "Register"}
          </button>
        </form>

        {!adminOnly && (
          <p className="mt-4 text-center text-sm text-muted">
            {mode === "login" ? (
              <>
                No account?{" "}
                <button
                  type="button"
                  onClick={() => {
                    setMode("register");
                    setError(null);
                  }}
                  className="text-text underline-offset-2 hover:underline"
                >
                  Register
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => {
                    setMode("login");
                    setError(null);
                  }}
                  className="text-text underline-offset-2 hover:underline"
                >
                  Sign in
                </button>
              </>
            )}
          </p>
        )}

        <p className="mt-4 text-center">
          <Link to="/" className="text-sm text-muted hover:text-text">
            ← Back to movies
          </Link>
        </p>
      </div>
    </main>
  );
}
