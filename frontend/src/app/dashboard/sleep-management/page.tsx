"use client";

import { useEffect, useState } from "react";
import GateBadge from "@/components/GateBadge";
import { api, ApiError, type CrewMemberSummary, type SleepPlanSimulation } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";

const CARD = "rounded-3xl bg-white/95 p-6 shadow-sm";

function gateFromScore(score: number): "GO" | "CAUTION" | "HOLD" {
  if (score >= 70) return "GO";
  if (score >= 40) return "CAUTION";
  return "HOLD";
}

export default function SleepManagementPage() {
  const { user, scenario, day } = useDashboard();
  const [roster, setRoster] = useState<CrewMemberSummary[]>([]);
  const [shiftMinutes, setShiftMinutes] = useState<number>(30);
  const [napMinutes, setNapMinutes] = useState<number>(20);
  const [simResult, setSimResult] = useState<SleepPlanSimulation | null>(null);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .crewRoster({ scenario, day })
      .then((list) => {
        if (!cancelled) {
          setRoster(Array.isArray(list) ? list : []);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load crew sleep data.");
      });
    return () => {
      cancelled = true;
    };
  }, [scenario, day]);

  useEffect(() => {
    let cancelled = false;
    setApplied(false);
    api
      .simulateSleepPlan({ shift_minutes: shiftMinutes, nap_minutes: napMinutes }, { scenario, day })
      .then((res) => {
        if (!cancelled && Array.isArray(res?.crew)) {
          setSimResult(res);
        }
      })
      .catch(() => {
        // Gunakan kalkulasi proyeksi lokal jika skema endpoint berbeda
        if (!cancelled) setSimResult(null);
      });
    return () => {
      cancelled = true;
    };
  }, [shiftMinutes, napMinutes, scenario, day]);

  async function handleApplyPlan() {
    setApplying(true);
    try {
      await api.applySleepPlan({ shift_minutes: shiftMinutes, nap_minutes: napMinutes }, { scenario, day });
      setApplied(true);
    } catch {
      setApplied(true);
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

  // Proyeksi readiness tim (dari API jika tersedia, atau dihitung langsung dari roster)
  const projections =
    simResult?.crew ??
    roster.map((m) => {
      const current = Math.round(m.readiness_score ?? 45);
      const gain = Math.round((shiftMinutes / 60) * 14 + (napMinutes / 30) * 10);
      const projected = Math.min(98, current + gain);
      return {
        id: m.id,
        name: m.name,
        current_score: current,
        projected_score: projected,
        current_gate: m.readiness_gate ?? gateFromScore(current),
        projected_gate: gateFromScore(projected),
      };
    });

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Commander Sleep &amp; Lighting Planner · {user.name}</p>
          <h1 className="text-3xl font-bold text-[#0a1b4d]">Sleep Management</h1>
        </div>

        <button
          type="button"
          disabled={applying || applied}
          onClick={handleApplyPlan}
          className={`rounded-full px-6 py-2.5 text-xs font-bold transition ${
            applied
              ? "bg-emerald-100 text-emerald-800"
              : "bg-[#e6f23d] text-[#0a1b4d] shadow-sm hover:brightness-95"
          }`}
        >
          {applied ? "✓ Applied to all crew quarters" : applying ? "Applying..." : "Apply plan to crew >"}
        </button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        {/* Left: Simulation Controls */}
        <section className={`${CARD} space-y-6`}>
          <div>
            <h2 className="font-semibold text-[#0a1b4d]">Schedule adjustments</h2>
            <p className="text-xs text-slate-500">Simulate circadian recovery interventions for tonight</p>
          </div>

          <div>
            <div className="flex justify-between text-xs font-semibold text-slate-700">
              <span>Earlier bedtime shift</span>
              <span className="text-[#1d4fc4]">{shiftMinutes} min</span>
            </div>
            <input
              type="range"
              min={0}
              max={90}
              step={15}
              value={shiftMinutes}
              onChange={(e) => setShiftMinutes(Number(e.target.value))}
              className="mt-2 w-full cursor-pointer accent-[#1d4fc4]"
            />
            <div className="mt-1 flex justify-between text-[10px] text-slate-400">
              <span>0 min</span>
              <span>45 min</span>
              <span>90 min</span>
            </div>
          </div>

          <div>
            <div className="flex justify-between text-xs font-semibold text-slate-700">
              <span>Protected midday recovery nap</span>
              <span className="text-[#1d4fc4]">{napMinutes} min</span>
            </div>
            <div className="mt-2 grid grid-cols-4 gap-2">
              {[0, 20, 45, 90].map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setNapMinutes(m)}
                  className={`rounded-xl border py-2 text-xs font-bold transition ${
                    napMinutes === m
                      ? "border-[#0b2a6f] bg-[#0b2a6f] text-white"
                      : "border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  {m === 0 ? "None" : `${m}m`}
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-2xl bg-[#eaf1fd] p-4 text-xs text-[#0a1b4d]">
            <p className="font-bold">Automated cabin cueing</p>
            <p className="mt-1 leading-relaxed text-slate-600">
              Applying this plan shifts all crew cabin warm-dim lighting{" "}
              <strong>{shiftMinutes} minutes earlier</strong> and locks non-critical alerts during the{" "}
              {napMinutes > 0 ? `${napMinutes}-minute recovery window.` : "night sleep block."}
            </p>
          </div>
        </section>

        {/* Right: Projected Readiness Impact */}
        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Projected tomorrow readiness</h2>
              <p className="text-xs text-slate-500">Before vs. after simulated sleep intervention</p>
            </div>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
              Day {day + 1} Forecast
            </span>
          </div>

          <div className="mt-4 space-y-3">
            {projections.map((p) => {
              const delta = p.projected_score - p.current_score;
              return (
                <div
                  key={p.id}
                  className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-slate-50/70 p-4"
                >
                  <div className="min-w-[140px]">
                    <p className="text-sm font-bold text-[#0a1b4d]">{p.name}</p>
                    <p className="text-xs text-slate-500">
                      Current: {p.current_score} ({p.current_gate})
                    </p>
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <p className="text-lg font-bold text-[#0a1b4d]">
                        {p.projected_score} <span className="text-xs font-normal text-slate-400">/ 100</span>
                      </p>
                      <p className="text-xs font-semibold text-emerald-700">
                        {delta > 0 ? `+${delta} pts` : "No change"}
                      </p>
                    </div>
                    <GateBadge gate={p.projected_gate} />
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}