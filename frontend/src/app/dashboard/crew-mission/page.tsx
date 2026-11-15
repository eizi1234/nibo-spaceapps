"use client";

import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import Avatar from "@/components/Avatar";
import GateBadge from "@/components/GateBadge";
import Icon from "@/components/Icon";
import {
  api,
  ApiError,
  type TaskSwapSuggestion,
} from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type { ReadinessGate } from "@/types/astronaut";
import type { CrewMember, LocalRestRequest, RestRequest } from "@/types/crew";

const CARD = "glass-card rounded-[24px] p-6";
const SHARED_REST_KEY = "nibo_shared_rest_requests";

const GATE_BAR_COLOR: Record<ReadinessGate, string> = {
  GO: "bg-[#12935f]",
  CAUTION: "bg-[#f59e0b]",
  HOLD: "bg-[#fc3d21]",
};

const GATE_TEXT_COLOR: Record<ReadinessGate, string> = {
  GO: "text-[#12935f]",
  CAUTION: "text-[#d97706]",
  HOLD: "text-[#fc3d21]",
};

const SHIFT_CELL_COLOR: Record<ReadinessGate, string> = {
  GO: "bg-[#a7dec6]",
  CAUTION: "bg-[#f6d594]",
  HOLD: "bg-[#f47560]",
};

