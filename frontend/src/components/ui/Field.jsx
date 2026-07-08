import { forwardRef } from "react";
import { cn } from "../../lib/cn.js";
import { ChevronDown, Info } from "lucide-react";

const baseControl =
  "w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground " +
  "placeholder:text-subtle-foreground shadow-xs transition-colors " +
  "focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/60 " +
  "disabled:cursor-not-allowed disabled:opacity-60";

export const Input = forwardRef(function Input({ className, ...props }, ref) {
  return (
    <input ref={ref} className={cn(baseControl, "h-9", className)} {...props} />
  );
});

export const Textarea = forwardRef(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(baseControl, "py-2 leading-relaxed", className)}
      {...props}
    />
  );
});

export const Select = forwardRef(function Select({ className, children, ...props }, ref) {
  return (
    <div className="relative">
      <select
        ref={ref}
        className={cn(baseControl, "h-9 appearance-none pr-9", className)}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground" />
    </div>
  );
});

// Small "?" affordance next to a label: hover (or focus) reveals what the field
// is for. For fields whose purpose isn't obvious from the label alone.
export function InfoTip({ text, className }) {
  if (!text) return null;
  return (
    <span className={cn("group/tip relative inline-flex", className)} tabIndex={0}>
      <Info className="h-3.5 w-3.5 cursor-help text-subtle-foreground transition-colors group-hover/tip:text-muted-foreground" />
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 w-60 -translate-x-1/2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-normal normal-case leading-relaxed text-muted-foreground opacity-0 shadow-md transition-opacity duration-100 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

// Labelled field wrapper. Pass `label` and optionally `hint` (text under the
// control) or `info` (hover tooltip on an info icon next to the label);
// children is the control.
export function Field({ label, hint, info, htmlFor, required, className, children }) {
  return (
    <label htmlFor={htmlFor} className={cn("block space-y-1.5", className)}>
      {label && (
        <span className="flex items-center gap-1 text-sm font-medium text-foreground">
          {label}
          {required && <span className="text-danger">*</span>}
          <InfoTip text={info} />
        </span>
      )}
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}
