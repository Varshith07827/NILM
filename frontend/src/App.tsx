import { Loader2 } from "lucide-react";
import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { AppShell } from "@/components/layout/AppShell";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/state/auth";
import { LiveProvider } from "@/state/live";
import { NotificationProvider } from "@/state/notifications";

import Overview from "@/pages/Overview";

/**
 * Only the Overview page is in the initial bundle. Every other route — and in
 * particular the 3-D house, which pulls in Three.js — is split out, so the
 * first paint stays fast and the heavy dependency is only downloaded by
 * someone who actually opens that page.
 */
const LiveChartsPage = lazy(() => import("@/pages/LiveChartsPage"));
const BreakdownPage = lazy(() => import("@/pages/BreakdownPage"));
const WaveformPage = lazy(() => import("@/pages/WaveformPage"));
const HomeView = lazy(() => import("@/pages/HomeView"));
const RoomsPage = lazy(() => import("@/pages/RoomsPage"));
const Appliances = lazy(() => import("@/pages/Appliances"));
const DeviceDetail = lazy(() => import("@/pages/DeviceDetail"));
const Billing = lazy(() => import("@/pages/Billing"));
const ReportsPage = lazy(() => import("@/pages/ReportsPage"));
const ControlPage = lazy(() => import("@/pages/ControlPage"));
const AccuracyPage = lazy(() => import("@/pages/AccuracyPage"));
const EventsPage = lazy(() => import("@/pages/EventsPage"));
const NotificationsPage = lazy(() => import("@/pages/NotificationsPage"));
const AdminPage = lazy(() => import("@/pages/AdminPage"));

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
      <AuthProvider>
        <LiveProvider>
          <NotificationProvider>
            <TooltipProvider delayDuration={200}>
              <ErrorBoundary>
                <Suspense fallback={<PageFallback />}>
                  <Routes>
                    <Route element={<AppShell />}>
                      <Route index element={<Overview />} />
                      <Route path="live" element={<LiveChartsPage />} />
                      <Route path="breakdown" element={<BreakdownPage />} />
                      <Route path="waveform" element={<WaveformPage />} />
                      <Route path="home" element={<HomeView />} />
                      <Route path="rooms" element={<RoomsPage />} />
                      <Route path="appliances" element={<Appliances />} />
                      <Route path="appliances/:deviceId" element={<DeviceDetail />} />
                      <Route path="billing" element={<Billing />} />
                      <Route path="reports" element={<ReportsPage />} />
                      <Route path="control" element={<ControlPage />} />
                      <Route path="accuracy" element={<AccuracyPage />} />
                      <Route path="events" element={<EventsPage />} />
                      <Route path="notifications" element={<NotificationsPage />} />
                      <Route path="admin" element={<AdminPage />} />
                      {/* Old bookmarks from before the pages were split. */}
                      <Route path="analytics" element={<Navigate to="/waveform" replace />} />
                      <Route path="diagnostics" element={<Navigate to="/accuracy" replace />} />
                      <Route path="*" element={<Navigate to="/" replace />} />
                    </Route>
                  </Routes>
                </Suspense>
              </ErrorBoundary>
            </TooltipProvider>
          </NotificationProvider>
        </LiveProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
