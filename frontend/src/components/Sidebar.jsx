import { NavLink } from "react-router-dom";
import { motion } from "framer-motion";
import { PanelLeftClose, PanelLeft, Sparkles } from "lucide-react";
import { cn } from "../lib/cn.js";

function Logo({ collapsed, subtitle }) {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent shadow-sm">
        <Sparkles className="h-5 w-5 text-white" strokeWidth={2.25} />
      </div>
      {!collapsed && (
        <div className="min-w-0 leading-tight">
          <div className="truncate text-sm font-bold text-foreground">Receptionaly</div>
          <div className="truncate text-[11px] text-muted-foreground">{subtitle}</div>
        </div>
      )}
    </div>
  );
}

function NavItem({ item, collapsed, onNavigate }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          collapsed && "justify-center px-0",
          isActive
            ? "text-primary"
            : "text-muted-foreground hover:bg-surface-hover hover:text-foreground"
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.span
              layoutId="nav-active"
              className="absolute inset-0 rounded-lg bg-primary/10 ring-1 ring-inset ring-primary/20"
              transition={{ type: "spring", stiffness: 400, damping: 32 }}
            />
          )}
          <Icon className="relative z-10 h-4.5 w-4.5 shrink-0" strokeWidth={2} />
          {!collapsed && <span className="relative z-10 truncate">{item.label}</span>}
        </>
      )}
    </NavLink>
  );
}

// Shared nav content (used by both the desktop rail and the mobile drawer).
export function SidebarNav({ nav, collapsed = false, onNavigate }) {
  const sections = [...new Set(nav.map((i) => i.section))];
  return (
    <nav className="flex-1 space-y-4 overflow-y-auto scrollbar-thin px-3 py-2">
      {sections.map((section) => (
        <div key={section} className="space-y-1">
          {!collapsed && (
            <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-subtle-foreground">
              {section}
            </div>
          )}
          {nav
            .filter((i) => i.section === section)
            .map((item) => (
              <NavItem
                key={item.to}
                item={item}
                collapsed={collapsed}
                onNavigate={onNavigate}
              />
            ))}
        </div>
      ))}
    </nav>
  );
}

export { Logo as SidebarLogo };

export default function Sidebar({ nav, subtitle, collapsed, onToggle }) {
  return (
    <aside
      className={cn(
        "hidden shrink-0 flex-col border-r border-border bg-surface/60 backdrop-blur transition-[width] duration-200 md:flex",
        collapsed ? "w-[68px]" : "w-60"
      )}
    >
      <div className="flex h-16 items-center px-4">
        <Logo collapsed={collapsed} subtitle={subtitle} />
      </div>

      <SidebarNav nav={nav} collapsed={collapsed} />

      <div className="border-t border-border p-3">
        <button
          onClick={onToggle}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface-hover hover:text-foreground",
            collapsed && "justify-center px-0"
          )}
          title={collapsed ? "Expand" : "Collapse"}
        >
          {collapsed ? (
            <PanelLeft className="h-4.5 w-4.5" />
          ) : (
            <>
              <PanelLeftClose className="h-4.5 w-4.5" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
