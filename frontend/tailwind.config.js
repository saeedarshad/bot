/** @type {import('tailwindcss').Config} */
function withOpacity(varName) {
  return ({ opacityValue } = {}) =>
    opacityValue === undefined
      ? `rgb(var(${varName}))`
      : `rgb(var(${varName}) / ${opacityValue})`;
}

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        background: withOpacity("--bg"),
        surface: withOpacity("--surface"),
        "surface-hover": withOpacity("--surface-hover"),
        muted: withOpacity("--muted"),
        border: withOpacity("--border"),
        "border-strong": withOpacity("--border-strong"),
        foreground: withOpacity("--fg"),
        "muted-foreground": withOpacity("--fg-muted"),
        "subtle-foreground": withOpacity("--fg-subtle"),
        primary: {
          DEFAULT: withOpacity("--primary"),
          hover: withOpacity("--primary-hover"),
          foreground: withOpacity("--primary-fg"),
          soft: withOpacity("--primary-soft"),
        },
        accent: {
          DEFAULT: withOpacity("--accent"),
          foreground: withOpacity("--accent-fg"),
        },
        success: withOpacity("--success"),
        warning: withOpacity("--warning"),
        danger: withOpacity("--danger"),
        info: withOpacity("--info"),
        ring: withOpacity("--ring"),
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      spacing: {
        4.5: "1.125rem",
      },
      borderRadius: {
        xl: "0.875rem",
        "2xl": "1.125rem",
      },
      boxShadow: {
        xs: "0 1px 2px 0 rgb(15 23 42 / 0.04)",
        sm: "0 1px 3px 0 rgb(15 23 42 / 0.08), 0 1px 2px -1px rgb(15 23 42 / 0.06)",
        md: "0 4px 12px -2px rgb(15 23 42 / 0.10), 0 2px 6px -2px rgb(15 23 42 / 0.06)",
        lg: "0 12px 28px -6px rgb(15 23 42 / 0.16), 0 6px 12px -8px rgb(15 23 42 / 0.10)",
        glow: "0 0 0 1px rgb(var(--primary) / 0.30), 0 8px 24px -6px rgb(var(--primary) / 0.35)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "fade-in-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "scale-in": {
          from: { opacity: "0", transform: "scale(0.97)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        "fade-in": "fade-in 0.2s ease-out",
        "fade-in-up": "fade-in-up 0.25s ease-out",
        "scale-in": "scale-in 0.15s ease-out",
      },
    },
  },
  plugins: [],
};
