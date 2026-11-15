"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import GateBadge from "@/components/GateBadge";
import Icon from "@/components/Icon";
import type { IconName } from "@/components/Icon";
import ReactionTest, { type ReactionResult } from "@/components/ReactionTest";
import { api, ApiError } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";
import type {
  CheckInResult,
  Drink,
  LocalRestRequest,
  OverviewResponse,
  RestRequestCreate,
} from "@/types/crew";

const CARD = "glass-card rounded-[24px] p-6";
const SHARED_REST_KEY = "nibo_shared_rest_requests";

const DRINKS: { value: Drink; label: string; icon: IconName }[] = [
  { value: "coffee", label: "Coffee", icon: "sun" },
  { value: "tea", label: "Tea", icon: "sun" },
  { value: "water", label: "Water only", icon: "moon-sm" },
  { value: "nothing", label: "Nothing yet", icon: "info-circle" },
];

const MOODS: { value: 1 | 2 | 3 | 4 | 5; label: string; emoji: string }[] = [
  { value: 1, label: "Very low", emoji: "😫" },
  { value: 2, label: "Low", emoji: "🙁" },
  { value: 3, label: "Okay", emoji: "😐" },
  { value: 4, label: "Good", emoji: "🙂" },
  { value: 5, label: "Very good", emoji: "😄" },
];

