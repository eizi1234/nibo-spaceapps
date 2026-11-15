"use client";

import { useEffect, useState } from "react";
import GateBadge from "@/components/GateBadge";
import { api, ApiError } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { ReadinessGate } from "@/types/astronaut";
import type { OverviewResponse } from "@/types/crew";

const FEATURE_LABEL: Record<string, string> = {
  sleep_debt_hours: "Sleep debt",
  schedule_shift_minutes: "Schedule shift",
  hrv_rmssd_ms: "Heart rate variability",
  resting_hr_bpm: "Resting heart rate",
};

const GATE_MESSAGE: Record<ReadinessGate, string> = {
  GO: "You are ready for critical tasks.",
  CAUTION: "Take care with demanding tasks today.",
  HOLD: "Avoid critical tasks for now.",
};

const CARD = "rounded-3xl bg-white/90 p-5 shadow-sm";

export default function OverviewPage() {
  const { user, scenario, day } = useDashboard();
  const [data, setData] = useState<OverviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .overview({ scenario, day })
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Something went wrong.");
      });
    return () => {
      cancelled = true;
    };
  }, [scenario, day]);

  if (error) {
    return (
      <p role="alert" className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">
        {error}
      </p>
    );
  }
  if (!data) return <p className="text-sm text-slate-500">Loading overview</p>;

  const stale = data.scenario !== scenario || data.day !== day;
  const features = data.prediction.cognitive_stress.top_features;
  const total = features.reduce((sum, f) => sum + f.impact, 0) || 1;

  return (
    <div className={`space-y-4 transition-opacity ${stale ? "opacity-60" : ""}`}>
      <header>
        <p className="text-sm text-slate-500">Good morning, {user.name}</p>
        <h1 className="text-3xl font-bold text-[#0a1b4d]">Overview</h1>
      </header>

      <div className="grid gap-4 md:grid-cols-3">
        <section className="rounded-3xl bg-[#1d4fc4] p-5 text-white shadow-sm" aria-label="Readiness today">
          <p className="text-sm text-white/80">Readiness today</p>
          <div className="mt-2 flex items-end gap-2">
            <span className="text-6xl font-bold leading-none">{Math.round(data.readiness_score)}</span>
            <span className="pb-1 text-sm text-white/70">of 100</span>
          </div>
          <div className="mt-3">
            <GateBadge gate={data.readiness_gate} />
          </div>
          <p className="mt-3 text-sm text-white/85">{GATE_MESSAGE[data.readiness_gate]}</p>
          <p className="mt-2 text-xs text-white/60">
            GO from {data.thresholds.go} · CAUTION from {data.thresholds.caution}
          </p>
        </section>

        <section className={`${CARD} bg-[#e6f23d]/80`} aria-label="Daily check-in">
          <p className="text-sm text-[#0a1b4d]/70">Daily check-in</p>
          <p className="mt-2 text-xl font-bold text-[#0a1b4d]">
            {data.checkin_done ? "Done today" : "Not done yet today"}
          </p>
          <p className="mt-1 text-sm text-[#0a1b4d]/70">
            {data.checkin_done
              ? "Your answers are included in the score."
              : "About 4 minutes: reaction test first, then 3 questions."}
          </p>
        </section>

        <section className={CARD} aria-label="Next critical activity">
          <p className="text-sm text-slate-500">Next critical activity</p>
          {data.next_critical_task ? (
            <>
              <p className="mt-2 text-xl font-bold text-[#0a1b4d]">{data.next_critical_task.name}</p>
              <p className="mt-1 text-sm text-slate-500">
                {data.next_critical_task.when_label} · needs score {data.next_critical_task.needs_score}
              </p>
              <div className="mt-3">
                <GateBadge gate={data.next_critical_task.status} />
              </div>
            </>
          ) : (
            <p className="mt-2 text-sm text-slate-500">No critical activity planned.</p>
          )}
        </section>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className={CARD} aria-label="Why this status">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-[#0a1b4d]">Why this status</h2>
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-600">
              Model confidence {Math.round(data.prediction.cognitive_stress.confidence * 100)}%
            </span>
          </div>
          <ul className="mt-4 space-y-3">
            {features.map((f) => {
              const pct = Math.round((f.impact / total) * 100);
              return (
                <li key={f.name}>
                  <div className="flex justify-between text-sm">
                    <span className="text-slate-700">{FEATURE_LABEL[f.name] ?? f.name}</span>
                    <span className="font-semibold text-[#0a1b4d]">{pct}%</span>
                  </div>
                  <div className="mt-1 h-2 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-[#1f56d6]" style={{ width: `${pct}%` }} />
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="mt-4 text-xs text-slate-400">Share of the risk score from each factor.</p>
        </section>

        <section className={CARD} aria-label="Sleep, last 7 days">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-[#0a1b4d]">Sleep, last 7 days</h2>
            <span className="text-xs text-slate-500">Recommended {data.baseline.sleep_hours} h</span>
          </div>
          <div className="mt-4 flex h-40 items-end gap-2">
            {data.sleep_7d.map((d) => (
              <div key={d.day} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
                <span className="text-xs font-medium text-slate-600">{d.hours.toFixed(1)}</span>
                <div
                  className={`w-full rounded-lg ${d.hours < 6 ? "bg-orange-400" : "bg-[#1f56d6]"}`}
                  style={{ height: `${Math.min(100, (d.hours / 9) * 100) * 0.75}%` }}
                />
                <span className="text-[10px] text-slate-400">
                  {d.label === "Last night" ? "Last" : d.label.replace("Day ", "D")}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className={CARD} aria-label="Your tasks">
          <h2 className="font-semibold text-[#0a1b4d]">Your tasks</h2>
          {data.tasks.length === 0 ? (
            <p className="mt-3 text-sm text-slate-500">No tasks assigned.</p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {data.tasks.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-800">{t.name}</p>
                    <p className="text-xs text-slate-500">
                      {t.when_label} · needs {t.needs_score}
                    </p>
                  </div>
                  <GateBadge gate={t.status} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className={CARD} aria-label="What you can do today">
          <h2 className="font-semibold text-[#0a1b4d]">What you can do today</h2>
          <ul className="mt-3 space-y-2">
            {data.recommended_actions.map((a) => (
              <li key={a} className="rounded-xl bg-[#eaf1fd] px-3 py-2.5 text-sm text-slate-700">
                {a}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
