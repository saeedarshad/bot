import { Suspense, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import Sidebar from "./Sidebar.jsx";
import Topbar from "./Topbar.jsx";
import MobileNav from "./MobileNav.jsx";
import CommandPalette from "./CommandPalette.jsx";
import ErrorBoundary from "./ErrorBoundary.jsx";
import { PageSpinner } from "./ui/Spinner.jsx";

export default function AppShell({ nav, subtitle, me, onLogout, badge }) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("sidebar-collapsed") === "1";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    try {
      localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  // ⌘K / Ctrl+K opens the command palette.
  useEffect(() => {
    function onKey(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full overflow-hidden bg-background">
      <Sidebar
        nav={nav}
        subtitle={subtitle}
        collapsed={collapsed}
        onToggle={() => setCollapsed((v) => !v)}
      />
      <MobileNav
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        nav={nav}
        subtitle={subtitle}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar
          nav={nav}
          me={me}
          onLogout={onLogout}
          onOpenMobile={() => setMobileOpen(true)}
          onOpenSearch={() => setSearchOpen(true)}
          badge={badge}
        />
        <main className="flex-1 overflow-y-auto scrollbar-thin">
          {/* Enter-only keyed transition — remounts on route change so each page
              fades in. We avoid AnimatePresence's exit measurement here because
              it conflicts with a Suspense boundary suspending on lazy routes. */}
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8"
          >
            <ErrorBoundary resetKey={location.pathname}>
              <Suspense fallback={<PageSpinner />}>
                <Outlet />
              </Suspense>
            </ErrorBoundary>
          </motion.div>
        </main>
      </div>

      <CommandPalette open={searchOpen} onClose={() => setSearchOpen(false)} nav={nav} />
    </div>
  );
}
