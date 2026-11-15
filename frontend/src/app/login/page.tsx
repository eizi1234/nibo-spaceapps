"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import type { ChangeEvent, ClipboardEvent, FormEvent, KeyboardEvent } from "react";
import { api, ApiError, tokenStore } from "@/lib/api";

const PIN_LENGTH = 6;

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [digits, setDigits] = useState<string[]>(Array(PIN_LENGTH).fill(""));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  const pin = digits.join("");
  const canSubmit = username.trim().length > 0 && pin.length === PIN_LENGTH && !busy;

  function onDigitChange(i: number, e: ChangeEvent<HTMLInputElement>) {
    const d = e.target.value.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[i] = d;
    setDigits(next);
    if (d && i < PIN_LENGTH - 1) refs.current[i + 1]?.focus();
  }

  function onDigitKeyDown(i: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[i] && i > 0) refs.current[i - 1]?.focus();
  }

  function onPaste(e: ClipboardEvent<HTMLDivElement>) {
    const text = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, PIN_LENGTH);
    if (!text) return;
    e.preventDefault();
    const next: string[] = Array(PIN_LENGTH).fill("");
    text.split("").forEach((ch, k) => {
      next[k] = ch;
    });
    setDigits(next);
    refs.current[Math.min(text.length, PIN_LENGTH - 1)]?.focus();
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(username.trim(), pin);
      tokenStore.set(res.token);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
      setDigits(Array(PIN_LENGTH).fill(""));
      refs.current[0]?.focus();
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[linear-gradient(to_bottom,#cfdffb,#f4f8ff)] p-4">
      <div aria-hidden className="absolute -right-24 -top-24 size-80 rounded-full bg-[#d9e6b8]" />
      <div aria-hidden className="absolute -bottom-32 left-12 size-96 rounded-full bg-[#c9daf8]" />

      <form
        onSubmit={onSubmit}
        className="relative w-full max-w-sm rounded-3xl bg-white/90 p-8 shadow-xl shadow-blue-900/10"
      >
        <h1 className="text-center text-3xl font-bold text-[#0a1b4d]">Sign in</h1>
        <p className="mt-1 text-center text-sm text-slate-500">Use your crew username and PIN</p>

        <label htmlFor="username" className="mt-6 block text-xs font-semibold text-[#0a1b4d]">
          Username
        </label>
        <input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="e.g. astronaut.a"
          autoComplete="username"
          autoCapitalize="none"
          className="mt-1.5 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-[#1f56d6] focus:ring-2 focus:ring-[#1f56d6]/20"
        />

        <div className="mt-4 flex items-center justify-between">
          <span id="pin-label" className="text-xs font-semibold text-[#0a1b4d]">
            PIN
          </span>
          <span className="text-xs text-slate-400">{PIN_LENGTH} digits</span>
        </div>
        <div role="group" aria-labelledby="pin-label" onPaste={onPaste} className="mt-1.5 flex gap-2">
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => {
                refs.current[i] = el;
              }}
              value={d}
              onChange={(e) => onDigitChange(i, e)}
              onKeyDown={(e) => onDigitKeyDown(i, e)}
              type="password"
              inputMode="numeric"
              autoComplete="off"
              aria-label={`PIN digit ${i + 1}`}
              className="h-11 w-full min-w-0 rounded-xl border border-slate-200 bg-white text-center text-lg outline-none focus:border-[#1f56d6] focus:ring-2 focus:ring-[#1f56d6]/20"
            />
          ))}
        </div>

        {error && (
          <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={!canSubmit}
          className="mt-6 w-full rounded-full bg-[#1f56d6] py-3 text-sm font-semibold text-white shadow-lg shadow-blue-700/25 transition enabled:hover:bg-[#1a47b3] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "Signing in" : "Sign in"}
        </button>

        {process.env.NODE_ENV !== "production" && (
          <p className="mt-4 text-center text-xs text-slate-400">
            Demo accounts: astronaut.a to astronaut.d, PIN 123456
          </p>
        )}
      </form>
    </main>
  );
}
