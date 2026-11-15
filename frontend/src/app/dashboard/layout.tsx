"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Avatar from "@/components/Avatar";
import Icon from "@/components/Icon";
import Logo from "@/components/Logo";
import type { IconName } from "@/components/Icon";
import { api, ApiError, tokenStore } from "@/lib/api";
import { DashboardContext } from "@/lib/dashboard-context";
import type { Scenario } from "@/types/astronaut";
import type { UserPublic } from "@/types/crew";

const SCENARIOS: { value: Scenario; label: string }[] = [
  { value: "normal", label: "Normal" },
  { value: "sleep_deprived", label: "Sleep deprived" },
  { value: "chaotic_schedule", label: "Chaotic schedule" },
];

const MISSION_DAYS = 180;

const NAV: { href: string; label: string; icon: IconName; roles: UserPublic["role"][] }[] = [
  { href: "/dashboard", label: "Overview", icon: "overview", roles: ["crew", "commander"] },
  { href: "/dashboard/checkin", label: "Daily check-in", icon: "checkin", roles: ["crew", "commander"] },
  { href: "/dashboard/sleep", label: "Sleep & schedule", icon: "moon", roles: ["crew", "commander"] },
  { href: "/dashboard/ready-to-sleep", label: "Ready to Sleep", icon: "clock", roles: ["crew"] },
  { href: "/dashboard/crew-mission", label: "Crew Mission", icon: "people", roles: ["commander"] },
  { href: "/dashboard/sleep-management", label: "Sleep Management", icon: "sliders", roles: ["commander"] },
];

const PILL =
  "glass-card flex items-center rounded-full text-[13px] font-semibold leading-[1.3] text-ink";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [scenario, setScenario] = useState<Scenario>("chaotic_schedule");
  const [day, setDay] = useState(142);
  const [menuOpen, setMenuOpen] = useState(false);

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
      <div className="flex min-h-screen items-center justify-center bg-soft text-sm text-ink-secondary">
        Loading your dashboard
      </div>
    );
  }

  const progress = Math.min(100, Math.round((day / MISSION_DAYS) * 100));

  return (
    <DashboardContext.Provider value={{ user, scenario, day }}>
      <div className="min-h-screen bg-gradient-to-b from-[#c9dafb] to-[#f3f7fe] p-3 md:p-6">
        <div className="mx-auto flex max-w-[1440px] flex-col gap-6 md:flex-row">
          <aside className="flex shrink-0 flex-col gap-1 overflow-hidden rounded-xl bg-gradient-to-b from-[#123a82] to-[#061e4a] px-4 py-[22px] text-white shadow-[0_4px_12px_0_rgba(10,43,115,0.1)] md:sticky md:top-6 md:h-[calc(100vh-3rem)] md:w-[232px]">
            <div className="flex h-11 items-end pl-2">
              <Logo />
            </div>
            <div className="h-[26px]" />
            <p className="pb-2 pl-4 text-[11px] font-semibold leading-[1.3] tracking-[0.22px]">MENU</p>

            <nav aria-label="Main" className="flex flex-col gap-1">
              {NAV.filter((item) => item.roles.includes(user.role)).map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-12 items-center gap-3 rounded-full px-4 py-3 text-[13px] font-semibold leading-[1.3] transition ${
                      active ? "accent-glow text-on-accent" : "text-white hover:bg-white/10"
                    }`}
                  >
                    <Icon name={item.icon} />
                    {item.label}
                  </Link>
                );
              })}
            </nav>

            <div className="flex-1" />

            <div className="flex flex-col gap-2 rounded-lg bg-white/[0.07] p-4">
              <div className="flex items-center gap-2">
                <Icon name="calendar" className="text-accent" />
                <p className="text-[13px] font-semibold leading-[1.3]">Mission day {day}</p>
              </div>
              <p className="text-xs font-medium leading-[1.4]">Long-duration mission, crew of 4</p>
              <div
                role="progressbar"
                aria-label="Mission progress"
                aria-valuemin={0}
                aria-valuemax={MISSION_DAYS}
                aria-valuenow={day}
                className="h-1.5 overflow-hidden rounded-full bg-white"
              >
                <div className="h-1.5 rounded-full bg-accent" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-xs font-medium leading-[1.4]">
                {day} of {MISSION_DAYS} days
              </p>
            </div>

            <div className="h-3.5" />

            <div className="relative">
              <button
                type="button"
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                onClick={() => setMenuOpen((v) => !v)}
                className="flex w-full items-center gap-2.5 rounded-full px-2 text-left hover:bg-white/5"
              >
                <Avatar name={user.name} tone="accent" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-[13px] font-semibold leading-[1.3]">{user.name}</span>
                  <span className="truncate text-xs font-medium leading-[1.4]">{user.title}</span>
                </span>
                <Icon name="chevron-down" className={`text-white transition ${menuOpen ? "rotate-180" : ""}`} />
              </button>
              {menuOpen && (
                <div role="menu" className="absolute bottom-full left-0 right-0 mb-2 rounded-2xl bg-white p-1 shadow-lg">
                  <button
                    type="button"
                    role="menuitem"
                    onClick={logout}
                    className="w-full rounded-xl px-3 py-2 text-left text-[13px] font-semibold text-ink hover:bg-soft"
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </aside>

          <div className="relative min-w-0 flex-1">
            <div className="mb-4 flex flex-wrap items-center justify-end gap-3 md:absolute md:right-0 md:top-0 md:mb-0">
              <span className="rounded-full bg-soft px-3 py-1.5 text-xs font-medium leading-[1.4] text-brand">
                Synthetic data
              </span>
              <label className={`${PILL} relative gap-2 py-3 pl-4 pr-4`}>
                <Icon name="routing" className="text-brand" />
                <span className="text-xs font-medium leading-[1.4] text-ink-muted">Scenario</span>
                <select
                  value={scenario}
                  onChange={(e) => setScenario(e.target.value as Scenario)}
                  className="cursor-pointer appearance-none bg-transparent pr-5 outline-none"
                >
                  {SCENARIOS.map((s) => (
                    <option key={s.value} value={s.value}>
                      {s.label}
                    </option>
                  ))}
                </select>
                <Icon name="chevron-down" className="pointer-events-none absolute right-4 text-ink-muted" />
              </label>
              <div className={`${PILL} gap-3 px-3.5 py-3`}>
                <button
                  type="button"
                  aria-label="Previous day"
                  onClick={() => setDay((d) => Math.max(1, d - 1))}
                  className="rounded-full text-ink-muted hover:text-ink"
                >
                  <Icon name="chevron-left" />
                </button>
                <span>Day {day}</span>
                <button
                  type="button"
                  aria-label="Next day"
                  onClick={() => setDay((d) => Math.min(999, d + 1))}
                  className="rounded-full text-ink-muted hover:text-ink"
                >
                  <Icon name="chevron-right" />
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
