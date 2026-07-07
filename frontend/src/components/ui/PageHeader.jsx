import { cn } from "../../lib/cn.js";

export default function PageHeader({ title, description, actions, children, className }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between",
        className
      )}
    >
      <div className="min-w-0">
        <h1 className="text-xl font-bold tracking-tight text-foreground">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {(actions || children) && (
        <div className="flex flex-wrap items-center gap-2">{actions || children}</div>
      )}
    </div>
  );
}
