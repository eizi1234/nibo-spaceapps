"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import ReactionTest, { type ReactionResult } from "@/components/ReactionTest";
import { api, ApiError } from "@/lib/api";
import type { Scenario } from "@/types/astronaut";
import type {
  CheckInResult,
  Drink,
  OverviewResponse,
  RestRequestCreate,
  UserPublic,
} from "@/types/crew";

const DRINKS: { value: Drink; label: string }[] = [
  { value: "coffee", label: "Coffee" },
  { value: "tea", label: "Tea" },
  { value: "water", label: "Water only" },
  { value: "nothing", label: "Nothing yet" },
];

const MOODS: { value: 1 | 2 | 3 | 4 | 5; label: string; emoji: string }[] = [
  { value: 1, label: "Very low", emoji: "😫" },
  { value: 2, label: "Low", emoji: "😕" },
  { value: 3, label: "Okay", emoji: "😐" },
  { value: 4, label: "Good", emoji: "🙂" },
  { value: 5, label: "Very good", emoji: "😄" },
];

function GateBadge({ gate }: { gate: "GO" | "CAUTION" | "HOLD" }) {
  const styles = {
    GO: "bg-emerald-100 text-emerald-800",
    CAUTION: "bg-amber-100 text-amber-800",
    HOLD: "bg-rose-100 text-rose-800",
  }[gate];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold ${styles}`}>
      <span className="size-1.5 rounded-full bg-current" />
      {gate}
    </span>
  );
}

export default function DailyCheckInPage() {
  const router = useRouter();
  const params = useSearchParams();
  const scenario = (params.get("scenario") as Scenario) || "normal";
  const day = Number(params.get("day") || 142);

  const [user, setUser] = useState<UserPublic | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [demoDuration, setDemoDuration] = useState<number>(20); // 20s untuk demo cepat, 180s standar ISS

  // Step 1 state
  const [reaction, setReaction] = useState<ReactionResult | null>(null);

  // Step 2 state
  const [drink, setDrink] = useState<Drink>("nothing");
  const [mood, setMood] = useState<1 | 2 | 3 | 4 | 5>(3);
  const [tookMed, setTookMed] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState(false);

  // Step 3 state
  const [result, setResult] = useState<CheckInResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Rest Request Modal state
  const [restOpen, setRestOpen] = useState(false);
  const [restKind, setRestKind] = useState<"short_rest" | "change_schedule">("short_rest");
  const [restMinutes, setRestMinutes] = useState<number>(120);
  const [restReason, setRestReason] = useState("");
  const [restSending, setRestSending] = useState(false);
  const [restSent, setRestSent] = useState(false);

  useEffect(() => {
    const ctx = { scenario, day };
    Promise.all([api.me(), api.overview(ctx), api.checkinToday(ctx)])
      .then(([u, ov, existing]) => {
        setUser(u);
        setOverview(ov);
        if (existing) {
          setResult(existing);
          setStep(3);
        }
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.push("/login");
        else setError(err.message || "Failed to load check-in context");
      });
  }, [scenario, day, router]);

  function handleReactionDone(r: ReactionResult) {
    setReaction(r);
    setStep(2);
  }

  async function handleSubmitQuestions(e: React.FormEvent) {
    e.preventDefault();
    if (!reaction) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.submitCheckin(
        {
          reaction_ms: reaction.meanMs,
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

  async function handleSendRestRequest(e: React.FormEvent) {
    e.preventDefault();
    setRestSending(true);
    setError(null);
    try {
      const affected = result?.tasks.find((t) => t.status !== "GO") ?? result?.tasks[0];
      const payload: RestRequestCreate = {
        kind: restKind,
        duration_minutes: restMinutes,
        reason:
          restReason.trim() ||
          `My reaction test averaged ${result?.reaction_ms ?? reaction?.meanMs} ms and readiness is ${result?.readiness_gate}. Requesting recovery window.`,
        task_id: affected?.id,
      };
      await api.createRestRequest(payload, { scenario, day });
      setRestSent(true);
      setTimeout(() => {
        setRestOpen(false);
        setRestSent(false);
        setRestReason("");
      }, 1200);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to send rest request");
    } finally {
      setRestSending(false);
    }
  }

  const lastNightSleep = overview?.sleep_7d[overview.sleep_7d.length - 1]?.hours ?? overview?.baseline.sleep_hours;
  const affectedTask = result?.tasks.find((t) => t.status !== "GO") ?? result?.tasks[0];

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      {/* Header & Stepper */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
            Mission Day {day} · {user?.name ?? "Crew"}
          </p>
          <h1 className="text-2xl font-bold text-[#0a1b4d]">Daily check-in</h1>
        </div>

        {/* 3-Step Indicator */}
        <div className="flex items-center gap-2 rounded-full bg-white/90 px-4 py-2 text-xs font-semibold shadow-sm">
          {[
            { n: 1, label: "1. Reaction test" },
            { n: 2, label: "2. Questions" },
            { n: 3, label: "3. Result" },
          ].map((s, idx) => (
            <div key={s.n} className="flex items-center gap-2">
              {idx > 0 && <span className="text-slate-300">→</span>}
              <span
                className={`rounded-full px-3 py-1 ${
                  step === s.n
                    ? "bg-[#0a1b4d] text-white"
                    : step > s.n
                    ? "bg-emerald-100 text-emerald-800"
                    : "text-slate-400"
                }`}
              >
                {s.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-2xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {/* ================= STEP 1: REACTION TEST ================= */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-2xl bg-white/80 px-4 py-2.5 text-xs text-slate-600">
            <span>Test mode duration:</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setDemoDuration(20)}
                className={`rounded-full px-3 py-1 font-semibold ${
                  demoDuration === 20 ? "bg-[#0a1b4d] text-white" : "bg-slate-100 text-slate-600"
                }`}
              >
                20 sec (Quick demo)
              </button>
              <button
                type="button"
                onClick={() => setDemoDuration(180)}
                className={`rounded-full px-3 py-1 font-semibold ${
                  demoDuration === 180 ? "bg-[#0a1b4d] text-white" : "bg-slate-100 text-slate-600"
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
        <form onSubmit={handleSubmitQuestions} className="grid gap-6 lg:grid-cols-[1fr_300px]">
          <div className="space-y-6 rounded-3xl bg-white/95 p-6 shadow-sm">
            {/* Wearable summary */}
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-[#eaf1fd] p-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-[#0a1b4d]/70">
                  From your wearable & test
                </p>
                <p className="mt-1 text-sm text-slate-700">
                  Sleep last night: <strong>{lastNightSleep?.toFixed(1) ?? "-"} h</strong> · Reaction mean:{" "}
                  <strong>{reaction?.meanMs} ms</strong> ({reaction?.samples} taps)
                </p>
              </div>
              <button
                type="button"
                onClick={() => setStep(1)}
                className="text-xs font-semibold text-[#0b2a6f] underline"
              >
                Retake test
              </button>
            </div>

            {/* Q1: Drink */}
            <div>
              <label className="block text-sm font-semibold text-[#0a1b4d]">
                What have you had to drink since waking up?
              </label>
              <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                {DRINKS.map((d) => (
                  <button
                    key={d.value}
                    type="button"
                    onClick={() => setDrink(d.value)}
                    className={`rounded-2xl border px-3 py-3 text-sm font-medium transition ${
                      drink === d.value
                        ? "border-[#0b2a6f] bg-[#0b2a6f] text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Q2: Mood */}
            <div>
              <label className="block text-sm font-semibold text-[#0a1b4d]">How do you feel right now?</label>
              <div className="mt-3 grid grid-cols-5 gap-2">
                {MOODS.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => setMood(m.value)}
                    className={`flex flex-col items-center rounded-2xl border p-3 transition ${
                      mood === m.value
                        ? "border-[#0b2a6f] bg-[#eaf1fd] text-[#0a1b4d]"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    <span className="text-2xl">{m.emoji}</span>
                    <span className="mt-1 text-xs font-medium">{m.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Q3: Sleep medication */}
            <div>
              <label className="block text-sm font-semibold text-[#0a1b4d]">
                Did you take sleep medication last night?
              </label>
              <div className="mt-3 flex gap-3">
                {[
                  { val: false, label: "No" },
                  { val: true, label: "Yes" },
                ].map((opt) => (
                  <button
                    key={String(opt.val)}
                    type="button"
                    onClick={() => setTookMed(opt.val)}
                    className={`rounded-2xl border px-6 py-2.5 text-sm font-semibold transition ${
                      tookMed === opt.val
                        ? "border-[#0b2a6f] bg-[#0b2a6f] text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                disabled={submitting}
                className="rounded-full bg-[#e6f23d] px-7 py-3 text-sm font-bold text-[#0a1b4d] shadow-sm hover:brightness-95 disabled:opacity-50"
              >
                {submitting ? "Calculating readiness..." : "See my readiness >"}
              </button>
            </div>
          </div>

          {/* Side info cards */}
          <aside className="space-y-4">
            <div className="rounded-3xl bg-[#fef9c3] p-5 text-[#422006]">
              <h3 className="text-sm font-bold">Why we ask</h3>
              <p className="mt-2 text-xs leading-relaxed">
                Caffeine temporarily raises resting heart rate, and sleep aids can make wearable sleep stages look
                deeper than they are. Telling us prevents false alarms.
              </p>
            </div>

            {overview && (
              <div className="rounded-3xl bg-white/95 p-5 shadow-sm">
                <h3 className="text-sm font-bold text-[#0a1b4d]">Your normal profile</h3>
                <dl className="mt-3 space-y-2 text-xs">
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Sleep baseline</dt>
                    <dd className="font-semibold text-slate-800">{overview.baseline.sleep_hours} h</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Reaction baseline</dt>
                    <dd className="font-semibold text-slate-800">{overview.baseline.reaction_ms} ms</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-slate-500">Resting HR</dt>
                    <dd className="font-semibold text-slate-800">{overview.baseline.resting_hr_bpm} bpm</dd>
                  </div>
                </dl>
              </div>
            )}
          </aside>
        </form>
      )}

      {/* ================= STEP 3: RESULT ================= */}
      {step === 3 && result && (
        <div className="space-y-6">
          <div className="grid gap-6 md:grid-cols-3">
            {/* Main Readiness Score Card */}
            <div className="rounded-3xl bg-[#0b2a6f] p-6 text-white md:col-span-2">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm text-white/75">Updated readiness score</p>
                  <div className="mt-2 flex items-baseline gap-3">
                    <span className="text-5xl font-bold">{Math.round(result.readiness_score)}</span>
                    <span className="text-sm text-white/70">of 100 (sensor base {Math.round(result.base_score)})</span>
                  </div>
                </div>
                <GateBadge gate={result.readiness_gate} />
              </div>

              {result.adjustments.length > 0 && (
                <div className="mt-5 space-y-1.5 rounded-2xl bg-white/10 p-3.5 text-xs">
                  <p className="font-semibold text-white/90">Check-in adjustments applied:</p>
                  {result.adjustments.map((a, i) => (
                    <div key={i} className="flex justify-between text-white/80">
                      <span>{a.note}</span>
                      <span className="font-bold">
                        {a.points > 0 ? `+${a.points}` : a.points === 0 ? "flag" : a.points}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-5 flex flex-wrap gap-3">
                {result.readiness_gate !== "GO" && (
                  <button
                    type="button"
                    onClick={() => setRestOpen(true)}
                    className="rounded-full bg-[#e6f23d] px-5 py-2.5 text-sm font-bold text-[#0a1b4d] hover:brightness-95"
                  >
                    Request rest
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => router.push("/dashboard")}
                  className="rounded-full bg-white/15 px-5 py-2.5 text-sm font-semibold text-white hover:bg-white/25"
                >
                  Go to overview &gt;
                </button>
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="ml-auto text-xs text-white/70 underline hover:text-white"
                >
                  Redo check-in
                </button>
              </div>
            </div>

            {/* Metrics Summary */}
            <div className="space-y-4 rounded-3xl bg-white/95 p-6 shadow-sm">
              <div>
                <p className="text-xs text-slate-500">Sleep last night</p>
                <p className="text-2xl font-bold text-[#0a1b4d]">{result.sleep_hours.toFixed(1)} h</p>
              </div>
              <div className="border-t border-slate-100 pt-3">
                <p className="text-xs text-slate-500">Reaction test</p>
                <p className="text-2xl font-bold text-[#0a1b4d]">{Math.round(result.reaction_ms)} ms</p>
                <p className="text-xs text-slate-500">Your usual: {Math.round(result.reaction_baseline_ms)} ms</p>
              </div>
            </div>
          </div>

          {/* What helps & Tasks */}
          <div className="grid gap-6 md:grid-cols-2">
            <div className="rounded-3xl bg-[#fef9c3] p-6 text-[#422006]">
              <h2 className="text-base font-bold">What helps today</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {result.what_helps.map((tip, i) => (
                  <li key={i} className="rounded-xl bg-white/70 px-3.5 py-2.5">
                    {tip}
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-3xl bg-white/95 p-6 shadow-sm">
              <h2 className="text-base font-bold text-[#0a1b4d]">Your tasks today</h2>
              <div className="mt-3 space-y-2.5">
                {result.tasks.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between rounded-2xl bg-slate-50 px-4 py-3 text-sm"
                  >
                    <div>
                      <p className="font-semibold text-[#0a1b4d]">{t.name}</p>
                      <p className="text-xs text-slate-500">
                        {t.when_label} · needs score {t.needs_score}
                      </p>
                    </div>
                    <GateBadge gate={t.status} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ================= MODAL: REQUEST REST ================= */}
      {restOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-3xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-bold text-[#0a1b4d]">Request a rest</h3>
              <button
                type="button"
                onClick={() => setRestOpen(false)}
                className="rounded-full p-1.5 text-slate-400 hover:bg-slate-100"
              >
                ✕
              </button>
            </div>

            {restSent ? (
              <div className="py-8 text-center">
                <p className="text-base font-bold text-emerald-700">
                  Sent to {user?.role === "commander" ? "Mission Control" : "Commander"}!
                </p>
                <p className="mt-1 text-xs text-slate-500">Your request is now pending review.</p>
              </div>
            ) : (
              <form onSubmit={handleSendRestRequest} className="mt-4 space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-600">Request type</label>
                  <div className="mt-1.5 grid grid-cols-2 gap-2">
                    {[
                      { id: "short_rest", label: "Short rest" },
                      { id: "change_schedule", label: "Change schedule" },
                    ].map((k) => (
                      <button
                        key={k.id}
                        type="button"
                        onClick={() => setRestKind(k.id as "short_rest" | "change_schedule")}
                        className={`rounded-xl border py-2 text-xs font-semibold ${
                          restKind === k.id
                            ? "border-[#0b2a6f] bg-[#0b2a6f] text-white"
                            : "border-slate-200 text-slate-700"
                        }`}
                      >
                        {k.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-600">Duration</label>
                  <div className="mt-1.5 grid grid-cols-3 gap-2">
                    {[60, 120, 180].map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setRestMinutes(m)}
                        className={`rounded-xl border py-2 text-xs font-semibold ${
                          restMinutes === m
                            ? "border-[#0b2a6f] bg-[#eaf1fd] text-[#0a1b4d]"
                            : "border-slate-200 text-slate-700"
                        }`}
                      >
                        {m / 60} hour{m > 60 ? "s" : ""}
                      </button>
                    ))}
                  </div>
                </div>

                {affectedTask && (
                  <div className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    Affected task: <strong>{affectedTask.name}</strong> ({affectedTask.when_label})
                  </div>
                )}

                <div>
                  <label className="block text-xs font-semibold text-slate-600">Reason (optional)</label>
                  <textarea
                    rows={3}
                    value={restReason}
                    onChange={(e) => setRestReason(e.target.value)}
                    placeholder="e.g., Short sleep after late shift, slow reaction score..."
                    className="mt-1.5 w-full rounded-xl border border-slate-200 p-3 text-xs focus:border-[#0b2a6f] focus:outline-none"
                  />
                </div>

                <button
                  type="submit"
                  disabled={restSending}
                  className="w-full rounded-full bg-[#e6f23d] py-3 text-sm font-bold text-[#0a1b4d] hover:brightness-95 disabled:opacity-50"
                >
                  {restSending
                    ? "Sending..."
                    : user?.role === "commander"
                    ? "Send to Mission Control >"
                    : "Send to commander >"}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}