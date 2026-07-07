import { cn } from "../../lib/cn.js";

export function Card({ className, hover = false, ...props }) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-surface shadow-xs",
        hover && "transition-shadow hover:shadow-md",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, title, subtitle, action, children }) {
  if (title || subtitle || action) {
    return (
      <div
        className={cn(
          "flex items-start justify-between gap-4 border-b border-border px-5 py-4",
          className
        )}
      >
        <div className="min-w-0">
          {title && <h3 className="font-semibold text-foreground">{title}</h3>}
          {subtitle && (
            <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
    );
  }
  return <div className={cn("px-5 py-4", className)}>{children}</div>;
}

export function CardBody({ className, ...props }) {
  return <div className={cn("p-5", className)} {...props} />;
}

export function CardFooter({ className, ...props }) {
  return (
    <div
      className={cn("border-t border-border px-5 py-3.5", className)}
      {...props}
    />
  );
}
