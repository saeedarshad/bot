import { useEffect, useState } from "react";
import { useTheme } from "./theme.jsx";

function readVar(name) {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw ? `rgb(${raw})` : "#6366f1";
}

// Resolves our CSS token colors into concrete rgb() strings that Recharts can
// use as SVG fill/stroke. Recomputes when the theme flips.
export function useChartColors() {
  const { theme } = useTheme();
  const [colors, setColors] = useState(() => resolve());

  function resolve() {
    return {
      primary: readVar("--primary"),
      accent: readVar("--accent"),
      success: readVar("--success"),
      warning: readVar("--warning"),
      danger: readVar("--danger"),
      info: readVar("--info"),
      grid: readVar("--border"),
      muted: readVar("--fg-muted"),
    };
  }

  useEffect(() => {
    // Wait a tick so the .dark class has applied before reading.
    const id = requestAnimationFrame(() => setColors(resolve()));
    return () => cancelAnimationFrame(id);
  }, [theme]);

  return colors;
}
