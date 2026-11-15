"use client";

import { createContext, useContext } from "react";
import type { Scenario } from "@/types/astronaut";
import type { UserPublic } from "@/types/crew";

export interface DashboardState {
  user: UserPublic;
  scenario: Scenario;
  day: number;
}

export const DashboardContext = createContext<DashboardState | null>(null);

export function useDashboard(): DashboardState {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboard must be used inside the dashboard layout");
  return value;
}
