import { Loader2 } from "lucide-react";
import { cn } from "../../lib/cn.js";

export default function Spinner({ className }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-muted-foreground", className)} />;
}

export function PageSpinner({ label = "Loading…" }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-muted-foreground">
      <Loader2 className="h-6 w-6 animate-spin text-primary" />
      <span className="text-sm">{label}</span>
    </div>
  );
}
