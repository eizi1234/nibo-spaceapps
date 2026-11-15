"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import GateBadge from "@/components/GateBadge";
import Icon from "@/components/Icon";
import type { IconName } from "@/components/Icon";
import { api, ApiError } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { ReadinessGate } from "@/types/astronaut";
import type { OverviewResponse } from "@/types/crew";

const CARD = "glass-card rounded-[24px] p-6";

const FEATURE_META: Record<string, { label: string; icon: IconName; sub: string }> = {
  sleep_debt_hours: {
    label: "Sleep debt",
    icon: "moon",
    sub: "Accumulated sleep deficit",
  },
  schedule_shift_minutes: {
    label: "Schedule shift",
    icon: "clock",
    sub: "Circadian phase offset",
  },
  hrv_rmssd_ms: {
    label: "Heart rate variability",
    icon: "sun",
    sub: "Autonomic recovery index",
  },
  resting_hr_bpm: {
    label: "Resting heart rate",
    icon: "info-circle",
    sub: "Baseline cardiovascular load",
  },
};

const GATE_MESSAGE: Record<ReadinessGate, string> = {
  GO: "All biometrics aligned. Ready for critical tasks.",
  CAUTION: "Mild fatigue detected. Pace demanding tasks today.",
  HOLD: "High fatigue risk. Avoid critical tasks for now.",
};

const RING_STROKE: Record<ReadinessGate, string> = {
  GO: "#22c55e",
  CAUTION: "#f59e0b",
  HOLD: "#e6f23d",
};

const ACTION_ICONS: IconName[] = ["moon", "clock", "refresh", "info-circle"];

function splitActionText(text: string): { title: string; subtitle: string } {
  const colonIdx = text.indexOf(":");

  if (colonIdx > 0 && colonIdx < 36) {
    return {
      title: text.slice(0, colonIdx).trim(),
      subtitle: text.slice(colonIdx + 1).trim(),
    };
  }

  const dotIdx = text.indexOf(".");

  if (dotIdx > 0 && dotIdx < 40) {
    return {
      title: text.slice(0, dotIdx).trim(),
      subtitle: text.slice(dotIdx + 1).trim() || "Recommended daily countermeasure",
    };
  }

  return {
    title: text,
    subtitle: "Recommended daily recovery action",
  };
}

