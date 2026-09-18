import { AlertTriangle, RotateCcw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  /** Shown instead of the generic title, e.g. "The 3-D view". */
  label?: string;
}

interface State {
  error: Error | null;
}

/**
 * Stops one broken component from blanking the whole dashboard.
 *
 * This is not hypothetical: during development a single renamed field on the
 * backend left one number undefined, a `.toFixed()` threw inside the app shell,
 * and React unmounted the entire tree — a completely white page, with the real
 * cause only visible in the console. A live dashboard that goes blank tells the
 * viewer nothing. Showing the error, and keeping the rest of the app usable, is
 * strictly better.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard error boundary caught:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex min-h-[50vh] items-center justify-center p-6">
        <div className="max-w-lg rounded-xl border border-destructive/30 bg-destructive/10 p-5">
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-4 w-4" />
            <h2 className="text-sm font-semibold">
              {this.props.label ?? "Something went wrong"}
            </h2>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            This panel failed to render. The simulation itself is unaffected —
            the backend keeps running and recording.
          </p>
          <pre className="mt-3 max-h-40 overflow-auto rounded-md border border-border/50 bg-background/60 p-2.5 font-mono text-[0.66rem] text-muted-foreground">
            {error.message}
          </pre>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => this.setState({ error: null })}>
              <RotateCcw className="h-3.5 w-3.5" />
              Try again
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => window.location.reload()}
            >
              Reload page
            </Button>
          </div>
          <p className="mt-3 text-[0.66rem] text-muted-foreground">
            If this followed a code change, the backend may be serving an older
            build — restart it with{" "}
            <code className="rounded bg-secondary px-1 py-0.5 font-mono">
              python run_backend.py
            </code>
            .
          </p>
        </div>
      </div>
    );
  }
}
