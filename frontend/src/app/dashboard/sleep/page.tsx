"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import type { IconName } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { BodyClockPoint, OverviewResponse, SleepDay } from "@/types/crew";

const CARD = "glass-card rounded-xl p-6";
const REFRESH_MS = 5000;

type LampMode = "bright" | "warm_dim" | "off";
type LightStep = { time: string; title: string; subtitle: string; icon: IconName; lampMode: LampMode };

function toMin(hhmm: string) {
  const [h, m] = hhmm.split(":").map(Number);
  return ((h || 0) * 60 + (m || 0)) % 1440;
}

function toHhmm(min: number) {
  const m = ((Math.round(min) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

const AXIS_START = 18 * 60;

function axisPct(min: number) {
  return (((min - AXIS_START + 1440) % 1440) / 1440) * 100;
}

function span(bed: string, wake: string) {
  const start = axisPct(toMin(bed));
  const length = (((toMin(wake) - toMin(bed)) + 1440) % 1440) / 1440 * 100;
  return { left: start, width: Math.max(1.5, Math.min(100 - start, length)) };
}

function lightPlan(tonight: SleepDay | undefined): LightStep[] {
  const bed = tonight ? toMin(tonight.planned_bed) : 23 * 60 + 30;
  const wake = tonight ? toMin(tonight.planned_wake) : 6 * 60 + 30;
  return [
    { time: toHhmm(wake), title: "Bright light", subtitle: "At planned wake-up", icon: "sun", lampMode: "bright" },
    { time: "13:00", title: "Normal light", subtitle: "Daytime work", icon: "sun", lampMode: "bright" },
    { time: toHhmm(bed - 60), title: "Dim, warm light", subtitle: "1 hour before planned bedtime", icon: "moon-sm", lampMode: "warm_dim" },
    { time: toHhmm(bed), title: "Lights off", subtitle: "Planned bedtime tonight", icon: "moon-sm", lampMode: "off" },
  ];
}

export default function SleepSchedulePage() {
  const { user, scenario, day } = useDashboard();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [sleepDays, setSleepDays] = useState<SleepDay[]>([]);
  const [clockPoints, setClockPoints] = useState<BodyClockPoint[]>([]);
  const [selectedSlot, setSelectedSlot] = useState(2);
  const [planApplied, setPlanApplied] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [change, setChange] = useState<string | null>(null);
  const lastSeen = useRef<{ bed: string | null; sleep: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ctx = { scenario, day };
    lastSeen.current = null;

    async function load() {
      try {
        const [ov, sh, bc] = await Promise.all([
          api.overview(ctx),
          api.sleepHistory(user.id, ctx, 7),
          api.bodyClock(user.id, ctx, 14),
        ]);
        if (cancelled) return;

        const tonight = sh.find((d) => d.forecast);
        const mlSleep = ov.prediction.sleep;
        const sleepNow = mlSleep?.status === "ok" && mlSleep.predicted_sleep_tst_minutes != null
          ? mlSleep.predicted_sleep_tst_minutes / 60
          : ov.prediction.circadian.predicted_sleep_hours;
        const now = { bed: tonight?.planned_bed ?? null, sleep: sleepNow };
        const prev = lastSeen.current;
        if (prev && (prev.bed !== now.bed || Math.abs(prev.sleep - now.sleep) >= 0.05)) {
          setChange(
            prev.bed !== now.bed && now.bed
              ? `Your commander changed tonight's plan: bedtime ${prev.bed ?? "-"} → ${now.bed}, estimated sleep ${prev.sleep.toFixed(1)} h → ${now.sleep.toFixed(1)} h.`
              : `Updated: estimated sleep ${prev.sleep.toFixed(1)} h → ${now.sleep.toFixed(1)} h.`,
          );
        }
        lastSeen.current = now;

        setOverview(ov);
        setSleepDays(sh);
        setClockPoints(bc);
        setError(null);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load sleep data.");
      }
    }

    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, REFRESH_MS);
    const onFocus = () => void load();
    window.addEventListener("focus", onFocus);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, [user.id, scenario, day]);

  const tonight = sleepDays.find((d) => d.forecast);
  const plan = lightPlan(tonight);

  async function handleApplyLightPlan() {
    setApplying(true);
    setApplyError(null);
    const step = plan[selectedSlot];
    try {
      await Promise.all([
        api.applyLightPlan(day),
        step ? api.updateLamp({ mode: step.lampMode === "off" ? "off" : "warm" }, day) : Promise.resolve(),
      ]);
      setPlanApplied(true);
    } catch (e: unknown) {
      setPlanApplied(false);
      setApplyError(e instanceof ApiError ? e.message : "Could not apply the light plan.");
    } finally {
      setApplying(false);
    }
  }

  if (!overview) {
    return error ? (
      <p role="alert" className="rounded-2xl bg-hold-bg p-4 text-sm text-hold">
        {error}
      </p>
    ) : (
      <p className="text-sm text-ink-secondary">Loading sleep data...</p>
    );
  }

  const circ = overview.prediction.circadian;
  const shiftHours = Math.abs(circ.phase_shift_hours);
  const shiftDirection = circ.phase_shift_hours > 0 ? "late" : circ.phase_shift_hours < 0 ? "early" : "on time";
  const isDelayed = shiftHours >= 1;
  const target = overview.baseline.sleep_hours || 7;
  const mlSleep = overview.prediction.sleep ?? null;
  const sleepIsMl = mlSleep?.status === "ok" && mlSleep.predicted_sleep_tst_minutes != null && mlSleep.source !== "demo_rule";
  const sleepHours = sleepIsMl ? mlSleep!.predicted_sleep_tst_minutes! / 60 : circ.predicted_sleep_hours;
  const sleepLabel = sleepIsMl ? "Predicted sleep tonight (Model 2)" : "Estimated sleep tonight";
  const sleepNote = sleepIsMl
    ? "Total sleep time only, no bedtime forecast"
    : mlSleep?.status === "insufficient_data"
      ? "Sleep forecast: insufficient data. Illustrative estimate (not ML)"
      : "Illustrative estimate (not ML)";
  const shortfall = sleepIsMl && mlSleep!.sleep_shortfall_minutes != null
    ? Math.max(0, mlSleep!.sleep_shortfall_minutes / 60)
    : Math.max(0, target - sleepHours);
  const history = sleepDays.filter((d) => !d.forecast);
  const rows = tonight ? [...history, tonight] : history;

  return (
    <div className="flex flex-col gap-[22px]">
      <header className="flex flex-col gap-0.5 md:min-h-[46px]">
        <p className="text-[13px] leading-[1.5] text-ink-secondary">Your sleep timing and duration</p>
        <h1 className="text-[28px] font-bold leading-[1.2] tracking-[-0.42px] text-ink">Sleep &amp; schedule</h1>
      </header>

      {change && (
        <div role="status" className="flex items-start justify-between gap-3 rounded-2xl bg-go-bg px-4 py-3 text-[13px] text-go">
          <span>{change}</span>
          <button type="button" onClick={() => setChange(null)} className="shrink-0 font-semibold underline">
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-2xl bg-hold-bg px-4 py-3 text-[13px] text-hold">
          Could not refresh. Showing the last data. ({error})
        </p>
      )}

      <div className="grid gap-5 md:grid-cols-3">
        <section className="brand-glow relative flex flex-col justify-between gap-6 overflow-hidden rounded-xl p-6 text-white" aria-label="Sleep timing">
          <div className="flex items-center justify-between">
            <span className="flex size-11 items-center justify-center rounded-full bg-white text-brand">
              <Icon name="sun" size={20} />
            </span>
            <span className={`inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-[5px] text-[11px] font-semibold tracking-[0.22px] ${isDelayed ? "text-hold" : "text-go"}`}>
              <span className="size-2 rounded-full bg-current" />
              {isDelayed ? "DELAYED" : "ALIGNED"}
            </span>
          </div>
          <div>
            <p className="text-xs font-medium text-white/80">Sleep timing</p>
            <p className="mt-1 flex items-baseline gap-1.5">
              <span className="text-[44px] font-extrabold leading-none tracking-[-1.32px]">{shiftHours.toFixed(1)} h</span>
              <span className="text-sm font-medium text-white/85">{shiftDirection}</span>
            </p>
          </div>
        </section>

        <section className={`${CARD} flex flex-col justify-between gap-6`} aria-label="Predicted sleep tonight">
          <span className="flex size-11 items-center justify-center rounded-full bg-soft text-brand">
            <Icon name="moon-sm" size={20} />
          </span>
          <div>
            <p className="text-xs font-medium text-ink-muted">{sleepLabel}</p>
            <p className="mt-1 flex items-baseline gap-1">
              <span className="text-[44px] font-extrabold leading-none tracking-[-1.32px] text-ink">{sleepHours.toFixed(1)}</span>
              <span className="text-sm font-medium text-ink-muted">h</span>
            </p>
            <p className="mt-1 text-xs font-medium text-ink-muted">{sleepNote}</p>
          </div>
        </section>

        <section className={`${CARD} flex flex-col justify-between gap-6`} aria-label="Sleep shortfall">
          <span className="flex size-11 items-center justify-center rounded-full bg-soft text-brand">
            <Icon name="clock" size={20} />
          </span>
          <div>
            <p className="text-xs font-medium text-ink-muted">Sleep shortfall</p>
            <p className="mt-1 flex items-baseline gap-1">
              <span className={`text-[44px] font-extrabold leading-none tracking-[-1.32px] ${shortfall >= 1 ? "text-hold" : shortfall > 0 ? "text-caution" : "text-go"}`}>
                {shortfall.toFixed(1)}
              </span>
              <span className="text-sm font-medium text-ink-muted">h</span>
            </p>
            <p className="mt-1 text-xs font-medium text-ink-muted">{sleepIsMl ? "Model 2" : "Estimate"} vs {target} h demo target</p>
          </div>
        </section>
      </div>

      <section className={CARD} aria-labelledby="windows-heading">
        <div className="flex flex-wrap items-center gap-4">
          <h2 id="windows-heading" className="text-base font-semibold leading-[1.3] tracking-[-0.08px] text-ink">
            Sleep windows, last 7 days
          </h2>
          <span className="flex-1" />
          <Legend swatch="h-3 w-5 rounded-full border border-dashed border-ink-muted bg-white" label="Planned" />
          <Legend swatch="h-3 w-5 rounded-full bg-brand" label="Actual" />
          {tonight && <Legend swatch="h-3 w-5 rounded-full border-2 border-dashed border-brand bg-soft" label="Tonight, illustrative planned window" />}
        </div>

        <div className="mt-5 grid grid-cols-[84px_1fr_64px] items-center gap-4 text-[11px] font-medium text-ink-muted">
          <span />
          <div className="relative h-4">
            {["18:00", "00:00", "06:00", "12:00", "18:00"].map((t, i) => (
              <span
                key={`${t}-${i}`}
                className="absolute -translate-x-1/2 whitespace-nowrap first:translate-x-0 last:-translate-x-full"
                style={{ left: `${i * 25}%` }}
              >
                {t}
              </span>
            ))}
          </div>
          <span />
        </div>

        {rows.length === 0 ? (
          <p className="mt-4 text-[13px] text-ink-secondary">No sleep data yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2.5">
            {rows.map((d) => {
              const planned = span(d.planned_bed, d.planned_wake);
              const actual = span(d.actual_bed, d.actual_wake);
              const plannedHours = ((((toMin(d.planned_wake) - toMin(d.planned_bed)) + 1440) % 1440) / 60);
              const low = d.hours < target - 1.2;
              const isTonight = !!d.forecast;
              return (
                <li key={`${d.day}-${d.label}`} className="grid grid-cols-[84px_1fr_64px] items-center gap-4 text-xs">
                  <span className={`truncate ${d.label === "Last night" || isTonight ? "font-semibold text-ink" : "font-medium text-ink-muted"}`}>
                    {d.label}
                  </span>
                  <div
                    className={`relative h-7 rounded-full ${isTonight ? "bg-soft/60" : "bg-[#f4f7fe]"}`}
                    title={isTonight ? `Illustrative planned window ${d.planned_bed} to ${d.planned_wake}` : `Actual ${d.actual_bed} to ${d.actual_wake}, planned ${d.planned_bed} to ${d.planned_wake}`}
                  >
                    {[25, 50, 75].map((x) => (
                      <span key={x} aria-hidden className="absolute inset-y-1 w-px bg-white" style={{ left: `${x}%` }} />
                    ))}
                    {isTonight ? (
                      <span
                        aria-hidden
                        className="absolute inset-y-1 rounded-full border-2 border-dashed border-brand bg-brand/10"
                        style={{ left: `${planned.left}%`, width: `${planned.width}%` }}
                      />
                    ) : (
                      <>
                        <span
                          aria-hidden
                          className="absolute inset-y-0.5 rounded-full border border-dashed border-ink-muted/70 bg-white/70"
                          style={{ left: `${planned.left}%`, width: `${planned.width}%` }}
                        />
                        <span
                          aria-hidden
                          className={`absolute inset-y-1.5 rounded-full ${
                            low
                              ? "bg-[linear-gradient(90deg,#ff6b35_0%,#fc3d21_100%)]"
                              : "bg-[linear-gradient(90deg,#3470e0_0%,#0b3d91_100%)]"
                          }`}
                          style={{ left: `${actual.left}%`, width: `${actual.width}%` }}
                        />
                      </>
                    )}
                  </div>
                  <span className={`text-right font-semibold ${isTonight ? "text-brand" : low ? "text-hold" : "text-ink"}`}>
                    {isTonight ? plannedHours.toFixed(1) : d.hours.toFixed(1)} h{isTonight && <span className="block text-[11px] font-medium text-ink-muted">planned</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <div className="grid items-stretch gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className={`${CARD} flex flex-col gap-3`} aria-labelledby="shift-heading">
          <div className="flex flex-wrap items-center gap-3.5">
            <h2 id="shift-heading" className="text-base font-semibold leading-[1.3] tracking-[-0.08px] text-ink">
              Sleep schedule alignment <span className="font-normal text-ink-muted">last 14 days</span>
            </h2>
            <span className="flex-1" />
            <Legend swatch="w-[18px] border-t-[3px] border-ink" label="History" />
            {clockPoints.some((p) => p.projected) && <Legend swatch="w-[18px] border-t-[3px] border-dashed border-brand" label="Illustrative, with tonight's plan" />}
          </div>
          {clockPoints.length > 0 ? (
            <ShiftChart points={clockPoints} />
          ) : (
            <p className="text-[13px] text-ink-secondary">No data yet.</p>
          )}
          <p className="flex items-center gap-2 text-xs font-medium leading-[1.4] text-ink-muted">
            <Icon name="info-circle" />
            <span>How far bedtime is from the planned schedule. Not a biological circadian measure.</span>
          </p>
        </section>

        <section className={`${CARD} flex flex-col justify-between gap-4`} aria-labelledby="light-heading">
          <div>
            <div className="flex items-center justify-between">
              <h2 id="light-heading" className="text-base font-semibold leading-[1.3] tracking-[-0.08px] text-ink">
                Light plan today
              </h2>
              <span className="rounded-full bg-soft px-3 py-1 text-[11px] font-semibold text-brand">Rule-based suggestion</span>
            </div>
            <div className="mt-4 flex flex-col gap-2.5">
              {plan.map((item, i) => {
                const isSelected = selectedSlot === i;
                return (
                  <button
                    key={item.title}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => {
                      setSelectedSlot(i);
                      setPlanApplied(false);
                      setApplyError(null);
                    }}
                    className={`flex w-full items-center gap-3 rounded-2xl px-3.5 py-2.5 text-left transition ${
                      isSelected ? "accent-glow text-on-accent" : "bg-[#f4f7fe] text-ink hover:bg-soft"
                    }`}
                  >
                    <span className="w-11 shrink-0 text-xs font-bold">{item.time}</span>
                    <span
                      className={`flex size-8 shrink-0 items-center justify-center rounded-full ${
                        isSelected ? "bg-brand-strong text-accent" : "bg-white text-brand"
                      }`}
                    >
                      <Icon name={item.icon} />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-xs font-bold leading-tight">{item.title}</span>
                      <span className={`block truncate text-[11px] ${isSelected ? "text-on-accent/80" : "text-ink-muted"}`}>
                        {item.subtitle}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            {applyError && (
              <p role="alert" className="rounded-xl bg-hold-bg px-3 py-2 text-xs text-hold">
                {applyError}
              </p>
            )}
            <button
              type="button"
              disabled={applying}
              onClick={handleApplyLightPlan}
              className={`flex w-full items-center justify-center gap-2 rounded-full px-5 py-3 text-sm font-bold transition disabled:opacity-60 ${
                planApplied ? "bg-go-bg text-go hover:brightness-95" : "brand-glow text-white hover:brightness-110"
              }`}
            >
              {planApplied ? `Applied (${plan[selectedSlot]?.time}). Apply again` : applying ? "Applying..." : "Apply to crew quarters"}
              {!planApplied && !applying && <Icon name="chevron-right" />}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function Legend({ swatch, label }: { swatch: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs font-medium leading-[1.4] text-ink-secondary">
      <span aria-hidden className={`inline-block ${swatch}`} />
      {label}
    </span>
  );
}

function ShiftChart({ points }: { points: BodyClockPoint[] }) {
  const W = 700;
  const H = 250;
  const left = 44;
  const right = 14;
  const top = 18;
  const zeroY = 210;

  const peak = Math.max(1, ...points.map((p) => p.shift_hours));
  const step = peak <= 1.5 ? 0.5 : 1;
  const maxY = Math.ceil(peak / step) * step;
  const ticks = Array.from({ length: Math.round(maxY / step) + 1 }, (_, i) => i * step);
  const x = (i: number) => left + 14 + (i * (W - left - right - 28)) / Math.max(1, points.length - 1);
  const y = (v: number) => zeroY - (Math.max(0, v) / maxY) * (zeroY - top);

  const lastHist = points.reduce((acc, p, i) => (p.projected ? acc : i), 0);
  const line = (from: number, to: number) =>
    points
      .slice(from, to + 1)
      .map((p, k) => `${k === 0 ? "M" : "L"}${x(from + k).toFixed(1)} ${y(p.shift_hours).toFixed(1)}`)
      .join(" ");
  const hasProjection = lastHist < points.length - 1;
  const today = points[lastHist];
  const end = points[points.length - 1];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="h-auto w-full font-sans"
      role="img"
      aria-label={`Sleep timing shift is ${today.shift_hours} hours today${hasProjection ? `, projected ${end.shift_hours} hours on day ${end.day} with tonight's plan` : ""}`}
    >
      <rect x={left} y={y(Math.min(0.5, maxY))} width={W - left - right} height={zeroY - y(Math.min(0.5, maxY))} rx={8} fill="#ddf4e9" />
      <text x={left + 8} y={y(Math.min(0.5, maxY)) + 15} fontSize={12} fontWeight={500} fill="#12935f">
        Aligned
      </text>
      {ticks.map((t) => (
        <text key={t} x={0} y={y(t) + 4} fontSize={12} fontWeight={500} fill="#92a0bf">
          +{t} h
        </text>
      ))}
      {hasProjection && (
        <rect x={x(lastHist)} y={top - 6} width={x(points.length - 1) - x(lastHist) + 8} height={zeroY - top + 6} rx={8} fill="#e3ecfd" opacity={0.5} />
      )}
      <path d={line(0, lastHist)} fill="none" stroke="#0a1a3a" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      {hasProjection && (
        <>
          <path d={line(lastHist, points.length - 1)} fill="none" stroke="#0b3d91" strokeWidth={2.5} strokeDasharray="7 6" strokeLinecap="round" />
          {points.slice(lastHist + 1).map((p, k) => (
            <circle key={p.day} cx={x(lastHist + 1 + k)} cy={y(p.shift_hours)} r={3.5} fill="#fff" stroke="#0b3d91" strokeWidth={2} />
          ))}
        </>
      )}
      <circle cx={x(lastHist)} cy={y(today.shift_hours)} r={5} fill="#fff" stroke={today.shift_hours >= 1 ? "#fc3d21" : "#12935f"} strokeWidth={2.5} />
      <text x={x(0)} y={H - 6} fontSize={12} fontWeight={500} fill="#92a0bf" textAnchor="start">
        Day {points[0].day}
      </text>
      <text x={x(lastHist)} y={H - 6} fontSize={12} fontWeight={600} fill="#0a1a3a" textAnchor={hasProjection ? "middle" : "end"}>
        Today
      </text>
      {hasProjection && (
        <text x={x(points.length - 1)} y={H - 6} fontSize={12} fontWeight={500} fill="#0b3d91" textAnchor="end">
          Day {end.day}
        </text>
      )}
    </svg>
  );
}
