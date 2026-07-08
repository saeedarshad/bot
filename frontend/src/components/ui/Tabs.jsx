import { useId } from "react";
import { motion } from "framer-motion";
import { cn } from "../../lib/cn.js";

// Underline-style tab bar. Controlled: pass `tabs` [{ id, label, icon? }],
// the active `value`, and `onChange`. Scrolls horizontally on small screens.
export default function Tabs({ tabs, value, onChange, className }) {
  const layoutId = useId();
  return (
    <div
      role="tablist"
      className={cn(
        "flex gap-1 overflow-x-auto scrollbar-thin border-b border-border",
        className
      )}
    >
      {tabs.map((t) => {
        const active = t.id === value;
        const Icon = t.icon;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={cn(
              "relative flex items-center gap-2 whitespace-nowrap px-3.5 py-2.5 text-sm font-medium transition-colors",
              active ? "text-primary" : "text-muted-foreground hover:text-foreground"
            )}
          >
            {Icon && <Icon className="h-4 w-4" />}
            {t.label}
            {active && (
              <motion.span
                layoutId={layoutId}
                className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-primary"
                transition={{ type: "spring", stiffness: 400, damping: 32 }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
