import { cn } from "../../lib/cn.js";

export function Table({ className, children }) {
  return (
    <div className="w-full overflow-x-auto scrollbar-thin">
      <table className={cn("w-full text-sm", className)}>{children}</table>
    </div>
  );
}

export function THead({ children }) {
  return (
    <thead>
      <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {children}
      </tr>
    </thead>
  );
}

export function TH({ className, ...props }) {
  return <th className={cn("whitespace-nowrap px-3 py-2.5 font-medium", className)} {...props} />;
}

export function TBody({ children }) {
  return <tbody className="divide-y divide-border">{children}</tbody>;
}

export function TR({ className, ...props }) {
  return (
    <tr
      className={cn("transition-colors hover:bg-surface-hover/60", className)}
      {...props}
    />
  );
}

export function TD({ className, ...props }) {
  return <td className={cn("px-3 py-3 align-middle", className)} {...props} />;
}
