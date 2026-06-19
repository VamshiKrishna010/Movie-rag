import type { ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import AuthPage from "../pages/AuthPage";
import { ContentShell } from "./ContentShell";

export function AdminRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <ContentShell>
        <p className="text-sm text-muted">Loading…</p>
      </ContentShell>
    );
  }

  if (user?.role !== "admin") {
    return <AuthPage adminOnly />;
  }

  return children;
}
