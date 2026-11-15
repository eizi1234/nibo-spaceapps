"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { BodyClockPoint, OverviewResponse, SleepDay } from "@/types/crew";

const CARD = "rounded-3xl bg-white/95 p-6 shadow-sm";

const LIGHT_PLAN = [
  { time: "07:30", title: "Bright light", subtitle: "Helps you wake up", badge: "☀", active: false },
  { time: "13:00", title: "Normal light", subtitle: "Daytime work", badge: "🌤", active: false },
  { time: "22:30", title: "Dim, warm light", subtitle: "Gets you ready for sleep", badge: "🌙", active: true },
  { time: "00:30", title: "Lights off", subtitle: "30 min earlier than last night", badge: "💤", active: false },
];

export default function SleepCircadianPage() {
  const { user, scenario, day } = useDashboard();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [sleepDays, setSleepDays] = useState<SleepDay[]>([]);
  const [clockPoints, setClockPoints] = useState<BodyClockPoint[]>([]);
  const [planApplied, setPlanApplied] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ctx = { scenario, day };
    setPlanApplied(false);

    Promise.all([
      api.overview(ctx),
      api.sleepHistory(user.id, ctx, 7),
      api.bodyClock(user.id, ctx, 14),
    ])
      .then(([ov, sh, bc]) => {
        if (cancelled) return;
        setOverview(ov);
        setSleepDays(sh);
        setClockPoints(bc);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load sleep & circadian data.");
      });

    return () => {
      cancelled = true;
    };
  }, [user.id, scenario, day]);

  async function handleApplyLightPlan() {
    setApplying(true);
    try {
      await api.applyLightPlan(day);
      setPlanApplied(true);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to apply light plan.");
    } finally {
      setApplying(false);
    }
  }

  if (error) {
    return (
      <p role="alert" className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">
        {error}
      </p>
    );
  }

  if (!overview) {
    return <p className="text-sm text-slate-500">Loading sleep & circadian telemetry...</p>;
  }

  const circ = overview.prediction.circadian;
  const shiftHours = Math.abs(circ.phase_shift_hours);
  const shiftDirection =
    circ.phase_shift_hours > 0 ? "late" : circ.phase_shift_hours < 0 ? "early" : "shifted";
  const shiftDescription = circ.phase_shift_hours > 0 ? "delayed" : "advanced";
  const lastNight = sleepDays[sleepDays.length - 1];
  const avgSleep =
    sleepDays.length > 0
      ? sleepDays.reduce((acc, r) => acc + r.hours, 0) / sleepDays.length
      : overview.baseline.sleep_hours;
  const maxShift = Math.max(3, ...clockPoints.map((p) => p.shift_hours));

  return (
    <div className="space-y-4">
      <header>
        <p className="text-sm text-slate-500">Circadian rhythm & recovery · {user.name}</p>
        <h1 className="text-3xl font-bold text-[#0a1b4d]">Sleep &amp; circadian</h1>
      </header>

      {/* Top 3 Summary Cards */}
      <div className="grid gap-4 md:grid-cols-3">
        <section className="rounded-3xl bg-[#1d4fc4] p-5 text-white shadow-sm">
          <p className="text-sm text-white/80">Body clock shift</p>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-5xl font-bold">{shiftHours.toFixed(1)}</span>
            <span className="text-sm text-white/75">hours {shiftDirection}</span>
          </div>
          <p className="mt-3 text-xs text-white/80">
            {shiftHours >= 1
              ? `Your internal clock is ${shiftDescription} compared to station schedule.`
              : "Your circadian phase is well aligned with station time."}
          </p>
        </section>

        <section className={CARD}>
          <p className="text-sm text-slate-500">Sleep last night</p>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-4xl font-bold text-[#0a1b4d]">
              {lastNight ? lastNight.hours.toFixed(1) : "-"}
            </span>
            <span className="text-sm text-slate-500">h · 7d avg {avgSleep.toFixed(1)} h</span>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Actual window:{" "}
            <strong className="text-slate-700">
              {lastNight ? `${lastNight.actual_bed} – ${lastNight.actual_wake}` : "-"}
            </strong>{" "}
            (planned 00:00 – 07:00)
          </p>
        </section>

        <section className={CARD}>
          <p className="text-sm text-slate-500">Optimal sleep window tonight</p>
          <p className="mt-2 text-2xl font-bold text-[#0a1b4d]">{circ.optimal_sleep_window}</p>
          <p className="mt-3 text-xs text-slate-500">
            Predicted sleep duration:{" "}
            <strong className="text-slate-700">{circ.predicted_sleep_hours.toFixed(1)} h</strong>
          </p>
        </section>
      </div>

      {/* Middle Charts: Planned vs Actual Sleep & 14-day Body Clock */}
      <div className="grid gap-4 lg:grid-cols-2">
        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Sleep window, last 7 days</h2>
              <p className="text-xs text-slate-400">Planned 00:00–07:00 vs actual sleep duration</p>
            </div>
            <span className="rounded-full bg-[#eaf1fd] px-3 py-1 text-xs font-semibold text-[#1d4fc4]">
              Target {overview.baseline.sleep_hours} h
            </span>
          </div>

          <div className="mt-5 space-y-3">
            {sleepDays.map((d) => {
              const widthPct = Math.min(100, Math.round((d.hours / 9) * 100));
              const low = d.hours < 6;
              return (
                <div key={d.day} className="grid grid-cols-[76px_1fr_92px] items-center gap-3 text-xs">
                  <span className="font-medium text-slate-600">{d.label}</span>
                  <div className="h-3 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className={`h-full rounded-full transition-all ${low ? "bg-orange-400" : "bg-[#1f56d6]"}`}
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                  <span className="text-right font-semibold text-[#0a1b4d]">
                    {d.hours.toFixed(1)} h ({d.actual_bed})
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Body clock drift (14 days)</h2>
              <p className="text-xs text-slate-400">Cumulative phase delay in hours</p>
            </div>
            <span className="text-xs font-medium text-slate-500">Lower is better</span>
          </div>

          <div className="mt-6 flex h-44 items-end gap-1.5">
            {clockPoints.map((pt) => {
              const hPct = Math.max(8, Math.round((pt.shift_hours / maxShift) * 100));
              return (
                <div key={pt.day} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
                  <span className="text-[10px] font-medium text-slate-600">
                    {pt.shift_hours > 0 ? `${pt.shift_hours.toFixed(1)}` : "0"}
                  </span>
                  <div
                    className={`w-full rounded-t-md ${
                      pt.shift_hours >= 1.5 ? "bg-orange-400" : "bg-[#1f56d6]"
                    }`}
                    style={{ height: `${hPct * 0.78}%` }}
                  />
                  <span className="text-[9px] text-slate-400">D{pt.day}</span>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {/* Bottom: Circadian Light Plan */}
      <section className={CARD}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold text-[#0a1b4d]">Today&apos;s circadian light plan</h2>
            <p className="text-xs text-slate-500">
              Automated cabin lighting schedule to shift your melatonin onset earlier
            </p>
          </div>

          <button
            type="button"
            disabled={applying || planApplied}
            onClick={handleApplyLightPlan}
            className={`rounded-full px-5 py-2.5 text-xs font-bold transition ${
              planApplied
                ? "bg-emerald-100 text-emerald-800"
                : "bg-[#e6f23d] text-[#0a1b4d] hover:brightness-95"
            }`}
          >
            {planApplied
              ? "✓ Applied to crew quarters"
              : applying
              ? "Applying..."
              : "Apply to crew quarters >"}
          </button>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {LIGHT_PLAN.map((item) => (
            <div
              key={item.time}
              className={`rounded-2xl border p-4 ${
                item.active ? "border-[#1d4fc4] bg-[#eaf1fd]" : "border-slate-100 bg-slate-50/70"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-bold text-[#0a1b4d]">{item.time}</span>
                <span className="text-base">{item.badge}</span>
              </div>
              <p className="mt-2 text-sm font-semibold text-slate-800">{item.title}</p>
              <p className="mt-0.5 text-xs text-slate-500">{item.subtitle}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
