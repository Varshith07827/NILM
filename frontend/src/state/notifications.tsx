/**
 * Notification centre state: the unread count behind the bell, and optional
 * desktop pop-ups through the browser's Notification API.
 *
 * Alerts reach the browser twice: inside each live frame the moment they fire,
 * and in the database behind `/api/notifications`, where read/unread state
 * lives. The frame is the trigger (pop-up, refresh the count); the database is
 * the record.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api } from "@/lib/api";
import { useLive } from "@/state/live";
import type { Alert } from "@/types";

const POPUP_KEY = "nilm-popups";

/** Which alerts pop up on the desktop. */
export type PopupLevel = "off" | "important" | "all";

type PermissionState = NotificationPermission | "unsupported";

interface NotificationContextValue {
  unread: number;
  refresh: () => void;
  markRead: (ids?: number[]) => Promise<void>;
  popupLevel: PopupLevel;
  setPopupLevel: (level: PopupLevel) => Promise<void>;
  permission: PermissionState;
  /** Bumped whenever new alerts arrive, so lists can refetch. */
  version: number;
}

const NotificationContext = createContext<NotificationContextValue | null>(null);

function browserPermission(): PermissionState {
  return typeof window !== "undefined" && "Notification" in window
    ? window.Notification.permission
    : "unsupported";
}

function readPopupLevel(): PopupLevel {
  try {
    const raw = window.localStorage.getItem(POPUP_KEY);
    return raw === "all" || raw === "important" ? raw : "off";
  } catch {
    return "off";
  }
}

function shouldPopUp(alert: Alert, level: PopupLevel): boolean {
  if (level === "all") return true;
  if (level === "important") return alert.level === "warning" || alert.level === "critical";
  return false;
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { frame } = useLive();
  const [unread, setUnread] = useState(0);
  const [version, setVersion] = useState(0);
  const [popupLevel, setPopupLevelState] = useState<PopupLevel>(readPopupLevel);
  const [permission, setPermission] = useState<PermissionState>(browserPermission);
  const lastFrame = useRef<string | null>(null);

  const refresh = useCallback(() => {
    void api
      .notifications({ limit: 1 })
      .then((page) => setUnread(page.unread))
      .catch(() => undefined);
  }, []);

  useEffect(refresh, [refresh]);

  // New alerts in the live stream: refresh the count, and pop up.
  useEffect(() => {
    if (!frame || frame.sim_time === lastFrame.current) return;
    lastFrame.current = frame.sim_time;
    if (!frame.alerts.length) return;

    refresh();
    setVersion((value) => value + 1);

    if (permission !== "granted") return;
    for (const alert of frame.alerts) {
      if (!shouldPopUp(alert, popupLevel)) continue;
      try {
        // `tag` collapses repeats of the same alert into one pop-up.
        new window.Notification(alert.title, {
          body: alert.message,
          tag: `nilm-${alert.category}-${alert.title}`,
        });
      } catch {
        /* some browsers only allow notifications from a service worker */
      }
    }
  }, [frame, permission, popupLevel, refresh]);

  const markRead = useCallback(
    async (ids?: number[]) => {
      await api.markNotificationsRead(ids);
      refresh();
      setVersion((value) => value + 1);
    },
    [refresh],
  );

  const setPopupLevel = useCallback(async (level: PopupLevel) => {
    if (level !== "off" && browserPermission() === "default") {
      setPermission(await window.Notification.requestPermission());
    } else {
      setPermission(browserPermission());
    }
    setPopupLevelState(level);
    try {
      window.localStorage.setItem(POPUP_KEY, level);
    } catch {
      /* the choice then lasts only as long as the page */
    }
  }, []);

  const value = useMemo<NotificationContextValue>(
    () => ({ unread, refresh, markRead, popupLevel, setPopupLevel, permission, version }),
    [unread, refresh, markRead, popupLevel, setPopupLevel, permission, version],
  );

  return (
    <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>
  );
}

export function useNotifications(): NotificationContextValue {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error("useNotifications must be used inside a <NotificationProvider>");
  }
  return context;
}
