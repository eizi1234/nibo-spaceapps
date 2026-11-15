"use client";

import { useEffect, useRef, useState } from "react";
import Icon from "@/components/Icon";
import type { IconName } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { BodyClockPoint, OverviewResponse, SleepDay } from "@/types/crew";

const CARD = "glass-card rounded-[24px] p-6";

// Data ini di-refresh otomatis supaya perubahan dari commander muncul tanpa reload.
const REFRESH_MS = 5000;

// Backend belum mengirim field ini. Begitu ada, kartu Sleep debt otomatis memakainya
// (nilainya konsisten dengan halaman Overview). Sebelum itu dipakai hitungan lama dari riwayat tidur.
type OverviewWithDebt = OverviewResponse & { sleep_debt_hours?: number };

const LIGHT_PLAN: {
  time: string;
  title: string;
  subtitle: string;
  icon: IconName;
  lampMode: "bright" | "warm_dim" | "off";
}[] = [
  { time: "07:30", title: "Bright light", subtitle: "Helps you wake up", icon: "sun", lampMode: "bright" },
  { time: "13:00", title: "Normal light", subtitle: "Daytime work", icon: "sun", lampMode: "bright" },
  { time: "22:30", title: "Dim, warm light", subtitle: "Gets you ready for sleep", icon: "moon-sm", lampMode: "warm_dim" },
  { time: "01:00", title: "Lights off", subtitle: "30 min earlier than last night", icon: "moon-sm", lampMode: "off" },
];

// Konversi string jam "HH:MM" ke posisi persen pada timeline 24 jam (mulai 18:00 s.d. 18:00 berikutnya)
function timeToTimelinePct(hhmm: string): number {
  const [hStr, mStr] = hhmm.split(":");
  const h = Number(hStr) || 0;
  const m = Number(mStr) || 0;
  const totalHours = h + m / 60;
  const offsetFrom18 = (totalHours - 18 + 24) % 24;
  return Math.min(96, Math.max(4, (offsetFrom18 / 24) * 100));
}

