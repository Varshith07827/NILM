import { Loader2 } from "lucide-react";
import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AppShell } from "@/components/layout/AppShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LiveProvider } from "@/state/live";

import Overview from "@/pages/Overview";

/**
 * Only the Overview page is in the initial bundle. Every other route — and in
 * particular the 3-D house, which pulls in Three.js — is split out, so the
 * first paint stays fast and the heavy dependency is only downloaded by
 * someone who actually opens that page.
 */
const HomeView = lazy(() => import("@/pages/HomeView"));
const Appliances = lazy(() => import("@/pages/Appliances"));
const Analytics = lazy(() => import("@/pages/Analytics"));
const Billing = lazy(() => import("@/pages/Billing"));
const ReportsPage = lazy(() => import("@/pages/ReportsPage"));
const Diagnostics = lazy(() => import("@/pages/Diagnostics"));

function PageFallback() {
  return (
    <div className="flex h-[60vh] items-center justify-center gap-2 text-muted-foreground">
      <Loader2 className="h-5 w-5 animate-spin" />
      <span className="text-xs">Loading…</span>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <LiveProvider>
        <TooltipProvider delayDuration={200}>
          <ErrorBoundary>
            <Suspense fallback={<PageFallback />}>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<Overview />} />
                <Route path="home" element={<HomeView />} />
                <Route path="appliances" element={<Appliances />} />
                <Route path="analytics" element={<Analytics />} />
                <Route path="billing" element={<Billing />} />
                <Route path="reports" element={<ReportsPage />} />
                <Route path="diagnostics" element={<Diagnostics />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
            </Suspense>
          </ErrorBoundary>
        </TooltipProvider>
      </LiveProvider>
    </BrowserRouter>
  );
}
