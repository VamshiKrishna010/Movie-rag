import { Route, Routes } from "react-router-dom";
import { GenreSidebar } from "./components/GenreSidebar";
import { NavBar } from "./components/NavBar";
import { AuthProvider } from "./context/AuthContext";
import { GenreProvider } from "./context/GenreContext";
import { SearchProvider } from "./context/SearchContext";
import AuthPage from "./pages/AuthPage";
import HomePage from "./pages/HomePage";
import MovieDetailPage from "./pages/MovieDetailPage";

function AppRoutes() {
  return (
    <>
      <NavBar />
      <GenreSidebar />
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/" element={<HomePage />} />
        <Route path="/movie/:id" element={<MovieDetailPage />} />
      </Routes>
    </>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-bg">
      <AuthProvider>
        <SearchProvider>
          <GenreProvider>
            <AppRoutes />
          </GenreProvider>
        </SearchProvider>
      </AuthProvider>
    </div>
  );
}
