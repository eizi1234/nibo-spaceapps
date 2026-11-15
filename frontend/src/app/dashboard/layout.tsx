"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError, tokenStore } from "@/lib/api";
import { DashboardContext } from "@/lib/dashboard-context";
import type { Scenario } from "@/types/astronaut";
import type { UserPublic } from "@/types/crew";

const SCENARIOS: { value: Scenario; label: string }[] = [
  { value: "normal", label: "Normal" },
  { value: "sleep_deprived", label: "Sleep deprived" },
  { value: "chaotic_schedule", label: "Chaotic schedule" },
];

const NAV: { href: string; label: string; roles: UserPublic["role"][] }[] = [
  { href: "/dashboard", label: "Overview", roles: ["crew", "commander"] },
  { href: "/dashboard/checkin", label: "Daily check-in", roles: ["crew", "commander"] },
  { href: "/dashboard/sleep", label: "Sleep & circadian", roles: ["crew", "commander"] },
  { href: "/dashboard/ready-to-sleep", label: "Ready to Sleep", roles: ["crew"] },
  { href: "/dashboard/crew-mission", label: "Crew Mission", roles: ["commander"] },
  { href: "/dashboard/sleep-management", label: "Sleep Management", roles: ["commander"] },
];

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [scenario, setScenario] = useState<Scenario>("chaotic_schedule");
  const [day, setDay] = useState(142);

  useEffect(() => {
    if (!tokenStore.get()) {
      router.replace("/login");
      return;
    }
    api
      .me()
      .then(setUser)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
      });
  }, [router]);

  function logout() {
    tokenStore.clear();
    router.replace("/login");
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#eaf1fd] text-sm text-slate-500">
        Loading your dashboard
      </div>
    );
  }

  return (
    <DashboardContext.Provider value={{ user, scenario, day }}>
      <div className="min-h-screen bg-[linear-gradient(to_bottom,#cfdffb,#f4f8ff)] p-3 md:p-4">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-4 md:flex-row">
          <aside className="flex shrink-0 flex-col gap-6 rounded-3xl bg-[#0b2a6f] p-4 text-white md:sticky md:top-4 md:h-[calc(100vh-2rem)] md:w-56">
            <div className="flex items-center gap-2 px-2 pt-1">
              <span aria-hidden className="size-8 rounded-full border border-dashed border-white/60" />
              <span className="text-sm font-semibold">Crew health</span>
            </div>

            <nav aria-label="Main" className="flex flex-1 flex-row gap-2 md:flex-col">
              {NAV.filter((item) => item.roles.includes(user.role)).map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`rounded-full px-4 py-2.5 text-sm font-medium transition ${
                      active ? "bg-[#e6f23d] text-[#0a1b4d]" : "text-white/80 hover:bg-white/10"
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>

            <div className="flex items-center gap-3 rounded-2xl bg-white/10 p-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#e6f23d] text-xs font-bold text-[#0a1b4d]">
                {user.name.split(" ").map((w) => w[0]).join("").slice(0, 2)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{user.name}</p>
                <p className="truncate text-xs text-white/70">{user.title}</p>
              </div>
              <button
                onClick={logout}
                className="rounded-full px-2 py-1 text-xs text-white/80 hover:bg-white/10"
              >
                Sign out
              </button>
            </div>
          </aside>

          <div className="min-w-0 flex-1">
            <div className="mb-4 flex flex-wrap items-center justify-end gap-2">
              <span className="rounded-full bg-white/70 px-3 py-1.5 text-xs font-medium text-slate-600">
                Synthetic data
              </span>
              <label className="sr-only" htmlFor="scenario">
                Scenario
              </label>
              <select
                id="scenario"
                value={scenario}
                onChange={(e) => setScenario(e.target.value as Scenario)}
                className="rounded-full border-0 bg-white px-4 py-1.5 text-sm font-medium text-[#0a1b4d] shadow-sm outline-none focus:ring-2 focus:ring-[#1f56d6]/30"
              >
                {SCENARIOS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
              <div className="flex items-center rounded-full bg-white text-sm font-medium text-[#0a1b4d] shadow-sm">
                <button
                  aria-label="Previous day"
                  onClick={() => setDay((d) => Math.max(1, d - 1))}
                  className="rounded-l-full px-3 py-1.5 hover:bg-slate-100"
                >
                  ‹
                </button>
                <span className="px-2">Day {day}</span>
                <button
                  aria-label="Next day"
                  onClick={() => setDay((d) => Math.min(999, d + 1))}
                  className="rounded-r-full px-3 py-1.5 hover:bg-slate-100"
                >
                  ›
                </button>
              </div>
            </div>

            {children}
          </div>
        </div>
      </div>
    </DashboardContext.Provider>
  );
}