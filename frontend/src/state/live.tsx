/**
 * Application-wide live state.
 *
 * The WebSocket connection lives here, above the router, so that navigating
 * between pages does not tear down and re-open the socket. A per-page hook
 * would drop the chart history and re-handshake on every click.
 *
 * Shared UI preferences that several pages need (theme, the ground-truth
 * reveal) live here too, persisted to localStorage.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useLiveSocket, type LiveData } from "@/hooks/useLiveSocket";
import { api } from "@/lib/api";
import type { ScenarioInfo } from "@/types";

const THEME_KEY = "nilm-theme";
const TRUTH_KEY = "nilm-show-truth";

type Theme = "dark" | "light";

interface LiveContextValue extends LiveData {
  scenarios: ScenarioInfo[];
  theme: Theme;
  toggleTheme: () => void;
  showTruth: boolean;
  setShowTruth: (value: boolean) => void;
  /** Call after any control mutation so the server state is re-read. */
  onChanged: () => void;
}

const LiveContext = createContext<LiveContextValue | null>(null);

/** Read a persisted preference without letting a locked-down browser break the app. */
function readStored<T>(key: string, fallback: T, parse: (raw: string) => T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? fallback : parse(raw);
  } catch {
    return fallback;
  }
}

function persist(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* preferences are a nicety, not a requirement */
  }
}

export function LiveProvider({ children }: { children: ReactNode }) {
  const live = useLiveSocket();

  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([]);
  const [theme, setTheme] = useState<Theme>(() =>
    readStored(THEME_KEY, "dark" as Theme, (raw) =>
      raw === "light" ? "light" : "dark",
    ),
  );
  const [showTruth, setShowTruthState] = useState(() =>
    readStored(TRUTH_KEY, true, (raw) => raw === "true"),
  );

  useEffect(() => {
    document.documentElement.classList.toggle("light", theme === "light");
    persist(THEME_KEY, theme);
  }, [theme]);

  const setShowTruth = useCallback((value: boolean) => {
    setShowTruthState(value);
    persist(TRUTH_KEY, String(value));
  }, []);

  const toggleTheme = useCallback(
    () => setTheme((current) => (current === "dark" ? "light" : "dark")),
    [],
  );

  useEffect(() => {
    void api
      .scenarios()
      .then(setScenarios)
      .catch(() => undefined);
  }, []);

  const onChanged = useCallback(() => {
    // Controls mutate server state; ask for a fresh status rather than
    // guessing what it became.
    live.refreshStatus();
  }, [live]);

  const value = useMemo<LiveContextValue>(
    () => ({
      ...live,
      scenarios,
      theme,
      toggleTheme,
      showTruth,
      setShowTruth,
      onChanged,
    }),
    [live, scenarios, theme, toggleTheme, showTruth, setShowTruth, onChanged],
  );

  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveContextValue {
  const context = useContext(LiveContext);
  if (!context) {
    throw new Error("useLive must be used inside a <LiveProvider>");
  }
  return context;
}
