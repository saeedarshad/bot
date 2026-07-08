import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import { Building2 } from "lucide-react";
import { api, ensureCsrf } from "./api.js";
import { ThemeProvider } from "./lib/theme.jsx";
import { AuthProvider } from "./lib/auth.jsx";
import { STAFF_NAV } from "./nav.js";
import { ConfirmProvider, Toaster } from "./components/ui/index.js";
import { PageSpinner } from "./components/ui/Spinner.jsx";
import Badge from "./components/ui/Badge.jsx";
import AppShell from "./components/AppShell.jsx";
import Login from "./pages/Login.jsx";

// Route-level code splitting: heavy pages (Analytics pulls in Recharts) load on
// demand so the initial bundle stays lean.
const Calendar = lazy(() => import("./pages/Calendar.jsx"));
const Patients = lazy(() => import("./pages/Patients.jsx"));
const Escalations = lazy(() => import("./pages/Escalations.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));
const Chat = lazy(() => import("./pages/Chat.jsx"));
const Analytics = lazy(() => import("./pages/Analytics.jsx"));
const Recalls = lazy(() => import("./pages/Recalls.jsx"));
const Operator = lazy(() => import("./pages/Operator.jsx"));

const OPERATOR_NAV = [
  { to: "/", label: "Clinics", icon: Building2, end: true, section: "Platform" },
];

function Root() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setMe(await api("/me"));
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    ensureCsrf().then(reload);
  }, [reload]);

  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" });
    setMe(null);
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <PageSpinner label="Loading your dashboard…" />
      </div>
    );
  }

  if (!me) return <Login onLoggedIn={reload} />;

  const authValue = { me, reload, logout };

  if (me.is_superuser) {
    return (
      <AuthProvider value={authValue}>
        <Routes>
          <Route
            element={
              <AppShell
                nav={OPERATOR_NAV}
                subtitle="Operator console"
                me={me}
                onLogout={logout}
                badge={<Badge tone="accent" dot>Operator</Badge>}
              />
            }
          >
            <Route index element={<Operator />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    );
  }

  return (
    <AuthProvider value={authValue}>
      <Routes>
        <Route
          element={
            <AppShell
              nav={STAFF_NAV}
              subtitle={me.clinic?.name || "Staff dashboard"}
              me={me}
              onLogout={logout}
              badge={
                me.clinic?.name ? (
                  <Badge tone="neutral" className="hidden sm:inline-flex">
                    {me.clinic.name}
                  </Badge>
                ) : null
              }
            />
          }
        >
          <Route index element={<Calendar />} />
          <Route path="patients" element={<Patients />} />
          <Route path="escalations" element={<Escalations />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="recalls" element={<Recalls />} />
          <Route path="chat" element={<Chat />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <ConfirmProvider>
          <Root />
          <Toaster />
        </ConfirmProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
