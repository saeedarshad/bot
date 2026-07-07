import { Switch as HeadlessSwitch } from "@headlessui/react";
import { cn } from "../../lib/cn.js";

export default function Switch({ checked, onChange, disabled, label, className }) {
  return (
    <HeadlessSwitch
      checked={!!checked}
      onChange={onChange}
      disabled={disabled}
      className={cn(
        "group relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        checked ? "bg-primary" : "bg-border-strong",
        disabled && "cursor-not-allowed opacity-50",
        className
      )}
    >
      {label && <span className="sr-only">{label}</span>}
      <span
        className={cn(
          "inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-5" : "translate-x-0.5"
        )}
      />
    </HeadlessSwitch>
  );
}
