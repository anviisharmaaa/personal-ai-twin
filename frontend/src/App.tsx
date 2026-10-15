import { Navigate, Outlet, createBrowserRouter, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { AppShell } from "./components/AppShell";
import { Skeleton } from "./components/ui";
import { AuthCallback, AuthPage, ResetPassword } from "./pages/AuthPages";
import { Dashboard } from "./pages/Dashboard";
import { Landing } from "./pages/Landing";
import { Automations, Voice } from "./pages/Placeholders";

const Fallback = () => <Skeleton className="h-64" />;

function RequireAuth() {
  const { session, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <div className="p-10"><Skeleton className="h-10 w-48" /></div>;
  if (!session) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <Outlet />;
}

export const router = createBrowserRouter([
  { path: "/", element: <Landing /> },
  { path: "/login", element: <AuthPage initial="signin" /> },
  { path: "/register", element: <AuthPage initial="signup" /> },
  { path: "/auth/callback", element: <AuthCallback /> },
  { path: "/reset-password", element: <ResetPassword /> },
  {
    element: <RequireAuth />,
    children: [{
      path: "/app", element: <AppShell />,
      children: [
        { index: true, element: <Dashboard /> },
        { path: "onboarding", lazy: async () => ({ Component: (await import("./pages/Onboarding")).Onboarding, HydrateFallback: Fallback }) },
        { path: "studio", lazy: async () => ({ Component: (await import("./pages/TwinStudio")).TwinStudio, HydrateFallback: Fallback }) },
        { path: "conversations", lazy: async () => ({ Component: (await import("./pages/Conversations")).Conversations, HydrateFallback: Fallback }) },
        { path: "memories", lazy: async () => ({ Component: (await import("./pages/Memories")).Memories, HydrateFallback: Fallback }) },
        { path: "voice", element: <Voice /> },
        { path: "automations", element: <Automations /> },
        { path: "settings", lazy: async () => ({ Component: (await import("./pages/Settings")).Settings, HydrateFallback: Fallback }) },
      ],
    }],
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
