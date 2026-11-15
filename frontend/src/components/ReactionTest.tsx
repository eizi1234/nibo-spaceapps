"use client";

import { useEffect, useRef, useState } from "react";

export interface ReactionResult {
  meanMs: number;
  samples: number;
  falseStarts: number;
}

const MIN_SAMPLES = 3;

function fmt(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export default function ReactionTest({
  durationSeconds,
  onDone,
}: {
  durationSeconds: number;
  onDone: (r: ReactionResult) => void;
}) {
  const [running, setRunning] = useState(false);
  const [dotOn, setDotOn] = useState(false);
  const [remaining, setRemaining] = useState(durationSeconds);
  const [last, setLast] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const runningRef = useRef(false);
  const startedAt = useRef(0);
  const shownAt = useRef<number | null>(null);
  const reactions = useRef<number[]>([]);
  const falseStarts = useRef(0);
  const dotTimer = useRef<number | undefined>(undefined);
  const clock = useRef<number | undefined>(undefined);
  const onDoneRef = useRef(onDone);
  const respondRef = useRef<() => void>(() => {});

  function scheduleDot() {
    dotTimer.current = window.setTimeout(() => {
      shownAt.current = performance.now();
      setDotOn(true);
    }, 2000 + Math.random() * 6000);
  }

  function finish() {
    window.clearTimeout(dotTimer.current);
    window.clearInterval(clock.current);
    runningRef.current = false;
    shownAt.current = null;
    setRunning(false);
    setDotOn(false);
    const valid = reactions.current.filter((r) => r >= 100); // di bawah 100 ms = menebak
    if (valid.length < MIN_SAMPLES) {
      setNotice("Too few valid reactions to score. Run the full test.");
      setRemaining(durationSeconds);
      return;
    }
    const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    onDoneRef.current({ meanMs: Math.round(mean), samples: valid.length, falseStarts: falseStarts.current });
  }

  function start() {
    reactions.current = [];
    falseStarts.current = 0;
    shownAt.current = null;
    startedAt.current = performance.now();
    runningRef.current = true;
    setNotice(null);
    setLast(null);
    setDotOn(false);
    setRemaining(durationSeconds);
    setRunning(true);
    scheduleDot();
    clock.current = window.setInterval(() => {
      const left = durationSeconds - (performance.now() - startedAt.current) / 1000;
      if (left <= 0) finish();
      else setRemaining(left);
    }, 200);
  }

  function respond() {
    if (!runningRef.current) return;
    if (shownAt.current === null) {
      falseStarts.current += 1; // menekan sebelum titik muncul
      return;
    }
    const rt = Math.round(performance.now() - shownAt.current);
    shownAt.current = null;
    reactions.current.push(rt);
    setLast(rt);
    setDotOn(false);
    scheduleDot();
  }

  useEffect(() => {
    onDoneRef.current = onDone;
    respondRef.current = respond;
  });

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.code === "Space" && runningRef.current) {
        e.preventDefault();
        respondRef.current();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(dotTimer.current);
      window.clearInterval(clock.current);
    };
  }, []);

  const lengthLabel = durationSeconds % 60 === 0 ? `${durationSeconds / 60} minute` : `${durationSeconds} second`;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
      <div
        onPointerDown={respond}
        className="relative flex min-h-[420px] select-none flex-col items-center justify-center rounded-3xl bg-[#0b2a6f] p-6 text-center text-white"
      >
        {running ? (
          <>
            <div
              aria-hidden
              className={`size-24 rounded-full transition ${
                dotOn ? "bg-[#e6f23d] shadow-[0_0_0_18px_rgba(230,242,61,0.2)]" : "bg-white/10"
              }`}
            />
            <p className="mt-8 text-lg font-semibold">Tap or press space when the dot appears</p>
            <p className="mt-1 text-sm text-white/70">Keep your eyes on the center of the screen</p>
          </>
        ) : (
          <>
            <p className="text-lg font-semibold">{lengthLabel} vigilance test</p>
            <p className="mt-2 max-w-sm text-sm text-white/70">
              A dot lights up at random moments. Tap or press space as fast as you can each time, until the timer ends.
            </p>
            <button
              onClick={start}
              className="mt-6 rounded-full bg-[#e6f23d] px-6 py-3 text-sm font-semibold text-[#0a1b4d] hover:brightness-95"
            >
              Start test
            </button>
            {notice && (
              <p role="alert" className="mt-4 rounded-lg bg-white/10 px-3 py-2 text-sm">
                {notice}
              </p>
            )}
          </>
        )}
      </div>

      <aside className="flex flex-col gap-4 rounded-3xl bg-white/90 p-5 shadow-sm">
        <div>
          <p className="text-sm text-slate-500">Time left</p>
          <p className="text-4xl font-bold tabular-nums text-[#0a1b4d]">{fmt(remaining)}</p>
        </div>
        <div className="flex items-center justify-between rounded-xl bg-[#eaf1fd] px-3 py-2.5 text-sm">
          <span className="text-slate-600">Last reaction</span>
          <span className="font-semibold text-[#0a1b4d]">{last === null ? "-" : `${last} ms`}</span>
        </div>
        <p className="text-xs text-slate-500">
          This is a vigilance test of the kind used on the ISS. Your average is scored after the test ends.
        </p>
        {running && (
          <button
            onClick={finish}
            className="mt-auto rounded-full bg-slate-100 py-2.5 text-sm font-semibold text-[#0a1b4d] hover:bg-slate-200"
          >
            Stop test
          </button>
        )}
      </aside>
    </div>
  );
}
