import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "../../lib/theme.jsx";

// Themed wrapper around sonner. Styling is driven by our CSS tokens so toasts
// match light/dark automatically.
export default function Toaster() {
  const { theme } = useTheme();
  return (
    <SonnerToaster
      theme={theme}
      position="bottom-right"
      richColors
      closeButton
      toastOptions={{
        style: {
          borderRadius: "0.75rem",
          fontFamily: "Inter, sans-serif",
        },
      }}
    />
  );
}

export { toast } from "sonner";
