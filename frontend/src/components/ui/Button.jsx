import { forwardRef } from "react";
import { cn } from "../../lib/cn.js";
import { Loader2 } from "lucide-react";

const VARIANTS = {
  primary:
    "bg-primary text-primary-foreground shadow-sm hover:bg-primary-hover active:translate-y-px",
  secondary:
    "bg-surface text-foreground border border-border shadow-xs hover:bg-surface-hover active:translate-y-px",
  outline:
    "border border-border-strong text-foreground hover:bg-surface-hover active:translate-y-px",
  ghost: "text-muted-foreground hover:bg-surface-hover hover:text-foreground",
  danger:
    "bg-danger text-white shadow-sm hover:brightness-95 active:translate-y-px",
  success:
    "bg-success text-white shadow-sm hover:brightness-95 active:translate-y-px",
  subtle: "bg-muted text-foreground hover:bg-surface-hover",
};

const SIZES = {
  sm: "h-8 px-3 text-xs gap-1.5 rounded-lg",
  md: "h-9 px-4 text-sm gap-2 rounded-lg",
  lg: "h-11 px-5 text-sm gap-2 rounded-xl",
  icon: "h-9 w-9 rounded-lg",
  "icon-sm": "h-8 w-8 rounded-lg",
};

const Button = forwardRef(function Button(
  {
    variant = "primary",
    size = "md",
    className,
    children,
    loading = false,
    disabled,
    icon: Icon,
    iconRight: IconRight,
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center font-medium transition-all duration-150",
        "disabled:pointer-events-none disabled:opacity-50 select-none",
        VARIANTS[variant],
        SIZES[size],
        className
      )}
      {...props}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : (
        Icon && <Icon className={cn("h-4 w-4", size === "sm" && "h-3.5 w-3.5")} />
      )}
      {children}
      {IconRight && !loading && <IconRight className="h-4 w-4" />}
    </button>
  );
});

export default Button;
