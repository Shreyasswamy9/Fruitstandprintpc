import { createContext, useContext } from "react";
import type { Bootstrap, User } from "./api";

export interface HubContext {
  boot: Bootstrap;
  user: User;
  setUser: (u: User | null) => void;
  reloadBoot: () => Promise<void>;
  logout: (reason?: string) => Promise<void>;
  themeOverride: string | null;
  setThemeOverride: (t: string | null) => void;
}

export const Hub = createContext<HubContext | null>(null);

export function useHub(): HubContext {
  const ctx = useContext(Hub);
  if (!ctx) throw new Error("useHub outside provider");
  return ctx;
}