export default function DailyCheckInPage() {
  const router = useRouter();
  const { user, scenario, day } = useDashboard();

  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [demoDuration, setDemoDuration] = useState<number>(20);

  // Step 1 state
  const [reaction, setReaction] = useState<ReactionResult | null>(null);

  // Step 2 state
  const [drink, setDrink] = useState<Drink>("coffee");
  const [mood, setMood] = useState<1 | 2 | 3 | 4 | 5>(2);
  const [tookMed, setTookMed] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState(false);

  // Step 3 state
  const [result, setResult] = useState<CheckInResult | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Rest Request Modal state
  const [restOpen, setRestOpen] = useState(false);
  const [restKind, setRestKind] = useState<"short_rest" | "change_schedule">("short_rest");
  const [restMinutes, setRestMinutes] = useState<number>(120);
  const [restReason, setRestReason] = useState("");
  const [restSending, setRestSending] = useState(false);
  const [restSent, setRestSent] = useState(false);

  const isCommander = user.role === "commander" || user.id === "astronaut_a";

  useEffect(() => {
    let cancelled = false;
    const ctx = { scenario, day };
    Promise.all([api.overview(ctx), api.checkinToday(ctx)])
      .then(([ov, existing]) => {
        if (cancelled) return;
        setOverview(ov);
        if (existing) {
          setResult(existing);
          setStep(3);
        } else {
          setResult(null);
          setStep(1);
        }
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) router.push("/login");
        else setError(err.message || "Failed to load check-in context");
      });
    return () => {
      cancelled = true;
    };
  }, [scenario, day, router]);

  function handleReactionDone(r: ReactionResult) {
    setReaction(r);
    setStep(2);
  }

  async function handleSubmitQuestions(e: React.FormEvent) {
    e.preventDefault();
    const meanMs = reaction?.meanMs ?? 285;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.submitCheckin(
        {
          reaction_ms: meanMs,
          mood,
          drink,
          took_sleep_medication: tookMed,
        },
        { scenario, day }
      );
      setResult(res);
      setStep(3);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit check-in");
    } finally {
      setSubmitting(false);
    }
  }

  function openRestModal() {
    const taskName = (result?.tasks.find((t) => t.status !== "GO") ?? result?.tasks[0])?.name ?? "Robotic arm operations";
    const sleepStr = result?.sleep_hours ? result.sleep_hours.toFixed(1) : "5.0";
    setRestKind("short_rest");
    setRestMinutes(120);
    setRestReason(
      `I slept ${sleepStr} hours and my reaction test was slow (${Math.round(
        result?.reaction_ms ?? reaction?.meanMs ?? 286
      )} ms). Can I rest before ${taskName.toLowerCase()}?`
    );
    setRestSent(false);
    setRestOpen(true);
  }

  async function handleSendRestRequest(e: React.FormEvent) {
    e.preventDefault();
    setRestSending(true);
    setError(null);
    try {
      const affected = result?.tasks.find((t) => t.status !== "GO") ?? result?.tasks[0];
      const finalReason =
        restReason.trim() ||
        `My reaction test averaged ${result?.reaction_ms ?? reaction?.meanMs ?? 285} ms and readiness is ${result?.readiness_gate}. Requesting recovery window.`;

      const payload: RestRequestCreate = {
        kind: restKind,
        duration_minutes: restMinutes,
        reason: finalReason,
        task_id: affected?.id,
      };

      const created = await api.createRestRequest(payload, { scenario, day }).catch(() => null);

      // Simpan juga ke shared browser storage agar langsung muncul di dashboard Commander (Crew Mission)
      try {
        const raw = window.localStorage.getItem(SHARED_REST_KEY);
        const existing: LocalRestRequest[] = raw ? JSON.parse(raw) : [];
        const newEntry: LocalRestRequest = {
          id: created?.id ?? `rest-${Date.now()}`,
          requester_id: user.id,
          requester_name: user.name,
          requester_gate: result?.readiness_gate ?? "CAUTION",
          kind: restKind,
          duration_minutes: restMinutes,
          reason: finalReason,
          task_id: affected?.id ?? null,
          task_name: affected?.name ?? null,
          task_when: affected?.when_label ?? null,
          status: "pending",
          day,
          routed_to: isCommander ? "mission_control" : "commander",
          created_at: new Date().toISOString(),
          decided_at: null,
          approved_minutes: null,
          replacement_user_id: null,
          suggestion: null,
        };
        window.localStorage.setItem(SHARED_REST_KEY, JSON.stringify([newEntry, ...existing]));
      } catch {
        // ignore storage errors
      }

      setRestSent(true);
      setTimeout(() => {
        setRestOpen(false);
        setRestSent(false);
      }, 1200);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to send rest request");
    } finally {
      setRestSending(false);
    }
  }

  const lastNightSleep =
    overview?.sleep_7d[overview.sleep_7d.length - 1]?.hours ?? overview?.baseline.sleep_hours ?? 5.0;
  const affectedTask = result?.tasks.find((t) => t.status !== "GO") ?? result?.tasks[0];

  const pageTitle =
    step === 1 ? "Reaction test" : step === 2 ? "Daily check-in" : "Your check-in result";

  const stepsMeta = [
    {
      n: 1 as const,
      title: "Reaction test",
      sub:
        step > 1 && reaction
          ? `Done, average ${Math.round(reaction.meanMs)} ms`
          : step > 1 && result
          ? `Done, average ${Math.round(result.reaction_ms)} ms`
          : "About 3 minutes",
    },
    {
      n: 2 as const,
      title: "Questions",
      sub: step > 2 ? "Done, 3 answers saved" : "Wearable data and 3 questions",
    },
    {
      n: 3 as const,
      title: "Result",
      sub: "Your readiness today",
    },
  ];

  const scorePct = Math.min(100, Math.max(0, Math.round(result?.readiness_score ?? 30)));
  const arcRadius = 56;
  const arcLength = Math.PI * arcRadius;
  const arcDashOffset = arcLength - (scorePct / 100) * arcLength;

  return (
    <div className="space-y-5">
      {/* Header */}
      <header className="flex flex-col gap-0.5">
        <p className="text-[13px] font-medium text-ink-secondary">Step {step} of 3</p>
        <h1 className="text-[28px] font-bold leading-[1.2] tracking-[-0.42px] text-ink">{pageTitle}</h1>
      </header>

      {/* 3 Large Pill Stepper Cards */}
      <div className="grid gap-3.5 md:grid-cols-3">
        {stepsMeta.map((s) => {
          const isActive = step === s.n;
          const isDone = step > s.n;
          return (
            <button
              key={s.n}
              type="button"
              onClick={() => {
                if (s.n === 1 || (s.n === 2 && (reaction || result)) || (s.n === 3 && result)) {
                  setStep(s.n);
                }
              }}
              className={`flex items-center gap-3.5 rounded-full px-5 py-3.5 text-left transition ${
                isActive ? "brand-glow text-white" : "glass-card text-ink hover:brightness-[0.99]"
              }`}
            >
              <span
                className={`flex size-9 shrink-0 items-center justify-center rounded-full text-xs font-extrabold ${
                  isActive || isDone ? "bg-[#e6f23d] text-[#0a1b4d]" : "bg-soft text-ink-muted"
                }`}
              >
                {isDone ? "✓" : s.n}
              </span>
              <div className="min-w-0">
                <p className={`text-[13px] font-bold leading-tight ${isActive ? "text-white" : "text-ink"}`}>
                  {s.title}
                </p>
                <p className={`truncate text-xs ${isActive ? "text-white/80" : "text-ink-muted"}`}>
                  {s.sub}
                </p>
              </div>
            </button>
          );
        })}
      </div>

      {error && (
        <div role="alert" className="rounded-2xl bg-hold-bg px-4 py-3 text-sm text-hold">
          {error}
        </div>
      )}

      {/* ================= STEP 1: REACTION TEST ================= */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="glass-card flex flex-wrap items-center justify-between gap-2 rounded-2xl px-4 py-2.5 text-xs text-ink-secondary">
            <span>Test mode duration:</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setDemoDuration(20)}
                className={`rounded-full px-3.5 py-1 font-semibold transition ${
                  demoDuration === 20 ? "bg-[#0b3d91] text-white" : "bg-soft text-ink-secondary"
                }`}
              >
                20 sec (Quick demo)
              </button>
              <button
                type="button"
                onClick={() => setDemoDuration(180)}
                className={`rounded-full px-3.5 py-1 font-semibold transition ${
                  demoDuration === 180 ? "bg-[#0b3d91] text-white" : "bg-soft text-ink-secondary"
                }`}
              >
                3 min (ISS standard)
              </button>
            </div>
          </div>

          <ReactionTest key={demoDuration} durationSeconds={demoDuration} onDone={handleReactionDone} />
        </div>
      )}

      {/* ================= STEP 2: QUESTIONS ================= */}
      {step === 2 && (
        <form onSubmit={handleSubmitQuestions} className="grid items-start gap-5 lg:grid-cols-[1fr_320px]">
          <div className={`${CARD} space-y-6`}>
            <div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="flex size-8 items-center justify-center rounded-full bg-soft text-brand">
                    <Icon name="info-circle" />
                  </span>
                  <div>
                    <h2 className="text-sm font-bold text-ink">From your wearable</h2>
                    <p className="text-xs text-ink-muted">
                      Synced at 07:05 · Reaction mean {reaction?.meanMs ?? 286} ms{" "}
                      <button
                        type="button"
                        onClick={() => setStep(1)}
                        className="ml-1 font-semibold text-brand underline"
                      >
                        (Retake test)
                      </button>
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-3.5 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl bg-[#f4f7fe] p-4">
                  <div className="flex items-center justify-between text-xs text-ink-muted">
                    <span className="flex items-center gap-1.5 font-medium">
                      <Icon name="moon-sm" className="text-brand" /> Sleep last night
                    </span>
                    <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-ink-muted">
                      Auto
                    </span>
                  </div>
                  <p className="mt-2 text-2xl font-extrabold text-ink">
                    {Math.floor(lastNightSleep)} h {Math.round((lastNightSleep % 1) * 60)} min
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink-muted">23:40 to 04:40, woke up 3 times</p>
                </div>

                <div className="rounded-2xl bg-[#f4f7fe] p-4">
                  <div className="flex items-center justify-between text-xs text-ink-muted">
                    <span className="flex items-center gap-1.5 font-medium">
                      <Icon name="sun" className="text-brand" /> Exercise yesterday
                    </span>
                    <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-ink-muted">
                      Auto
                    </span>
                  </div>
                  <p className="mt-2 text-2xl font-extrabold text-ink">75 min</p>
                  <p className="mt-0.5 text-[11px] text-ink-muted">Cycling 45 min, treadmill 30 min</p>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-100 pt-5">
              <div className="flex items-start gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-soft text-brand">
                  <Icon name="sun" />
                </span>
                <div className="flex-1">
                  <label className="block text-sm font-bold text-ink">
                    What have you had to drink since waking up?
                  </label>
                  <p className="text-xs text-ink-muted">
                    Caffeine raises heart rate for a while, so that reading is marked less reliable.
                  </p>

                  <div className="mt-3 flex flex-wrap gap-2.5">
                    {DRINKS.map((d) => {
                      const active = drink === d.value;
                      return (
                        <button
                          key={d.value}
                          type="button"
                          onClick={() => setDrink(d.value)}
                          className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-xs font-semibold transition ${
                            active
                              ? "border-[#0b3d91] bg-[#0b3d91] text-white shadow-xs"
                              : "border-slate-200 bg-white text-ink hover:bg-slate-50"
                          }`}
                        >
                          <Icon name={d.icon} />
                          {d.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-100 pt-5">
              <div className="flex items-start gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-soft text-brand">
                  <Icon name="info-circle" />
                </span>
                <div className="flex-1">
                  <label className="block text-sm font-bold text-ink">How do you feel right now?</label>
                  <div className="mt-3.5 flex items-center gap-4">
                    {MOODS.map((m) => {
                      const active = mood === m.value;
                      return (
                        <button
                          key={m.value}
                          type="button"
                          onClick={() => setMood(m.value)}
                          title={m.label}
                          className={`flex size-12 items-center justify-center rounded-full text-2xl transition ${
                            active
                              ? "bg-[#0b3d91] ring-4 ring-[#0b3d91]/20 scale-105"
                              : "bg-[#f4f7fe] hover:bg-slate-200/70"
                          }`}
                        >
                          {m.emoji}
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-2 flex w-[304px] justify-between text-[11px] font-medium text-ink-muted">
                    <span>Very low</span>
                    <span>Very good</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="border-t border-slate-100 pt-5">
              <div className="flex items-start gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-soft text-brand">
                  <Icon name="moon-sm" />
                </span>
                <div className="flex-1">
                  <label className="block text-sm font-bold text-ink">
                    Did you take sleep medication last night?
                  </label>
                  <div className="mt-3 flex gap-2.5">
                    {[
                      { val: true, label: "Yes" },
                      { val: false, label: "No" },
                    ].map((opt) => (
                      <button
                        key={String(opt.val)}
                        type="button"
                        onClick={() => setTookMed(opt.val)}
                        className={`rounded-full border px-6 py-2 text-xs font-bold transition ${
                          tookMed === opt.val
                            ? "border-[#0b3d91] bg-[#0b3d91] text-white"
                            : "border-slate-200 bg-white text-ink hover:bg-slate-50"
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="rounded-full border border-slate-200 bg-white px-5 py-2.5 text-xs font-bold text-ink hover:bg-slate-50"
              >
                Back
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="brand-glow rounded-full px-6 py-2.5 text-xs font-bold text-white transition hover:brightness-110 disabled:opacity-50"
              >
                {submitting ? "Calculating..." : "See my result >"}
              </button>
            </div>
          </div>

          <aside className="space-y-4">
            <div className="accent-glow rounded-[24px] p-5 text-on-accent">
              <div className="flex items-center gap-2.5">
                <span className="flex size-8 items-center justify-center rounded-full bg-[#0a1b4d] text-[#e6f23d]">
                  <Icon name="moon-sm" />
                </span>
                <h3 className="text-sm font-bold">Why we ask</h3>
              </div>
              <p className="mt-3 text-xs leading-relaxed">
                Sleep and sleep debt are the biggest drivers of your readiness score.
              </p>
              <p className="mt-2 text-xs leading-relaxed">
                Coffee and exercise raise heart rate for a while, so those readings will not raise an alarm.
              </p>
            </div>

            {overview && (
              <div className={CARD}>
                <h3 className="text-sm font-bold text-ink">Your normal profile</h3>
                <div className="mt-3.5 space-y-2.5 text-xs">
                  <div className="flex items-center justify-between rounded-xl bg-[#f4f7fe] px-3.5 py-2.5">
                    <span className="flex items-center gap-2 font-medium text-ink-secondary">
                      <Icon name="moon-sm" className="text-brand" /> Sleep
                    </span>
                    <strong className="text-ink">{overview.baseline.sleep_hours} h</strong>
                  </div>
                  <div className="flex items-center justify-between rounded-xl bg-[#f4f7fe] px-3.5 py-2.5">
                    <span className="flex items-center gap-2 font-medium text-ink-secondary">
                      <Icon name="sun" className="text-brand" /> HRV
                    </span>
                    <strong className="text-ink">55 ms</strong>
                  </div>
                  <div className="flex items-center justify-between rounded-xl bg-[#f4f7fe] px-3.5 py-2.5">
                    <span className="flex items-center gap-2 font-medium text-ink-secondary">
                      <Icon name="info-circle" className="text-brand" /> Resting heart rate
                    </span>
                    <strong className="text-ink">{overview.baseline.resting_hr_bpm} bpm</strong>
                  </div>
                </div>
                <p className="mt-3 text-[11px] text-ink-muted">Today you are below this on all three.</p>
              </div>
            )}
          </aside>
        </form>
      )}

      {/* ================= STEP 3: RESULT ================= */}
      {step === 3 && result && (
        <div className="grid items-start gap-5 lg:grid-cols-[1fr_320px]">
          <div className={`${CARD} space-y-5`}>
            <div className="brand-glow flex flex-col items-center gap-6 rounded-[20px] p-6 text-white sm:flex-row">
              <div className="relative flex h-[96px] w-[150px] shrink-0 flex-col items-center justify-end">
                <svg viewBox="0 0 140 80" className="w-full overflow-visible">
                  <path
                    d="M 14 70 A 56 56 0 0 1 126 70"
                    fill="none"
                    stroke="rgba(255,255,255,0.2)"
                    strokeWidth="11"
                    strokeLinecap="round"
                  />
                  <path
                    d="M 14 70 A 56 56 0 0 1 126 70"
                    fill="none"
                    stroke="#e6f23d"
                    strokeWidth="11"
                    strokeLinecap="round"
                    strokeDasharray={arcLength}
                    strokeDashoffset={arcDashOffset}
                  />
                </svg>
                <div className="absolute bottom-2 text-center">
                  <span className="text-3xl font-extrabold leading-none">{scorePct}%</span>
                  <p className="mt-0.5 text-[10px] text-white/75">readiness</p>
                </div>
                <div className="flex w-full justify-between px-2 text-[10px] text-white/60">
                  <span>0</span>
                  <span>100</span>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2.5">
                  <GateBadge gate={result.readiness_gate} tone="white" />
                  <h2 className="text-base font-bold">Readiness today</h2>
                </div>
                <p className="text-xs leading-relaxed text-white/85">
                  {result.readiness_gate === "GO"
                    ? "Biometrics and reaction speed look strong. Cleared for high-priority tasks."
                    : "Not ready for high-risk tasks yet, mostly because of sleep debt and circadian shift."}
                </p>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-bold text-ink">In short</h3>
              <div className="mt-3 grid gap-3.5 sm:grid-cols-2">
                <div className="flex items-center gap-3.5 rounded-2xl bg-[#f4f7fe] p-4">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-white text-brand shadow-2xs">
                    <Icon name="moon" />
                  </span>
                  <div>
                    <p className="text-xs font-medium text-ink-muted">Sleep</p>
                    <p className="text-xl font-extrabold text-hold">{result.sleep_hours.toFixed(1)} h</p>
                    <p className="text-[11px] text-ink-muted">Compared to your baseline</p>
                  </div>
                </div>

                <div className="flex items-center gap-3.5 rounded-2xl bg-[#f4f7fe] p-4">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-white text-caution shadow-2xs">
                    <Icon name="clock" />
                  </span>
                  <div>
                    <p className="text-xs font-medium text-ink-muted">Reaction test</p>
                    <p className="text-xl font-extrabold text-caution">{Math.round(result.reaction_ms)} ms</p>
                    <p className="text-[11px] text-ink-muted">
                      Your usual: {Math.round(result.reaction_baseline_ms)} ms
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {result.adjustments.length > 0 && (
              <div>
                <button
                  type="button"
                  onClick={() => setDetailsOpen(!detailsOpen)}
                  className="text-xs font-semibold text-brand hover:underline"
                >
                  {detailsOpen ? "Hide full details ▲" : "See full details ▼"}
                </button>
                {detailsOpen && (
                  <div className="mt-2.5 space-y-1.5 rounded-2xl bg-[#f4f7fe] p-3.5 text-xs">
                    {result.adjustments.map((a, i) => (
                      <div key={i} className="flex justify-between text-ink-secondary">
                        <span>{a.note}</span>
                        <span className="font-bold text-ink">
                          {a.points > 0 ? `+${a.points}` : a.points === 0 ? "flag" : a.points}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-4">
              <p className="text-xs text-ink-muted">
                {isCommander
                  ? "You are the commander, so a rest request goes to Mission Control."
                  : "Need recovery time? Send a rest request to your Commander."}
              </p>
              <div className="flex items-center gap-2.5">
                {result.readiness_gate !== "GO" && (
                  <button
                    type="button"
                    onClick={openRestModal}
                    className="rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-bold text-ink hover:bg-slate-50"
                  >
                    Request rest
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => router.push("/dashboard")}
                  className="brand-glow rounded-full px-5 py-2 text-xs font-bold text-white hover:brightness-110"
                >
                  Go to overview &gt;
                </button>
              </div>
            </div>
          </div>

          <aside className="space-y-4">
            <div className="accent-glow rounded-[24px] p-5 text-on-accent">
              <div className="flex items-center gap-2.5">
                <span className="flex size-8 items-center justify-center rounded-full bg-[#0a1b4d] text-[#e6f23d]">
                  <Icon name="moon-sm" />
                </span>
                <h3 className="text-sm font-bold">What helps today</h3>
              </div>
              <ul className="mt-3 space-y-2 text-xs leading-relaxed">
                {result.what_helps.map((tip, i) => (
                  <li key={i}>{tip}</li>
                ))}
              </ul>
            </div>

            <div className={CARD}>
              <h3 className="text-sm font-bold text-ink">Your tasks today</h3>
              <div className="mt-3 space-y-2.5">
                {result.tasks.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between gap-2 rounded-xl bg-[#f4f7fe] px-3.5 py-2.5 text-xs"
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <Icon name="sun" className="shrink-0 text-brand" />
                      <span className="truncate font-semibold text-ink">{t.name}</span>
                    </div>
                    <GateBadge gate={t.status} />
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-ink-muted">
                The crew and Mission Control see only these statuses.
              </p>
            </div>
          </aside>
        </div>
      )}

      {/* ================= MODAL: REQUEST REST (MATCHING FIGMA) ================= */}
      {restOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#0a1a3a]/45 p-4 backdrop-blur-[2px]"
          onClick={() => setRestOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-[480px] rounded-[28px] bg-white p-6 shadow-[0_24px_48px_-12px_rgba(10,43,115,0.35)]"
          >
            {/* Header with Lime Moon Icon */}
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#e6f23d] text-[#0a1b4d]">
                  <Icon name="moon-sm" />
                </span>
                <div>
                  <h3 className="text-lg font-extrabold text-ink">Request a rest</h3>
                  <p className="text-xs text-ink-muted">
                    {isCommander
                      ? "Goes to Mission Control, because you are the commander"
                      : "Goes to Commander (Astronaut A) for schedule approval"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setRestOpen(false)}
                className="flex size-8 items-center justify-center rounded-full text-ink-muted hover:bg-slate-100 hover:text-ink"
              >
                ✕
              </button>
            </div>

            {restSent ? (
              <div className="py-10 text-center">
                <p className="text-base font-extrabold text-go">
                  Sent to {isCommander ? "Mission Control" : "Commander"}!
                </p>
                <p className="mt-1 text-xs text-ink-muted">
                  Your request is now visible in Crew Mission → Crew rest requests.
                </p>
              </div>
            ) : (
              <form onSubmit={handleSendRestRequest} className="mt-5 space-y-5">
                {/* What do you need? */}
                <div>
                  <label className="mb-2 block text-xs font-bold text-ink">What do you need?</label>
                  <div className="flex flex-wrap gap-2.5">
                    {[
                      { id: "short_rest", label: "Short rest", icon: "moon-sm" as IconName },
                      { id: "change_schedule", label: "Change schedule", icon: "clock" as IconName },
                    ].map((k) => {
                      const active = restKind === k.id;
                      return (
                        <button
                          key={k.id}
                          type="button"
                          onClick={() => setRestKind(k.id as "short_rest" | "change_schedule")}
                          className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-bold transition ${
                            active
                              ? "bg-[#0b3d91] text-white shadow-xs"
                              : "border border-slate-200 bg-white text-ink hover:bg-slate-50"
                          }`}
                        >
                          <Icon name={k.icon} />
                          {k.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* How long? */}
                <div>
                  <label className="mb-2 block text-xs font-bold text-ink">How long?</label>
                  <div className="flex flex-wrap items-center gap-2">
                    {[60, 120, 180].map((m) => {
                      const active = restMinutes === m;
                      return (
                        <button
                          key={m}
                          type="button"
                          onClick={() => setRestMinutes(m)}
                          className={`inline-flex items-center gap-1.5 rounded-full px-4 py-2 text-xs font-bold transition ${
                            active
                              ? "bg-[#0b3d91] text-white shadow-xs"
                              : "border border-slate-200 bg-white text-ink hover:bg-slate-50"
                          }`}
                        >
                          <Icon name="clock" />
                          {m / 60} h
                        </button>
                      );
                    })}
                    <span className="rounded-full bg-[#e6f23d] px-3 py-1.5 text-[11px] font-extrabold text-[#0a1b4d]">
                      AI suggests 2 h
                    </span>
                  </div>
                </div>

                {/* Short reason */}
                <div>
                  <label className="mb-1.5 block text-xs font-bold text-ink">Short reason</label>
                  <textarea
                    rows={3}
                    value={restReason}
                    onChange={(e) => setRestReason(e.target.value)}
                    placeholder="e.g., Short sleep after late shift, slow reaction score..."
                    className="w-full rounded-2xl border-2 border-[#0b3d91]/70 bg-white px-4 py-3 text-xs leading-relaxed text-ink focus:border-[#0b3d91] focus:outline-none"
                  />
                </div>

                {/* Affects Banner */}
                {affectedTask && (
                  <div className="flex items-center gap-3 rounded-2xl bg-[#f4f7fe] p-3.5 text-xs">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-white text-brand shadow-2xs">
                      <Icon name="info-circle" />
                    </span>
                    <div>
                      <p className="font-bold text-ink">Affects: {affectedTask.name}</p>
                      <p className="text-[11px] text-ink-muted">
                        {affectedTask.when_label}. {isCommander ? "Mission Control" : "Commander"} may reassign
                        this task.
                      </p>
                    </div>
                  </div>
                )}

                {/* Footer Actions */}
                <div className="flex items-center justify-end gap-2.5 pt-1">
                  <button
                    type="button"
                    onClick={() => setRestOpen(false)}
                    className="rounded-full border border-slate-200 bg-white px-5 py-2.5 text-xs font-bold text-ink hover:bg-slate-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={restSending}
                    className="brand-glow rounded-full px-5 py-2.5 text-xs font-bold text-white hover:brightness-110 disabled:opacity-50"
                  >
                    {restSending
                      ? "Sending..."
                      : isCommander
                      ? "Send to Mission Control >"
                      : "Send to Commander >"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}