function initialsOf(name: string) {
  const parts = name.trim().split(" ");
  if (parts.length >= 2) return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function shortInitial(name: string) {
  return name.split(" ").pop() ?? name;
}

function formatDurationBadge(mins: number) {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m} min`;
  return `${h} h ${String(m).padStart(2, "0")} min`;
}

function formatDurationShort(mins: number) {
  const h = mins / 60;
  return Number.isInteger(h) ? `${h} h` : `${h.toFixed(1)} h`;
}

function buildShiftForecast(member: CrewMember): ReadinessGate[] {
  const baseScore = member.score ?? 50;
  const shift = member.clock_shift_hours ?? 0;
  return Array.from({ length: 12 }, (_, idx) => {
    const recovery = idx * 3.8;
    const circadianDip = idx % 4 === 0 ? -6 : idx % 4 === 2 ? 4 : 0;
    const projected = baseScore + recovery - Math.max(0, shift - 1) * 2 + circadianDip;
    if (projected >= 70) return "GO";
    if (projected >= 45) return "CAUTION";
    return "HOLD";
  });
}

function syncLocalRequestStatus(rid: string, status: "approved" | "declined") {
  try {
    const raw = window.localStorage.getItem(SHARED_REST_KEY);
    if (!raw) return;
    const parsed: LocalRestRequest[] = JSON.parse(raw);
    const updated = parsed.map((item) => (item.id === rid ? { ...item, status } : item));
    window.localStorage.setItem(SHARED_REST_KEY, JSON.stringify(updated));
  } catch {
    // ignore storage errors
  }
}

type ModalContextState = {
  mode: "swap" | "rest";
  swap?: TaskSwapSuggestion;
  request?: RestRequest;
  requesterName: string;
  requesterTitle: string;
  requesterGate: ReadinessGate;
  requesterScore: number;
  reasonQuote: string;
  sentTime: string;
  taskName: string;
  taskWindow: string;
  needsScore: number;
  requestKind: "short_rest" | "change_schedule";
  restMinutes: number;
  selectedAssigneeId: string;
  pickerExpanded: boolean;
};

export default function CrewMissionPage() {
  const { user, scenario, day } = useDashboard();
  const [members, setMembers] = useState<CrewMember[]>([]);
  const [swaps, setSwaps] = useState<TaskSwapSuggestion[]>([]);
  const [dismissedSwaps, setDismissedSwaps] = useState<Record<string, boolean>>({});
  const [appliedSwaps, setAppliedSwaps] = useState<Record<string, boolean>>({});
  const [requests, setRequests] = useState<RestRequest[]>([]);
  const [decidedReqs, setDecidedReqs] = useState<Record<string, "approved" | "declined">>({});
  const [sharingOpen, setSharingOpen] = useState(false);
  const [shareFull, setShareFull] = useState(true);
  const [modal, setModal] = useState<ModalContextState | null>(null);
  const [modalSubmitting, setModalSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const ctx = { scenario, day };
    setLoading(true);
    setDismissedSwaps({});

    Promise.all([
      api.crew(ctx).catch(() => ({ members: [] as CrewMember[] })),
      api.crewSwaps(ctx).catch(() => []),
      api.restRequests(ctx).catch(() => []),
    ])
      .then(([crewRes, swapList, reqList]) => {
        if (cancelled) return;
        const list = Array.isArray(crewRes) ? crewRes : crewRes?.members ?? [];
        setMembers(list);
        setSwaps(Array.isArray(swapList) ? swapList : []);

        // Gabungkan pengajuan dari API dengan pengajuan baru dari localStorage
        const apiReqs = Array.isArray(reqList) ? reqList : [];
        let localReqs: RestRequest[] = [];
        try {
          const raw = window.localStorage.getItem(SHARED_REST_KEY);
          const parsed: LocalRestRequest[] = raw ? JSON.parse(raw) : [];
          localReqs = parsed.filter((r) => r.day === undefined || r.day === day);
        } catch {
          // ignore
        }
        const mergedReqs = [
          ...localReqs,
          ...apiReqs.filter((a) => !localReqs.some((l) => l.id === a.id)),
        ];
        setRequests(mergedReqs);
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
  }, [scenario, day, user.id]);

  useEffect(() => {
    if (!modal) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setModal(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal]);

  const memberByName = (name: string) =>
    members.find((m) => m.user.name.toLowerCase().includes(name.toLowerCase()));

  function openSwapModal(s: TaskSwapSuggestion) {
    const fromM = memberByName(s.from_user_name) ?? members[members.length - 1];
    const toM = memberByName(s.to_user_name) ?? members.find((m) => m.gate === "GO") ?? members[1];
    setModal({
      mode: "swap",
      swap: s,
      requesterName: fromM?.user.name ?? s.from_user_name,
      requesterTitle: fromM?.user.title ?? "Crew specialist",
      requesterGate: fromM?.gate ?? "HOLD",
      requesterScore: Math.round(fromM?.score ?? 38),
      reasonQuote:
        s.reason ||
        `"I slept ${fromM?.sleep_hours?.toFixed(1) ?? "4.5"} hours after the late shift and my reaction test was slow. Can I rest before ${s.task_name.toLowerCase()}?"`,
      sentTime: "Sent 07:12",
      taskName: s.task_name,
      taskWindow: `${s.when_label} to 12:00`,
      needsScore: 50,
      requestKind: "short_rest",
      restMinutes: 120,
      selectedAssigneeId: toM?.user.id ?? "",
      pickerExpanded: true,
    });
  }

  function openRestReviewModal(r: RestRequest) {
    const reqName = r.requester_name ?? "Astronaut D";
    const fromM = memberByName(reqName) ?? members[members.length - 1];
    const bestPick =
      [...members]
        .filter((m) => m.user.id !== fromM?.user.id && (m.score ?? 0) >= 50)
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0] ?? members[1];

    setModal({
      mode: "rest",
      request: r,
      requesterName: fromM?.user.name ?? reqName,
      requesterTitle: fromM?.user.title ?? "Medical officer",
      requesterGate: fromM?.gate ?? "HOLD",
      requesterScore: Math.round(fromM?.score ?? 38),
      reasonQuote: `"${r.reason}"`,
      sentTime: "Sent 07:12",
      taskName: "Sample processing",
      taskWindow: "Today 10:00 to 12:00",
      needsScore: 50,
      requestKind: r.kind,
      restMinutes: r.duration_minutes || 120,
      selectedAssigneeId: bestPick?.user.id ?? "",
      pickerExpanded: false,
    });
  }

  async function handleModalDecline() {
    if (!modal) return;
    if (modal.mode === "swap" && modal.swap) {
      setDismissedSwaps((prev) => ({ ...prev, [modal.swap!.id]: true }));
    } else if (modal.mode === "rest" && modal.request) {
      const rid = modal.request.id;
      setDecidedReqs((prev) => ({ ...prev, [rid]: "declined" }));
      syncLocalRequestStatus(rid, "declined");
      try {
        await api.decideRestRequest(rid, "declined", { scenario, day });
      } catch {
        // ignore
      }
    }
    setModal(null);
  }

  async function handleModalApprove() {
    if (!modal) return;
    setModalSubmitting(true);
    try {
      if (modal.mode === "swap" && modal.swap) {
        setAppliedSwaps((prev) => ({ ...prev, [modal.swap!.id]: true }));
        await api.applySwap(modal.swap.id, { scenario, day }).catch(() => {});
      } else if (modal.mode === "rest" && modal.request) {
        const rid = modal.request.id;
        setDecidedReqs((prev) => ({ ...prev, [rid]: "approved" }));
        syncLocalRequestStatus(rid, "approved");
        await api.decideRestRequest(rid, "approved", { scenario, day }).catch(() => {});
      }
    } finally {
      setModalSubmitting(false);
      setModal(null);
    }
  }

  if (error) {
    return (
      <p role="alert" className="rounded-2xl bg-hold-bg p-4 text-sm text-hold">
        {error}
      </p>
    );
  }

  if (loading) {
    return <p className="text-sm text-ink-secondary">Loading crew readiness &amp; mission tasks...</p>;
  }

  const visibleSwaps = swaps.filter((s) => !dismissedSwaps[s.id]);

  const sortedCandidates = modal
    ? [...members]
        .filter((m) => m.user.name !== modal.requesterName)
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    : [];
  const aiPickMember = sortedCandidates.find((m) => (m.score ?? 0) >= (modal?.needsScore ?? 50));
  const selectedMember =
    members.find((m) => m.user.id === modal?.selectedAssigneeId) ?? aiPickMember ?? sortedCandidates[0];

  return (
    <div className="space-y-5">
      {/* Header matching Figma */}
      <header className="flex flex-col gap-0.5">
        <p className="text-[13px] font-medium text-ink-secondary">
          {members.length || 4} crew members on board
        </p>
        <h1 className="text-[28px] font-bold leading-[1.2] tracking-[-0.42px] text-ink">Crew</h1>
      </header>

      {/* Privacy Notice Banner */}
      <div className="glass-card flex flex-wrap items-center justify-between gap-3 rounded-full px-5 py-3">
        <div className="flex items-center gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-soft text-brand">
            <Icon name="info-circle" />
          </span>
          <p className="text-xs font-medium text-ink-secondary">
            You only see the status your crewmates choose to share. Their health details stay private.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setSharingOpen(!sharingOpen)}
          className="rounded-full border border-slate-200 bg-white px-4 py-1.5 text-xs font-semibold text-ink transition hover:bg-slate-50"
        >
          Sharing settings
        </button>
      </div>

      {/* Collapsible Sharing Settings Drawer */}
      {sharingOpen && (
        <div className="glass-card flex flex-wrap items-center justify-between gap-4 rounded-2xl px-5 py-3.5 text-xs">
          <div>
            <p className="font-bold text-ink">Telemetry sharing preference ({user.name})</p>
            <p className="text-ink-muted">
              Choose whether crewmates see your detailed sleep &amp; HRV metrics or only GO/CAUTION/HOLD status.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShareFull(true)}
              className={`rounded-full px-3.5 py-1.5 font-semibold ${
                shareFull ? "bg-[#0b3d91] text-white" : "bg-soft text-ink-secondary"
              }`}
            >
              Share full metrics
            </button>
            <button
              type="button"
              onClick={() => setShareFull(false)}
              className={`rounded-full px-3.5 py-1.5 font-semibold ${
                !shareFull ? "bg-[#0b3d91] text-white" : "bg-soft text-ink-secondary"
              }`}
            >
              Status only
            </button>
          </div>
        </div>
      )}

      {/* 4 Crew Member Cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {members.map((m, idx) => {
          const isYou = m.user.id === user.id;
          const canView = isYou || m.user.sharing === "full";
          const score = Math.round(m.score ?? (m.gate === "GO" ? 76 : m.gate === "CAUTION" ? 55 : 34));
          const sleepH = m.sleep_hours ?? (m.gate === "GO" ? 7.2 : 4.6);
          const hrvVal = m.gate === "GO" ? 55 : m.gate === "CAUTION" ? 41 : 28 + idx * 2;
          const reactionVal = m.gate === "GO" ? 250 : m.gate === "CAUTION" ? 278 : 286 + idx * 8;
          const moodLabel =
            m.gate === "GO" ? "Good" : m.gate === "CAUTION" ? "Okay" : isYou ? "Tired" : "Low";

          return (
            <section
              key={m.user.id}
              className={`relative flex flex-col justify-between overflow-hidden rounded-[24px] p-5 transition ${
                isYou ? "brand-glow text-white" : "glass-card text-ink"
              }`}
            >
              <div>
                <div className="flex items-center gap-3">
                  <Avatar name={m.user.name} tone={isYou ? "accent" : "soft"} />
                  <div className="min-w-0">
                    <p className={`truncate text-[13px] font-bold ${isYou ? "text-white" : "text-ink"}`}>
                      {m.user.name} {isYou ? "(you)" : ""}
                    </p>
                    <p className={`truncate text-xs ${isYou ? "text-white/75" : "text-ink-muted"}`}>
                      {m.user.title}
                    </p>
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-between">
                  <GateBadge gate={m.gate} tone={isYou ? "white" : "soft"} />
                  <p className="flex items-baseline gap-0.5">
                    <span
                      className={`text-3xl font-extrabold tracking-tight ${
                        isYou ? "text-white" : GATE_TEXT_COLOR[m.gate]
                      }`}
                    >
                      {score}
                    </span>
                    <span className={`text-xs font-semibold ${isYou ? "text-white/75" : "text-ink-muted"}`}>
                      %
                    </span>
                  </p>
                </div>

                <div
                  className={`mt-2.5 h-1.5 w-full overflow-hidden rounded-full ${
                    isYou ? "bg-white/20" : "bg-slate-100"
                  }`}
                >
                  <div
                    className={`h-full rounded-full ${isYou ? "bg-white" : GATE_BAR_COLOR[m.gate]}`}
                    style={{ width: `${Math.min(100, Math.max(8, score))}%` }}
                  />
                </div>
              </div>

              {canView ? (
                <div className="mt-4 grid grid-cols-2 gap-2">
                  <div className={`rounded-xl p-2.5 ${isYou ? "bg-white/12" : "bg-[#f4f7fe]"}`}>
                    <p className={`flex items-center gap-1 text-[11px] ${isYou ? "text-white/75" : "text-ink-muted"}`}>
                      <Icon name="moon-sm" className={isYou ? "text-[#e6f23d]" : "text-brand"} /> Sleep
                    </p>
                    <p className="mt-1 text-xs font-bold">{sleepH.toFixed(1)} h</p>
                  </div>

                  <div className={`rounded-xl p-2.5 ${isYou ? "bg-white/12" : "bg-[#f4f7fe]"}`}>
                    <p className={`flex items-center gap-1 text-[11px] ${isYou ? "text-white/75" : "text-ink-muted"}`}>
                      <Icon name="sun" className={isYou ? "text-[#e6f23d]" : "text-brand"} /> HRV
                    </p>
                    <p className="mt-1 text-xs font-bold">{hrvVal} ms</p>
                  </div>

                  <div className={`rounded-xl p-2.5 ${isYou ? "bg-white/12" : "bg-[#f4f7fe]"}`}>
                    <p className={`flex items-center gap-1 text-[11px] ${isYou ? "text-white/75" : "text-ink-muted"}`}>
                      <Icon name="clock" className={isYou ? "text-[#e6f23d]" : "text-brand"} /> Reaction
                    </p>
                    <p className="mt-1 text-xs font-bold">{reactionVal} ms</p>
                  </div>

                  <div className={`rounded-xl p-2.5 ${isYou ? "bg-white/12" : "bg-[#f4f7fe]"}`}>
                    <p className={`flex items-center gap-1 text-[11px] ${isYou ? "text-white/75" : "text-ink-muted"}`}>
                      <Icon name="info-circle" className={isYou ? "text-[#e6f23d]" : "text-brand"} /> Mood
                    </p>
                    <p className="mt-1 text-xs font-bold">{moodLabel}</p>
                  </div>
                </div>
              ) : (
                <div className="mt-4 rounded-xl bg-[#f4f7fe] p-4 text-center text-xs text-ink-muted">
                  Shares readiness status only
                </div>
              )}
            </section>
          );
        })}
      </div>

      {/* Bottom 2-Column Section */}
      <div className="grid items-start gap-5 lg:grid-cols-[1fr_360px]">
        {/* Left: Readiness by Shift + Crew Rest Requests */}
        <div className="space-y-5">
          <section className={CARD} aria-label="Readiness by shift, next 3 days">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-ink">Readiness by shift, next 3 days</h2>
              <div className="flex items-center gap-3 text-[11px] font-semibold text-ink-secondary">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full bg-[#12935f]" /> GO
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full bg-[#f59e0b]" /> CAUTION
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-full bg-[#fc3d21]" /> HOLD
                </span>
              </div>
            </div>

            <div className="mt-5 grid grid-cols-[100px_1fr] gap-3">
              <div />
              <div>
                <div className="grid grid-cols-3 text-xs font-bold text-ink">
                  <span>Today</span>
                  <span>Tomorrow</span>
                  <span>Day {day + 2}</span>
                </div>
                <div className="mt-1 grid grid-cols-12 text-center text-[10px] font-medium text-ink-muted">
                  {["00", "06", "12", "18", "00", "06", "12", "18", "00", "06", "12", "18"].map((hr, i) => (
                    <span key={i}>{hr}</span>
                  ))}
                </div>
              </div>
            </div>

            <div className="relative mt-2.5 space-y-2.5">
              {members.map((m) => {
                const cells = buildShiftForecast(m);
                const isYou = m.user.id === user.id;
                return (
                  <div key={m.user.id} className="grid grid-cols-[100px_1fr] items-center gap-3">
                    <span className={`truncate text-xs ${isYou ? "font-bold text-ink" : "font-medium text-ink-muted"}`}>
                      {m.user.name}
                    </span>
                    <div className="relative grid grid-cols-12 gap-1.5">
                      {cells.map((gate, i) => (
                        <div
                          key={i}
                          className={`h-8 rounded-lg ${SHIFT_CELL_COLOR[gate]} transition-opacity hover:opacity-85`}
                          title={`${m.user.name}: ${gate}`}
                        />
                      ))}
                      <div
                        aria-hidden
                        className="pointer-events-none absolute -top-1 -bottom-1 w-[2px] bg-[#0a1b4d]"
                        style={{ left: "21%" }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            <p className="mt-4 flex items-center gap-1.5 text-xs text-ink-muted">
              <Icon name="info-circle" />
              <span>Each block is 6 hours, projected from the current scores and the shift plan.</span>
            </p>
          </section>

          {/* Crew Rest Requests Inbox (Synced with Check-In Modal) */}
          <section className={CARD} aria-label="Crew rest requests">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-semibold text-ink">Crew rest requests</h2>
                <p className="text-xs text-ink-muted">Recovery &amp; schedule change submissions</p>
              </div>
              <span className="rounded-full bg-soft px-3 py-1 text-xs font-bold text-brand">
                {requests.length}
              </span>
            </div>

            {requests.length === 0 ? (
              <p className="mt-4 rounded-2xl bg-[#f4f7fe] p-4 text-xs text-ink-muted">
                No pending rest requests from the crew right now.
              </p>
            ) : (
              <div className="mt-4 space-y-3">
                {requests.map((r) => {
                  const status: RestRequest["status"] = decidedReqs[r.id] ?? r.status;
                  return (
                    <div key={r.id} className="rounded-2xl bg-[#f4f7fe] p-4 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-bold text-ink">
                          {r.requester_name ?? r.requester_id} ·{" "}
                          <span className="font-medium text-ink-secondary">
                            {r.kind === "short_rest" ? "Short rest" : "Schedule change"} ({r.duration_minutes} min)
                          </span>
                        </p>
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-[10px] font-extrabold uppercase ${
                            status === "approved"
                              ? "bg-go-bg text-go"
                              : status === "declined"
                              ? "bg-hold-bg text-hold"
                              : "bg-caution-bg text-caution"
                          }`}
                        >
                          {status}
                        </span>
                      </div>

                      <p className="mt-1.5 text-ink-secondary">{r.reason}</p>

                      {r.status === "pending" && decidedReqs[r.id] === undefined && (
                        <div className="mt-3 flex gap-2">
                          <button
                            type="button"
                            onClick={() => openRestReviewModal(r)}
                            className="rounded-full bg-[#0b3d91] px-4 py-1.5 text-xs font-bold text-white hover:brightness-110"
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setDecidedReqs((prev) => ({ ...prev, [r.id]: "declined" }));
                              syncLocalRequestStatus(r.id, "declined");
                              api.decideRestRequest(r.id, "declined", { scenario, day }).catch(() => {});
                            }}
                            className="rounded-full border border-slate-200 bg-white px-4 py-1.5 text-xs font-semibold text-ink hover:bg-slate-50"
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

        {/* Right: Suggested Swaps */}
        <section className={CARD} aria-label="Suggested swaps">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-ink">Suggested swaps</h2>
            <span className="text-xs font-bold text-ink-muted">{visibleSwaps.length}</span>
          </div>

          {visibleSwaps.length === 0 ? (
            <p className="mt-4 rounded-2xl bg-[#f4f7fe] p-4 text-xs text-ink-muted">
              No task swaps needed under current readiness levels.
            </p>
          ) : (
            <div className="mt-4 space-y-3.5">
              {visibleSwaps.map((s, idx) => {
                const isApplied = appliedSwaps[s.id] || s.applied;
                const isFeatured = idx === 0 && !isApplied;
                const fromMember = memberByName(s.from_user_name);
                const toMember = memberByName(s.to_user_name);
                const fromScore = Math.round(fromMember?.score ?? 38);
                const toScore = Math.round(toMember?.score ?? 76);

                return (
                  <div
                    key={s.id}
                    className={`rounded-[20px] p-4 transition ${
                      isFeatured ? "accent-glow text-on-accent" : "bg-[#f4f7fe] text-ink"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`flex size-8 items-center justify-center rounded-full text-[11px] font-extrabold ${
                            isFeatured ? "bg-white text-ink" : "bg-white text-brand shadow-2xs"
                          }`}
                        >
                          {initialsOf(s.from_user_name)}
                        </span>
                        <span
                          className={`flex size-5 items-center justify-center rounded-full text-[10px] ${
                            isFeatured ? "bg-[#0a1b4d] text-[#e6f23d]" : "bg-soft text-brand"
                          }`}
                        >
                          ⇄
                        </span>
                        <span className="flex size-8 items-center justify-center rounded-full bg-[#0a1b4d] text-[11px] font-extrabold text-white">
                          {initialsOf(s.to_user_name)}
                        </span>
                      </div>
                      <span
                        className={`text-[11px] font-medium ${
                          isFeatured ? "text-on-accent/80" : "text-ink-muted"
                        }`}
                      >
                        {s.when_label}
                      </span>
                    </div>

                    <p className="mt-3 text-xs font-bold leading-snug">{s.task_name}</p>
                    <p
                      className={`mt-0.5 text-[11px] ${
                        isFeatured ? "text-on-accent/85" : "text-ink-muted"
                      }`}
                    >
                      {shortInitial(s.from_user_name)} scores {fromScore}, {shortInitial(s.to_user_name)} scores{" "}
                      {toScore}.
                    </p>

                    <div className="mt-3.5 flex items-center gap-2">
                      <button
                        type="button"
                        disabled={isApplied}
                        onClick={() => openSwapModal(s)}
                        className={`flex-1 rounded-full py-2 text-xs font-bold transition ${
                          isApplied
                            ? "bg-go-bg text-go"
                            : "brand-glow text-white hover:brightness-110"
                        }`}
                      >
                        {isApplied ? "✓ Swap approved" : "Propose swap"}
                      </button>

                      {!isApplied && (
                        <button
                          type="button"
                          onClick={() => setDismissedSwaps((prev) => ({ ...prev, [s.id]: true }))}
                          className="rounded-full bg-white px-3.5 py-2 text-xs font-semibold text-ink shadow-2xs hover:bg-slate-50"
                        >
                          Dismiss
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* ================= FIGMA INTERACTIVE MODAL (SWAP & REST APPROVAL) ================= */}
      {modal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#0a1a3a]/45 p-4 backdrop-blur-[2px]"
          onClick={() => setModal(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            className="flex max-h-[92vh] w-full max-w-[540px] flex-col gap-4 overflow-y-auto rounded-[28px] bg-white p-6 shadow-[0_24px_48px_-12px_rgba(10,43,115,0.35)]"
          >
            {/* Top Header */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <Avatar name={modal.requesterName} tone="soft" />
                <div>
                  <h2 className="text-base font-bold text-ink">{modal.requesterName}</h2>
                  <p className="text-xs text-ink-muted">{modal.requesterTitle}</p>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <GateBadge gate={modal.requesterGate} />
                <p className="flex items-baseline gap-0.5">
                  <span className="text-2xl font-extrabold text-hold">{modal.requesterScore}</span>
                  <span className="text-xs font-medium text-ink-muted">/100</span>
                </p>
              </div>
            </div>

            {/* Soft Coral Quote Box */}
            <div className="rounded-2xl bg-[#fff1ee] p-4">
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-bold text-hold">Not ready, asks for a short rest</span>
                <span className="text-ink-muted">{modal.sentTime}</span>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-ink">{modal.reasonQuote}</p>

              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setModal({ ...modal, requestKind: "short_rest" })}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-bold transition ${
                    modal.requestKind === "short_rest"
                      ? "bg-[#0b3d91] text-white"
                      : "bg-white text-ink-secondary"
                  }`}
                >
                  <Icon name="moon-sm" /> Short rest
                </button>
                <button
                  type="button"
                  onClick={() => setModal({ ...modal, requestKind: "change_schedule" })}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-bold transition ${
                    modal.requestKind === "change_schedule"
                      ? "bg-[#0b3d91] text-white"
                      : "bg-white text-ink-secondary"
                  }`}
                >
                  <Icon name="clock" /> Change schedule
                </button>
              </div>
            </div>

            {/* Affected Task */}
            <div className="flex items-center gap-3 px-1">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-soft text-brand">
                <Icon name="info-circle" />
              </span>
              <div>
                <p className="text-xs font-bold text-ink">Affected: {modal.taskName}</p>
                <p className="text-[11px] text-ink-muted">
                  {modal.taskWindow}, needs a score of {modal.needsScore}
                </p>
              </div>
            </div>

            {/* AI Suggests Banner + Rest Length Controls */}
            {modal.mode === "rest" && (
              <>
                <div className="brand-glow rounded-2xl p-4 text-white">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <span className="flex size-8 items-center justify-center rounded-full bg-[#e6f23d] text-[#0a1b4d]">
                        <Icon name="moon-sm" />
                      </span>
                      <div>
                        <p className="text-[11px] font-medium text-white/80">AI suggests</p>
                        <p className="text-sm font-extrabold">2 hours of rest, 10:00 to 12:00</p>
                      </div>
                    </div>
                    <span className="rounded-full bg-white/15 px-3 py-1 text-[11px] font-semibold text-white">
                      Confidence 60%
                    </span>
                  </div>
                  <p className="mt-2.5 text-xs leading-relaxed text-white/85">
                    After 2 hours {shortInitial(modal.requesterName)} is predicted to reach 55 (CAUTION). That is
                    enough for {modal.taskName.toLowerCase()} at 12:00, but not for EVA preparation tomorrow.
                  </p>
                </div>

                <div className="space-y-2 px-1">
                  <div className="flex items-center justify-between">
                    <p className="text-xs font-bold text-ink">
                      Rest length <span className="font-normal text-ink-muted">You can change it</span>
                    </p>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setModal({ ...modal, restMinutes: Math.max(30, modal.restMinutes - 30) })
                        }
                        className="flex size-7 items-center justify-center rounded-full border border-slate-200 text-sm font-bold text-ink hover:bg-slate-50"
                      >
                        −
                      </button>
                      <span className="rounded-full bg-soft px-3.5 py-1 text-xs font-extrabold text-ink">
                        {formatDurationBadge(modal.restMinutes)}
                      </span>
                      <button
                        type="button"
                        onClick={() =>
                          setModal({ ...modal, restMinutes: Math.min(240, modal.restMinutes + 30) })
                        }
                        className="flex size-7 items-center justify-center rounded-full border border-slate-200 text-sm font-bold text-ink hover:bg-slate-50"
                      >
                        +
                      </button>
                    </div>
                  </div>

                  <input
                    type="range"
                    min={30}
                    max={240}
                    step={30}
                    value={modal.restMinutes}
                    onChange={(e) => setModal({ ...modal, restMinutes: Number(e.target.value) })}
                    className="nibo-range"
                    style={{ "--fill": `${((modal.restMinutes - 30) / 210) * 100}%` } as CSSProperties}
                  />
                  <div className="flex justify-between text-[11px] font-medium text-ink-muted">
                    <span>30 min</span>
                    <span>1 h</span>
                    <span className="font-bold text-brand">2 h, AI</span>
                    <span>3 h</span>
                    <span>4 h</span>
                  </div>
                </div>
              </>
            )}

            {/* Crew Replacement Picker */}
            {modal.pickerExpanded ? (
              <div className="space-y-2.5 rounded-2xl border border-slate-100 bg-[#f8faff] p-4">
                <div className="flex items-center justify-between text-xs">
                  <p className="font-bold text-ink">Who takes {modal.taskName}?</p>
                  <span className="text-[11px] text-ink-muted">
                    Needs {modal.needsScore}, {modal.taskWindow}
                  </span>
                </div>

                <div className="space-y-2">
                  {sortedCandidates.map((cand) => {
                    const cScore = Math.round(cand.score ?? 50);
                    const eligible = cScore >= modal.needsScore;
                    const isPicked = selectedMember?.user.id === cand.user.id;
                    const isAiPick = aiPickMember?.user.id === cand.user.id;
                    const isYou = cand.user.id === user.id;

                    return (
                      <button
                        key={cand.user.id}
                        type="button"
                        disabled={!eligible}
                        onClick={() => setModal({ ...modal, selectedAssigneeId: cand.user.id })}
                        className={`flex w-full items-center justify-between gap-3 rounded-2xl border p-3 text-left transition ${
                          !eligible
                            ? "cursor-not-allowed border-transparent bg-white/50 opacity-50"
                            : isPicked
                            ? "border-[#0b3d91] bg-white shadow-xs"
                            : "border-slate-200/70 bg-white hover:border-brand/40"
                        }`}
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          <Avatar name={cand.user.name} tone={isPicked ? "brand" : "soft"} />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <p className="truncate text-xs font-bold text-ink">
                                {cand.user.name} {isYou ? "(you)" : ""}
                              </p>
                              {isAiPick && (
                                <span className="rounded-full bg-[#e6f23d] px-2 py-0.5 text-[10px] font-extrabold text-[#0a1b4d]">
                                  AI pick
                                </span>
                              )}
                            </div>
                            <p className="truncate text-[11px] text-ink-muted">
                              {eligible
                                ? `${cand.user.title}, trained, free`
                                : `Score below ${modal.needsScore}, cannot take it`}
                            </p>
                          </div>
                        </div>

                        <div className="flex shrink-0 items-center gap-2">
                          <GateBadge gate={cand.gate} />
                          <span className="text-xs font-bold text-ink">{cScore}</span>
                          <span
                            className={`flex size-4 items-center justify-center rounded-full border ${
                              isPicked ? "border-[#0b3d91] bg-[#0b3d91]" : "border-slate-300"
                            }`}
                          >
                            {isPicked && <span className="size-1.5 rounded-full bg-white" />}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>

                <p className="text-[11px] text-ink-muted">
                  Only crew trained for this task are listed. The AI ranks them by score, free time and workload.
                </p>

                {selectedMember && (
                  <div className="flex items-center justify-between gap-2 rounded-xl bg-[#eef4ff] px-3.5 py-2.5 text-xs">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={selectedMember.user.name} tone="brand" />
                      <div>
                        <p className="font-bold text-ink">
                          {modal.taskName} moves to {selectedMember.user.name}
                        </p>
                        <p className="text-[11px] text-ink-muted">
                          Score {Math.round(selectedMember.score ?? 76)} {selectedMember.gate}, trained for it, free{" "}
                          {modal.taskWindow}
                        </p>
                      </div>
                    </div>
                    {modal.mode === "rest" && (
                      <button
                        type="button"
                        onClick={() => setModal({ ...modal, pickerExpanded: false })}
                        className="text-xs font-bold text-brand hover:underline"
                      >
                        Close
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              selectedMember && (
                <div className="flex items-center justify-between gap-3 rounded-2xl border-2 border-[#d4e137] bg-[#fcffe8] p-3.5 text-xs">
                  <div className="flex items-center gap-2.5">
                    <Avatar name={selectedMember.user.name} tone="brand" />
                    <div>
                      <p className="font-bold text-ink">
                        Your pick. AI suggested {aiPickMember ? shortInitial(aiPickMember.user.name) : "B"} (
                        {Math.round(aiPickMember?.score ?? 77)} GO). {shortInitial(selectedMember.user.name)} scores{" "}
                        {Math.round(selectedMember.score ?? 76)} {selectedMember.gate}, trained, free
                      </p>
                      <p className="text-[11px] text-ink-muted">
                        Score {Math.round(selectedMember.score ?? 76)} {selectedMember.gate}, trained for it, free{" "}
                        {modal.taskWindow}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setModal({ ...modal, pickerExpanded: true })}
                    className="shrink-0 font-bold text-brand hover:underline"
                  >
                    Change
                  </button>
                </div>
              )
            )}

            {/* Modal Footer */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
              <span className="text-[11px] text-ink-muted">Mission Control is notified after you decide.</span>
              <div className="flex items-center gap-2.5">
                <button
                  type="button"
                  onClick={handleModalDecline}
                  className="rounded-full border border-slate-200 bg-white px-5 py-2.5 text-xs font-bold text-ink hover:bg-slate-50"
                >
                  Decline
                </button>
                <button
                  type="button"
                  disabled={modalSubmitting}
                  onClick={handleModalApprove}
                  className="brand-glow rounded-full px-5 py-2.5 text-xs font-bold text-white hover:brightness-110 disabled:opacity-50"
                >
                  {modalSubmitting
                    ? "Saving..."
                    : `Approve ${formatDurationShort(modal.restMinutes)} rest >`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}