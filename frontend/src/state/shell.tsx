/**
 * Shell layout state shared between the app shell and a page that wants the
 * whole screen (the 3-D house in full-screen mode).
 *
 * While `immersive` is on, the shell hides its sidebar, top bar and footer;
 * `navOpen` brings the sidebar back as an overlay on top of the page.
 */

import { createContext, useContext } from "react";

export interface ShellState {
  immersive: boolean;
  setImmersive: (value: boolean) => void;
  navOpen: boolean;
  setNavOpen: (value: boolean) => void;
}

export const ShellContext = createContext<ShellState>({
  immersive: false,
  setImmersive: () => undefined,
  navOpen: false,
  setNavOpen: () => undefined,
});

export function useShell(): ShellState {
  return useContext(ShellContext);
}
