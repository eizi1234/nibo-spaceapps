"use client";

import { useEffect, useState } from "react";
import GateBadge from "@/components/GateBadge";
import {
  api,
  ApiError,
  type CrewMemberSummary,
  type TaskSwapSuggestion,
} from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { RestRequest } from "@/types/crew";

const CARD = "rounded-3xl bg-white/95 p-6 shadow-sm";

export default function CrewMissionPage() {
  const { user, scenario, day } = useDashboard();
  const [crew, setCrew] = useState<CrewMemberSummary[]>([]);
  const [swaps, setSwaps] = useState<TaskSwapSuggestion[]>([]);
  const [requests, setRequests] = useState<RestRequest[]>([]);
  const [appliedSwaps, setAppliedSwaps] = useState<Record<string, boolean>>({});
  const [decidedReqs, setDecidedReqs] = useState<Record<string, "approved" | "declined">>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const ctx = { scenario, day };
    setLoading(true);

    Promise.all([
      api.crewRoster(ctx).catch(() => []),
      api.crewSwaps(ctx).catch(() => []),
      api.restRequests(ctx).catch(() => []),
    ])
      .then(([roster, swapList, reqList]) => {
        if (cancelled) return;
        setCrew(Array.isArray(roster) ? roster : []);
        setSwaps(Array.isArray(swapList) ? swapList : []);
        setRequests(Array.isArray(reqList) ? reqList : []);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load crew mission data.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [scenario, day]);

  async function handleApproveSwap(swapId: string) {
    setAppliedSwaps((prev) => ({ ...prev, [swapId]: true }));
    try {
      await api.applySwap(swapId, { scenario, day });
    } catch {
      // Pertahankan feedback UI lokal
    }
  }

  async function handleDecision(rid: string, decision: "approved" | "declined") {
    setDecidedReqs((prev) => ({ ...prev, [rid]: decision }));
    try {
      await api.decideRestRequest(rid, decision, { scenario, day });
    } catch {
      // Pertahankan feedback UI lokal
    }
  }

  if (error) {
    return (
      <p role="alert" className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">
        {error}
      </p>
    );
  }

  if (loading) {
    return <p className="text-sm text-slate-500">Loading crew readiness &amp; mission tasks...</p>;
  }

  const goCount = crew.filter((c) => c.readiness_gate === "GO").length;
  const avgReadiness =
    crew.length > 0
      ? Math.round(crew.reduce((acc, c) => acc + (c.readiness_score ?? 0), 0) / crew.length)
      : 0;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm text-slate-500">Commander Operations · {user.name}</p>
          <h1 className="text-3xl font-bold text-[#0a1b4d]">Crew Mission</h1>
        </div>
        <div className="flex gap-2">
          <span className="rounded-full bg-white px-4 py-1.5 text-xs font-semibold text-[#0a1b4d] shadow-sm">
            Team Avg: <strong>{avgReadiness}%</strong>
          </span>
          <span className="rounded-full bg-emerald-100 px-4 py-1.5 text-xs font-semibold text-emerald-800">
            {goCount} / {crew.length || 4} Crew GO
          </span>
        </div>
      </header>

      {/* Crew Roster Cards */}
      <section className={CARD}>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-[#0a1b4d]">Crew readiness overview</h2>
            <p className="text-xs text-slate-500">Real-time cognitive &amp; circadian status across all crew members</p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {crew.map((member) => {
            const score = Math.round(member.readiness_score ?? 0);
            const debt = member.sleep_debt_hours ?? 0;
            return (
              <div
                key={member.id}
                className="flex flex-col justify-between rounded-2xl border border-slate-100 bg-slate-50/80 p-4"
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-bold text-[#0a1b4d]">{member.name}</span>
                    <GateBadge gate={member.readiness_gate ?? "CAUTION"} />
                  </div>
                  <p className="text-xs text-slate-500">{member.title}</p>

                  <div className="mt-4 flex items-baseline gap-1.5">
                    <span className="text-3xl font-bold text-[#0a1b4d]">{score}</span>
                    <span className="text-xs text-slate-400">/ 100</span>
                  </div>
                </div>

                <div className="mt-4 space-y-1 border-t border-slate-200/70 pt-3 text-xs text-slate-600">
                  <div className="flex justify-between">
                    <span>Sleep debt</span>
                    <strong className={debt > 2 ? "text-orange-600" : "text-slate-800"}>
                      {debt.toFixed(1)} h
                    </strong>
                  </div>
                  <div className="flex justify-between">
                    <span>Daily check-in</span>
                    <strong>{member.checkin_done ? "Done" : "Pending"}</strong>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Bottom Grid: AI Task Swap & Rest Requests */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Task Swap Suggestions */}
        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Recommended task swaps</h2>
              <p className="text-xs text-slate-500">Reassign critical duties from fatigued crew members</p>
            </div>
            <span className="rounded-full bg-[#eaf1fd] px-3 py-1 text-xs font-semibold text-[#1d4fc4]">
              AI Scheduler
            </span>
          </div>

          {swaps.length === 0 ? (
            <p className="mt-4 rounded-2xl bg-slate-50 p-4 text-xs text-slate-500">
              No task swaps needed under current readiness levels.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {swaps.map((s) => {
                const isApplied = appliedSwaps[s.id] || s.applied;
                return (
                  <div
                    key={s.id}
                    className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4 text-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="font-bold text-[#0a1b4d]">{s.task_name}</p>
                        <p className="text-xs text-slate-500">{s.when_label}</p>
                      </div>
                      <button
                        type="button"
                        disabled={isApplied}
                        onClick={() => handleApproveSwap(s.id)}
                        className={`rounded-full px-4 py-1.5 text-xs font-bold transition ${
                          isApplied
                            ? "bg-emerald-100 text-emerald-800"
                            : "bg-[#e6f23d] text-[#0a1b4d] hover:brightness-95"
                        }`}
                      >
                        {isApplied ? "✓ Swapped" : "Approve swap"}
                      </button>
                    </div>
                    <p className="mt-2 text-xs text-slate-700">
                      Move from <strong>{s.from_user_name}</strong> → <strong>{s.to_user_name}</strong>
                    </p>
                    <p className="mt-1 text-xs text-slate-500">{s.reason}</p>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        {/* Rest Requests Inbox */}
        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Crew rest requests</h2>
              <p className="text-xs text-slate-500">Review recovery &amp; schedule change submissions</p>
            </div>
          </div>

          {requests.length === 0 ? (
            <p className="mt-4 rounded-2xl bg-slate-50 p-4 text-xs text-slate-500">
              No pending rest requests from the crew today.
            </p>
          ) : (
            <div className="mt-4 space-y-3">
              {requests.map((r) => {
                const status: RestRequest["status"] = decidedReqs[r.id] ?? r.status;
                return (
                  <div
                    key={r.id}
                    className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4 text-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <p className="font-bold text-[#0a1b4d]">
                          {r.requester_name ?? r.requester_id} ·{" "}
                          <span className="font-medium text-slate-600">
                            {r.kind === "short_rest" ? "Short rest" : "Schedule change"} ({r.duration_minutes} min)
                          </span>
                        </p>
                      </div>
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase ${
                          status === "approved"
                            ? "bg-emerald-100 text-emerald-800"
                            : status === "declined"
                            ? "bg-rose-100 text-rose-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {status}
                      </span>
                    </div>

                    <p className="mt-2 text-xs text-slate-600">{r.reason}</p>

                    {r.status === "pending" && decidedReqs[r.id] === undefined && (
                      <div className="mt-3 flex gap-2">
                        <button
                          type="button"
                          onClick={() => handleDecision(r.id, "approved")}
                          className="rounded-full bg-[#0b2a6f] px-4 py-1.5 text-xs font-bold text-white hover:brightness-110"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDecision(r.id, "declined")}
                          className="rounded-full bg-slate-200 px-4 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-300"
                        >
                          Decline
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}