export default function OverviewPage() {
  const { user, scenario, day } = useDashboard();

  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [doneActions, setDoneActions] = useState<Record<number, boolean>>({});
  const [showCheckinModal, setShowCheckinModal] = useState(false);
  const [wakeUpText, setWakeUpText] = useState(
    "You woke up an hour ago, so the test now gives a fair result.",
  );

  useEffect(() => {
    let cancelled = false;

    setDoneActions({});

    api
      .overview({ scenario, day })
      .then((d) => {
        if (cancelled) return;

        setData(d);
        setError(null);

        try {
          const now = new Date();
          const wakeHour = 6;
          const wakeMinute = 30;
          const wakeDate = new Date(now);

          wakeDate.setHours(wakeHour, wakeMinute, 0, 0);

          const diffMinutes = Math.round(
            (now.getTime() - wakeDate.getTime()) / (1000 * 60),
          );

          if (diffMinutes >= 30 && diffMinutes <= 90) {
            setWakeUpText(
              "You woke up an hour ago, so the test now gives a fair result.",
            );
          } else if (diffMinutes > 90) {
            const hoursAgo = Math.round(diffMinutes / 60);
            setWakeUpText(
              `You woke up about ${hoursAgo} hours ago, so the test now gives a fair result.`,
            );
          } else if (diffMinutes > 0) {
            setWakeUpText(`You woke up ${diffMinutes} minutes ago.`);
          } else {
            setWakeUpText(
              "You woke up recently, so the test now gives a fair result.",
            );
          }
        } catch {
          setWakeUpText(
            "You woke up an hour ago, so the test now gives a fair result.",
          );
        }

        if (!d.checkin_done) {
          setShowCheckinModal(true);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(
            e instanceof ApiError ? e.message : "Something went wrong.",
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, [scenario, day]);

  if (error) {
    return (
      <p role="alert" className="rounded-2xl bg-hold-bg p-4 text-sm text-hold">
        {error}
      </p>
    );
  }

  if (!data) {
    return <p className="text-sm text-ink-secondary">Loading overview...</p>;
  }

  const stale = data.scenario !== scenario || data.day !== day;
  const score = Math.round(data.readiness_score);
  const features = data.prediction.cognitive_stress.top_features;
  const total = features.reduce((sum, f) => sum + f.impact, 0) || 1;
  const recHours = data.baseline.sleep_hours || 7;

  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const dashOffset =
    circumference - (Math.min(100, Math.max(0, score)) / 100) * circumference;

  const actions = data.recommended_actions.slice(0, 4);
  const completedCount = actions.filter((_, idx) => doneActions[idx]).length;

  return (
    <div
      className={`space-y-5 transition-opacity ${
        stale ? "opacity-60" : ""
      }`}
    >
      <header className="flex flex-col gap-0.5">
        <p className="text-[13px] font-medium text-ink-secondary">
          Good morning, {user.name}
        </p>
        <h1 className="text-[28px] font-bold leading-[1.2] tracking-[-0.42px] text-ink">
          Overview
        </h1>
      </header>

      {/* Top Row: 3 Cards */}
      <div className="grid gap-5 lg:grid-cols-3">
        {/* 1. Readiness Today */}
        <section
          className="brand-glow relative flex flex-col justify-between overflow-hidden rounded-[24px] p-6 text-white"
          aria-label="Readiness today"
        >
          <div className="flex items-center justify-between gap-4">
            <div className="space-y-2.5">
              <p className="text-[13px] font-medium text-white/85">
                Readiness today
              </p>
              <GateBadge gate={data.readiness_gate} tone="white" />
              <p className="max-w-[180px] text-xs leading-relaxed text-white/90">
                {GATE_MESSAGE[data.readiness_gate]}
              </p>
            </div>

            <div className="relative flex size-[112px] shrink-0 items-center justify-center">
              <svg className="-rotate-90 size-full" viewBox="0 0 104 104">
                <circle
                  cx="52"
                  cy="52"
                  r={radius}
                  fill="none"
                  stroke="rgba(255,255,255,0.18)"
                  strokeWidth="9"
                />
                <circle
                  cx="52"
                  cy="52"
                  r={radius}
                  fill="none"
                  stroke={RING_STROKE[data.readiness_gate]}
                  strokeWidth="9"
                  strokeLinecap="round"
                  strokeDasharray={circumference}
                  strokeDashoffset={dashOffset}
                />
              </svg>

              <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                <span className="text-[30px] font-extrabold leading-none tracking-tight">
                  {score}
                </span>
                <span className="mt-0.5 text-[11px] font-medium text-white/75">
                  of 100
                </span>
              </div>
            </div>
          </div>

          <p className="mt-4 text-[11px] font-medium text-white/70">
            GO from {data.thresholds.go} · CAUTION from{" "}
            {data.thresholds.caution}
          </p>
        </section>

        {/* 2. Daily Check-in Card */}
        <section
          className="accent-glow relative flex flex-col justify-between overflow-hidden rounded-[24px] p-6"
          aria-label="Daily check-in"
        >
          <div>
            <div className="flex items-center gap-2.5">
              <span className="flex size-8 items-center justify-center rounded-full bg-[#0a1b4d] text-[#e6f23d]">
                <svg className="size-4 fill-current" viewBox="0 0 24 24">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              </span>
              <p className="text-[13px] font-semibold text-on-accent">
                Daily check-in
              </p>
            </div>

            <p className="mt-3 text-xl font-bold text-on-accent">
              {data.checkin_done ? "Done today" : "Not done yet today"}
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-on-accent/80">
              {data.checkin_done
                ? "Your reaction & symptom answers are included in today's score."
                : "About 4 minutes: reaction test first, then 3 questions."}
            </p>
          </div>

          <div className="mt-4">
            <Link
              href="/dashboard/checkin"
              className="inline-flex items-center gap-1.5 rounded-full bg-[#0b3d91] px-4 py-2 text-xs font-bold text-white shadow-sm transition hover:brightness-110"
            >
              {data.checkin_done ? "View check-in >" : "Start check-in >"}
            </Link>
          </div>
        </section>

        {/* 3. Next Critical Activity */}
        <section
          className={`${CARD} flex flex-col justify-between`}
          aria-label="Next critical activity"
        >
          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="flex size-7 items-center justify-center rounded-full bg-soft text-brand">
                  <Icon name="sun" />
                </span>
                <p className="text-[13px] font-medium text-ink-secondary">
                  Next critical activity
                </p>
              </div>
              {data.next_critical_task && (
                <GateBadge gate={data.next_critical_task.status} />
              )}
            </div>

            {data.next_critical_task ? (
              <>
                <p className="mt-3 text-lg font-bold text-ink">
                  {data.next_critical_task.name}
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  {data.next_critical_task.when_label} · needs score{" "}
                  {data.next_critical_task.needs_score}
                </p>
              </>
            ) : (
              <p className="mt-3 text-sm text-ink-muted">
                No critical activity planned.
              </p>
            )}
          </div>

          <div className="mt-4">
            <Link
              href={
                user.role === "commander"
                  ? "/dashboard/crew-mission"
                  : "/dashboard/sleep"
              }
              className="inline-flex items-center rounded-full border border-slate-200 bg-white px-4 py-1.5 text-xs font-semibold text-ink transition hover:bg-slate-50"
            >
              See details &gt;
            </Link>
          </div>
        </section>
      </div>

      {/* Middle Row */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* 4. Why This Status */}
        <section className={CARD} aria-label="Why this status">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-ink">
              Why this status
            </h2>
            <span className="rounded-full bg-soft px-3 py-1 text-xs font-medium text-ink-muted">
              Model confidence{" "}
              {Math.round(
                data.prediction.cognitive_stress.confidence * 100,
              )}
              %
            </span>
          </div>

          <ul className="mt-5 space-y-4">
            {features.map((f) => {
              const pct = Math.round((f.impact / total) * 100);
              const meta = FEATURE_META[f.name] ?? {
                label: f.name,
                icon: "info-circle" as IconName,
                sub: "",
              };
              const barColor =
                pct >= 35
                  ? "bg-hold"
                  : pct >= 15
                    ? "bg-caution"
                    : "bg-[#f59e0b]";
              const textColor = pct >= 35 ? "text-hold" : "text-caution";

              return (
                <li key={f.name} className="flex items-center gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-soft text-brand">
                    <Icon name={meta.icon} />
                  </span>

                  <div className="min-w-[130px]">
                    <p className="text-[13px] font-semibold leading-tight text-ink">
                      {meta.label}
                    </p>
                    {meta.sub && (
                      <p className="text-[11px] text-ink-muted">{meta.sub}</p>
                    )}
                  </div>

                  <div className="h-2 flex-1 rounded-full bg-slate-100">
                    <div
                      className={`h-2 rounded-full ${barColor}`}
                      style={{ width: `${Math.min(100, pct * 2)}%` }}
                    />
                  </div>

                  <span
                    className={`w-10 text-right text-xs font-bold ${textColor}`}
                  >
                    {pct}%
                  </span>
                </li>
              );
            })}
          </ul>

          <p className="mt-5 flex items-center gap-1.5 text-xs text-ink-muted">
            <Icon name="info-circle" />
            <span>
              Share of the risk score from each factor, explained by the model.
            </span>
          </p>
        </section>

        {/* 5. Sleep, Last 7 Days */}
        <section className={CARD} aria-label="Sleep, last 7 days">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-base font-semibold text-ink">
              Sleep, last 7 days
            </h2>
            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5 text-ink-muted">
                <span className="inline-block size-2.5 rounded-sm bg-[#0b3d91]" />
                1 block = 1 hour
              </span>
              <span className="rounded-full bg-soft px-2.5 py-0.5 font-semibold text-brand">
                Recommended {recHours} h
              </span>
            </div>
          </div>

          <div className="relative mt-6">
            <div
              className="pointer-events-none absolute inset-x-0 border-t border-dashed border-brand/40"
              style={{ bottom: `${(recHours / 8) * 140 + 24}px` }}
            />

            <div className="grid grid-cols-7 gap-2.5 pt-4">
              {data.sleep_7d.map((d) => {
                const filledBlocks = Math.min(8, Math.round(d.hours));
                const isLow = d.hours < recHours - 1.2;
                const badgeBg = isLow
                  ? "bg-hold text-white"
                  : "bg-[#0a1b4d] text-white";
                const dayName =
                  d.label === "Last night"
                    ? "Today"
                    : d.label.replace("Day ", "D");

                return (
                  <div
                    key={d.day}
                    className="flex flex-col items-center gap-1.5"
                  >
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-bold shadow-xs ${badgeBg}`}
                    >
                      {d.hours.toFixed(1)}h
                    </span>

                    <div className="flex w-full max-w-[38px] flex-col-reverse gap-1">
                      {Array.from({ length: 8 }).map((_, idx) => {
                        const active = idx < filledBlocks;

                        return (
                          <div
                            key={idx}
                            className={`h-2.5 w-full rounded-full transition-colors ${
                              active
                                ? "bg-slate-200/90"
                                : "bg-slate-100/50"
                            }`}
                          />
                        );
                      })}
                    </div>

                    <span className="mt-1 text-[11px] font-medium text-ink-muted">
                      {dayName}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      </div>

      {/* Bottom Row */}
      <section className={CARD} aria-label="What you can do today">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-ink">
            What you can do today
          </h2>
          <span className="text-xs font-medium text-ink-muted">
            {completedCount} of {actions.length} done
          </span>
        </div>

        <div className="mt-4 grid gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
          {actions.map((actionText, idx) => {
            const { title, subtitle } = splitActionText(actionText);
            const isDone = !!doneActions[idx];
            const iconName = ACTION_ICONS[idx % ACTION_ICONS.length];

            return (
              <button
                key={actionText}
                type="button"
                onClick={() =>
                  setDoneActions((prev) => ({
                    ...prev,
                    [idx]: !prev[idx],
                  }))
                }
                className={`flex flex-col justify-between rounded-2xl border p-4 text-left transition ${
                  isDone
                    ? "border-emerald-200 bg-emerald-50/70"
                    : "border-slate-100 bg-[#f6f9ff] hover:border-brand/30"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="flex size-9 items-center justify-center rounded-full bg-white text-brand shadow-2xs">
                      <Icon name={iconName} />
                    </span>

                    <span
                      className={`flex size-6 items-center justify-center rounded-full border text-xs font-bold transition ${
                        isDone
                          ? "border-emerald-600 bg-emerald-600 text-white"
                          : "border-slate-300 bg-white text-transparent"
                      }`}
                    >
                      ✓
                    </span>
                  </div>

                  <p className="mt-3 text-[13px] font-bold leading-snug text-ink">
                    {title}
                  </p>
                  <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                    {subtitle}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* Daily check-in reminder modal */}
      {showCheckinModal && !data.checkin_done && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#0a1a3a]/45 p-4 backdrop-blur-[2px]"
          onClick={() => setShowCheckinModal(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="checkin-modal-title"
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-[500px] overflow-hidden rounded-[32px] bg-white text-center shadow-[0_24px_54px_-12px_rgba(10,43,115,0.35)]"
          >
            {/* Blue top section */}
            <div className="relative flex h-[105px] items-center justify-center bg-gradient-to-br from-[#3978e3] via-[#2160c5] to-[#0b3d91]">
              <button
                type="button"
                aria-label="Close reminder"
                onClick={() => setShowCheckinModal(false)}
                className="absolute right-4 top-4 flex size-8 items-center justify-center rounded-full bg-white/15 text-white transition hover:bg-white/25"
              >
                ✕
              </button>

              {/* Check-in icon */}
              <div className="flex size-[60px] items-center justify-center rounded-full bg-[#e6f23d] text-[#0a1b4d] shadow-sm">
                <svg
                  aria-hidden="true"
                  className="size-7"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <rect
                    x="6"
                    y="5"
                    width="12"
                    height="16"
                    rx="2"
                    fill="currentColor"
                    opacity=".18"
                  />
                  <path
                    d="M9 5.5h6a1 1 0 0 1 1 1V8H8V6.5a1 1 0 0 1 1-1Z"
                    fill="currentColor"
                  />
                  <path
                    d="m9.5 14 1.7 1.7 3.5-3.7"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
            </div>

            <div className="px-6 pb-6 pt-5 sm:px-7">
              <h2
                id="checkin-modal-title"
                className="text-[22px] font-extrabold tracking-tight text-ink"
              >
                Time for your daily check-in
              </h2>
              <p className="mt-1.5 text-xs font-normal leading-relaxed text-ink-muted">
                {wakeUpText}
              </p>

              {/* Three check-in steps */}
              <div className="mt-5 grid grid-cols-3 gap-2 rounded-[24px] bg-[#eef4ff] p-3 sm:gap-3 sm:p-4">
                {[
                  {
                    step: "Step 1",
                    label: "Reaction test",
                    duration: "3 min",
                    icon: (
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 24 24"
                        className="size-5"
                      >
                        <path
                          d="M8 3h8M8 21h8M9 4c0 4 6 4 6 8s-6 4-6 8m6-16c0 4-6 4-6 8s6 4 6 8"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                        />
                      </svg>
                    ),
                  },
                  {
                    step: "Step 2",
                    label: "3 questions",
                    duration: "1 min",
                    icon: (
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 24 24"
                        className="size-5"
                      >
                        <rect
                          x="4"
                          y="5"
                          width="16"
                          height="16"
                          rx="2"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                        />
                        <path
                          d="M8 3v4M16 3v4M4 10h16M8 14h2M8 17h2M14 14h2"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                        />
                      </svg>
                    ),
                  },
                  {
                    step: "Step 3",
                    label: "Result & status",
                    duration: "Auto",
                    icon: (
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 24 24"
                        className="size-5"
                      >
                        <path
                          d="M12 20s-8-4.7-8-10.2A4.3 4.3 0 0 1 12 7.5a4.3 4.3 0 0 1 8 2.3C20 15.3 12 20 12 20Z"
                          fill="currentColor"
                        />
                      </svg>
                    ),
                  },
                ].map((item) => (
                  <div
                    key={item.step}
                    className="flex min-w-0 flex-col items-center rounded-[20px] bg-white px-2 py-3 shadow-2xs sm:px-3.5"
                  >
                    <p className="text-xs font-bold text-ink">{item.step}</p>
                    <span className="mt-2 flex size-8 items-center justify-center rounded-full bg-[#f0f5ff] text-[#0b3d91]">
                      {item.icon}
                    </span>
                    <p className="mt-1.5 text-[10px] leading-tight text-ink-muted sm:text-[11px]">
                      {item.label}
                    </p>
                    <p className="mt-1 text-xs font-extrabold text-[#0b3d91]">
                      {item.duration}
                    </p>
                  </div>
                ))}
              </div>

              {/* Action button */}
              <div className="mt-5">
                <Link
                  href="/dashboard/checkin"
                  onClick={() => setShowCheckinModal(false)}
                  className="flex w-full items-center justify-center rounded-full bg-gradient-to-r from-[#3978e3] to-[#0b3d91] py-3.5 text-xs font-bold text-white shadow-[0_8px_18px_rgba(11,61,145,0.3)] transition hover:brightness-110"
                >
                  Take the test &gt;
                </Link>
              </div>

              {/* Remind button */}
              <button
                type="button"
                onClick={() => setShowCheckinModal(false)}
                className="mt-4 text-xs font-medium text-ink-muted transition hover:text-ink"
              >
                Remind me in 15 min
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}