import { motion } from "framer-motion";
import { cn } from "../../lib/cn.js";
import { Card } from "./Card.jsx";

const ACCENTS = {
  primary: "text-primary",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
  accent: "text-accent",
  neutral: "text-foreground",
};

const ICON_BG = {
  primary: "bg-primary/10 text-primary",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-danger/10 text-danger",
  info: "bg-info/10 text-info",
  accent: "bg-accent/10 text-accent",
  neutral: "bg-muted text-muted-foreground",
};

export default function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  accent = "neutral",
  index = 0,
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28, delay: index * 0.05, ease: "easeOut" }}
    >
      <Card hover className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {label}
            </div>
            <div className={cn("mt-1.5 text-2xl font-bold tabular-nums", ACCENTS[accent])}>
              {value}
            </div>
            {sub && <div className="mt-1 text-xs text-muted-foreground">{sub}</div>}
          </div>
          {Icon && (
            <div
              className={cn(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
                ICON_BG[accent]
              )}
            >
              <Icon className="h-4 w-4" strokeWidth={2} />
            </div>
          )}
        </div>
      </Card>
    </motion.div>
  );
}
