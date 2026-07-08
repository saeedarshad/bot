import { Component } from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";
import Button from "./ui/Button.jsx";

// Catches render/runtime errors (incl. lazy-chunk load failures) so a single
// broken page shows a friendly recovery card instead of a blank screen.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidUpdate(prevProps) {
    // Reset when the route changes so navigating away clears the error.
    if (prevProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-danger/10">
            <AlertTriangle className="h-6 w-6 text-danger" />
          </div>
          <h2 className="text-lg font-semibold text-foreground">Something went wrong</h2>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            This page hit an unexpected error. Reloading usually fixes it.
          </p>
          <Button
            className="mt-5"
            icon={RotateCcw}
            onClick={() => window.location.reload()}
          >
            Reload
          </Button>
        </div>
      );
    }
    return this.props.children;
  }
}