export default function SleepCircadianPage() {
  const { user, scenario, day } = useDashboard();
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [sleepDays, setSleepDays] = useState<SleepDay[]>([]);
  const [clockPoints, setClockPoints] = useState<BodyClockPoint[]>([]);
  const [selectedSlot, setSelectedSlot] = useState<string>("22:30");
  const [planApplied, setPlanApplied] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [change, setChange] = useState<string | null>(null);

  // Angka sirkadian dari pengambilan data sebelumnya, untuk mendeteksi perubahan.
  const lastSeen = useRef<{ shift: number; sleep: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    const ctx = { scenario, day };
    lastSeen.current = null; // skenario/hari berganti: jangan bandingkan dengan data konteks lain

    async function load() {
      try {
        const [ov, sh, bc] = await Promise.all([
          api.overview(ctx),
          api.sleepHistory(user.id, ctx, 7),
          api.bodyClock(user.id, ctx, 14),
        ]);
        if (cancelled) return;

        const c = ov.prediction.circadian;
        const prev = lastSeen.current;
        if (
          prev &&
          (Math.abs(prev.shift - c.phase_shift_hours) >= 0.05 ||
            Math.abs(prev.sleep - c.predicted_sleep_hours) >= 0.05)
        ) {
          setChange(
            `Updated: body clock ${Math.abs(prev.shift).toFixed(1)} h → ${Math.abs(c.phase_shift_hours).toFixed(1)} h, ` +
              `predicted sleep ${prev.sleep.toFixed(1)} h → ${c.predicted_sleep_hours.toFixed(1)} h`,
          );
        }
        lastSeen.current = { shift: c.phase_shift_hours, sleep: c.predicted_sleep_hours };

        setOverview(ov);
        setSleepDays(sh);
        setClockPoints(bc);
        setError(null);
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load sleep & circadian data.");
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

  async function handleApplyLightPlan() {
    setApplying(true);
    setApplyError(null);
    const activePlan = LIGHT_PLAN.find((p) => p.time === selectedSlot);
    try {
      await Promise.all([
        api.applyLightPlan(day),
        activePlan
          ? api.updateLamp({ mode: activePlan.lampMode === "off" ? "off" : "warm" }, day)
          : Promise.resolve(),
      ]);
      setPlanApplied(true);
    } catch (e: unknown) {
      // Jangan menampilkan "Applied" kalau permintaannya gagal.
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
      <p className="text-sm text-ink-secondary">Loading sleep &amp; circadian telemetry...</p>
    );
  }

  const circ = overview.prediction.circadian;
  const shiftHours = Math.abs(circ.phase_shift_hours);
  const shiftDirection =
    circ.phase_shift_hours > 0 ? "late" : circ.phase_shift_hours < 0 ? "early" : "aligned";
  const isDelayed = shiftHours >= 1;
  const recHours = overview.baseline.sleep_hours || 7;

  // Sleep debt: pakai nilai dari backend kalau ada, kalau tidak hitung dari riwayat 7 hari.
  const serverDebt = (overview as OverviewWithDebt).sleep_debt_hours;
  const sleepDebt =
    serverDebt ?? sleepDays.reduce((acc, d) => acc + Math.max(0, recHours - d.hours), 0);

  // Posisi kotak Planned Window (00:00 s.d. 07:00 pada skala 18:00 - 18:00)
  const plannedLeftPct = timeToTimelinePct("00:00");
  const plannedWidthPct = (recHours / 24) * 100;

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-0.5">
        <p className="text-[13px] font-medium text-ink-secondary">Your body clock and sleep pattern</p>
        <h1 className="text-[28px] font-bold leading-[1.2] tracking-[-0.42px] text-ink">Sleep &amp; circadian</h1>
      </header>

      {change && (
        <div
          role="status"
          className="flex items-start justify-between gap-3 rounded-2xl bg-go-bg px-4 py-3 text-sm text-go"
        >
          <span>{change}</span>
          <button type="button" onClick={() => setChange(null)} className="shrink-0 font-semibold underline">
            Dismiss
          </button>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-2xl bg-hold-bg px-4 py-3 text-sm text-hold">
          Could not refresh. Showing the last data. ({error})
        </p>
      )}

      {/* Top 3 Summary Cards (Matching Figma) */}
      <div className="grid gap-5 md:grid-cols-3">
        {/* 1. Body Clock Card */}
        <section
          className="brand-glow relative flex flex-col justify-between overflow-hidden rounded-[24px] p-6 text-white"
          aria-label="Body clock"
        >
          <div className="flex items-center justify-between">
            <span className="flex size-9 items-center justify-center rounded-full bg-white text-brand">
              <Icon name="sun" />
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1 text-[11px] font-extrabold tracking-wide ${
                isDelayed ? "text-hold" : "text-go"
              }`}
            >
              <span className={`size-1.5 rounded-full ${isDelayed ? "bg-hold" : "bg-go"}`} />
              {isDelayed ? "DELAYED" : "ALIGNED"}
            </span>
          </div>

          <div className="mt-6">
            <p className="text-xs font-medium text-white/80">Body clock</p>
            <div className="mt-1 flex items-baseline gap-1.5">
              <span className="text-4xl font-extrabold tracking-tight">{shiftHours.toFixed(1)} h</span>
              <span className="text-sm font-medium text-white/85">{shiftDirection}</span>
            </div>
          </div>
        </section>

        {/* 2. Predicted Sleep Tonight Card */}
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Predicted sleep tonight">
          <div>
            <span className="flex size-9 items-center justify-center rounded-full bg-soft text-brand">
              <Icon name="moon-sm" />
            </span>
          </div>

          <div className="mt-6">
            <p className="text-xs font-medium text-ink-muted">Predicted sleep tonight</p>
            <div className="mt-1 flex items-baseline gap-1">
              <span className="text-4xl font-extrabold tracking-tight text-ink">
                {circ.predicted_sleep_hours.toFixed(1)}
              </span>
              <span className="text-base font-medium text-ink-muted">h</span>
            </div>
            <p className="mt-1 text-xs text-ink-muted">Recommended {recHours} h</p>
          </div>
        </section>

        {/* 3. Sleep Debt Card */}
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Sleep debt">
          <div>
            <span className="flex size-9 items-center justify-center rounded-full bg-soft text-brand">
              <Icon name="clock" />
            </span>
          </div>

          <div className="mt-6">
            <p className="text-xs font-medium text-ink-muted">Sleep debt</p>
            <div className="mt-1 flex items-baseline gap-1">
              <span className="text-4xl font-extrabold tracking-tight text-hold">
                {sleepDebt.toFixed(1)}
              </span>
              <span className="text-base font-medium text-ink-muted">h</span>
            </div>
            <p className="mt-1 text-xs text-ink-muted">Builds up night by night</p>
          </div>
        </section>
      </div>

      {/* Middle Full-Width Card: Sleep Windows, Last 7 Days (Timeline Style matching Figma) */}
      <section className={CARD} aria-label="Sleep windows, last 7 days">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-base font-semibold text-ink">Sleep windows, last 7 days</h2>
          <div className="flex items-center gap-4 text-xs font-medium text-ink-muted">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-5 rounded-full border border-dashed border-slate-400 bg-slate-100" />
              Planned
            </span>
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-3 w-5 rounded-full bg-[#0b3d91]" />
              Actual
            </span>
          </div>
        </div>

        {/* 24-hour Axis Header */}
        <div className="mt-5 grid grid-cols-[76px_1fr_52px] items-center gap-4 text-[11px] font-medium text-ink-muted">
          <span />
          <div className="flex justify-between px-1">
            <span>18:00</span>
            <span>00:00</span>
            <span>06:00</span>
            <span>12:00</span>
            <span>18:00</span>
          </div>
          <span />
        </div>

        {/* 7 Day Rows */}
        <div className="mt-3 space-y-3">
          {sleepDays.map((d) => {
            const actualLeft = timeToTimelinePct(d.actual_bed);
            const actualWidth = Math.min(45, Math.max(12, (d.hours / 24) * 100));
            const isLow = d.hours < recHours - 1.2;

            return (
              <div key={d.day} className="grid grid-cols-[76px_1fr_52px] items-center gap-4 text-xs">
                <span
                  className={
                    d.label === "Last night" ? "font-bold text-ink" : "font-medium text-ink-muted"
                  }
                >
                  {d.label}
                </span>

                {/* Timeline Track */}
                <div className="relative h-7 rounded-full bg-[#f4f7fe]">
                  {/* Planned Dashed Window */}
                  <div
                    className="absolute top-0.5 bottom-0.5 rounded-full border border-dashed border-slate-400/70 bg-white/60"
                    style={{
                      left: `${plannedLeftPct}%`,
                      width: `${plannedWidthPct}%`,
                    }}
                  />

                  {/* Actual Sleep Capsule */}
                  <div
                    className={`absolute top-1.5 bottom-1.5 rounded-full transition-all ${
                      isLow
                        ? "bg-[linear-gradient(90deg,#ff6b35_0%,#e63946_100%)]"
                        : "bg-[linear-gradient(90deg,#1d56c4_0%,#0b3d91_100%)]"
                    }`}
                    style={{
                      left: `${actualLeft}%`,
                      width: `${actualWidth}%`,
                    }}
                  />
                </div>

                <span className={`text-right font-bold ${isLow ? "text-hold" : "text-ink"}`}>
                  {d.hours.toFixed(1)} h
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {/* Bottom 2-Column Section */}
      <div className="grid items-stretch gap-5 lg:grid-cols-[1fr_360px]">
        {/* Left: Body Clock Shift (Last 14 Days SVG Line Chart) */}
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Body clock shift">
          <div>
            <h2 className="text-base font-semibold text-ink">
              Body clock shift <span className="font-normal text-ink-muted">last 14 days</span>
            </h2>
          </div>

          <div className="mt-4">
            <BodyClockLineChart points={clockPoints} />
          </div>
        </section>

        {/* Right: Interactive Light Plan Today */}
        <section className={`${CARD} flex flex-col justify-between gap-4`} aria-label="Light plan today">
          <div>
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-ink">Light plan today</h2>
              <span className="rounded-full bg-soft px-3 py-1 text-[11px] font-semibold text-brand">
                Crew quarters
              </span>
            </div>

            <div className="mt-4 space-y-2.5">
              {LIGHT_PLAN.map((item) => {
                const isSelected = selectedSlot === item.time;
                return (
                  <button
                    key={item.time}
                    type="button"
                    onClick={() => {
                      setSelectedSlot(item.time);
                      setPlanApplied(false);
                      setApplyError(null);
                    }}
                    className={`flex w-full items-center gap-3 rounded-2xl px-3.5 py-2.5 text-left transition ${
                      isSelected
                        ? "accent-glow text-on-accent"
                        : "bg-[#f4f7fe] text-ink hover:bg-slate-200/60"
                    }`}
                  >
                    <span
                      className={`w-11 shrink-0 text-xs font-bold ${
                        isSelected ? "text-on-accent" : "text-ink"
                      }`}
                    >
                      {item.time}
                    </span>

                    <span
                      className={`flex size-8 shrink-0 items-center justify-center rounded-full ${
                        isSelected
                          ? "bg-[#0a1b4d] text-[#e6f23d]"
                          : "bg-white text-brand shadow-2xs"
                      }`}
                    >
                      <Icon name={item.icon} />
                    </span>

                    <div className="min-w-0">
                      <p
                        className={`text-xs font-bold leading-tight ${
                          isSelected ? "text-on-accent" : "text-ink"
                        }`}
                      >
                        {item.title}
                      </p>
                      <p
                        className={`truncate text-[11px] ${
                          isSelected ? "text-on-accent/80" : "text-ink-muted"
                        }`}
                      >
                        {item.subtitle}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="space-y-2">
            {applyError && (
              <p role="alert" className="rounded-xl bg-hold-bg px-3 py-2 text-xs text-hold">
                {applyError}
              </p>
            )}
            <button
              type="button"
              disabled={applying}
              onClick={handleApplyLightPlan}
              className={`w-full rounded-full py-3 text-xs font-bold transition ${
                planApplied
                  ? "bg-go-bg text-go hover:brightness-95"
                  : "brand-glow text-white hover:brightness-110"
              }`}
            >
              {planApplied
                ? `✓ Applied (${selectedSlot}) · Click to re-apply`
                : applying
                ? "Applying..."
                : "Apply to crew quarters >"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function BodyClockLineChart({ points }: { points: BodyClockPoint[] }) {
  const W = 540;
  const H = 220;
  const left = 40;
  const right = 18;
  const top = 20;
  const zeroY = 184;

  const data =
    points.length > 0
      ? points
      : [
          { day: 129, shift_hours: 0 },
          { day: 135, shift_hours: 0.6 },
          { day: 142, shift_hours: 3.0 },
        ];

  const maxY = Math.max(3, Math.ceil(Math.max(...data.map((p) => p.shift_hours))));
  const x = (i: number) =>
    left + 12 + (i * (W - left - right - 24)) / Math.max(1, data.length - 1);
  const y = (v: number) => zeroY - (Math.max(0, v) / maxY) * (zeroY - top);

  const pathD = data
    .map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(p.shift_hours).toFixed(1)}`)
    .join(" ");

  const ticks = [0, 1, 2, 3];
  const lastIdx = data.length - 1;
  const midIdx = Math.floor(lastIdx / 2);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full font-sans">
      {/* Green Aligned Zone (0h to 0.5h) */}
      <rect
        x={left}
        y={y(0.5)}
        width={W - left - right}
        height={zeroY - y(0.5)}
        rx={8}
        fill="#ddf4e9"
      />
      <text x={left + 10} y={y(0.5) + 15} fontSize={11} fontWeight={600} fill="#12935f">
        Aligned
      </text>

      {/* Y-axis ticks */}
      {ticks.map((t) => (
        <text key={t} x={4} y={y(t) + 4} fontSize={11} fontWeight={500} fill="#92a0bf">
          +{t} h
        </text>
      ))}

      {/* Trend Line */}
      <path d={pathD} fill="none" stroke="#0a1b4d" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />

      {/* Highlighted Endpoint Dot */}
      {data.length > 0 && (
        <circle
          cx={x(lastIdx)}
          cy={y(data[lastIdx].shift_hours)}
          r={5}
          fill="#fff"
          stroke="#fc3d21"
          strokeWidth={2.5}
        />
      )}

      {/* X-axis Labels */}
      <text x={x(0)} y={H - 8} fontSize={11} fontWeight={500} fill="#92a0bf" textAnchor="start">
        Day {data[0].day}
      </text>
      <text x={x(midIdx)} y={H - 8} fontSize={11} fontWeight={500} fill="#92a0bf" textAnchor="middle">
        Day {data[midIdx].day}
      </text>
      <text x={x(lastIdx)} y={H - 8} fontSize={11} fontWeight={600} fill="#92a0bf" textAnchor="end">
        Today
      </text>
    </svg>
  );
}
