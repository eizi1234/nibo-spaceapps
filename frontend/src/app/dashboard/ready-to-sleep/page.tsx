"use client";

import { useEffect, useState } from "react";
import { api, ApiError, type ReadyToSleepState } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";

const CARD = "rounded-3xl bg-white/95 p-6 shadow-sm";

const LAMP_MODES = [
  { id: "warm_dim", label: "Warm dim (2700K)", desc: "Melatonin-friendly amber glow" },
  { id: "off", label: "Lights off", desc: "Total darkness for sleep" },
  { id: "bright", label: "Bright white (6500K)", desc: "Alertness & daytime work" },
];

const AUDIO_TRACKS = [
  { id: "brown_noise", label: "Cabin brown noise", desc: "Masks ventilation & fan hum" },
  { id: "deep_space", label: "Deep space ambient", desc: "Low-frequency binaural drift" },
  { id: "off", label: "Silence", desc: "No audio playback" },
];

export default function ReadyToSleepPage() {
  const { user, day } = useDashboard();
  const [state, setState] = useState<ReadyToSleepState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .readyToSleep(day)
      .then((res) => {
        if (!cancelled) {
          setState(res);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Failed to load cabin controls.");
      });
    return () => {
      cancelled = true;
    };
  }, [day]);

  async function handleLampChange(patchData: { lamp_mode?: string; lamp_brightness?: number }) {
    if (!state) return;
    setSaving(true);
    try {
      const updated = await api.updateLamp(patchData, day);
      setState(updated);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to update cabin lamp.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAudioChange(patchData: { audio_track?: string; audio_playing?: boolean }) {
    if (!state) return;
    setSaving(true);
    try {
      const updated = await api.updateAudio(patchData, day);
      setState(updated);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Failed to update sleep audio.");
    } finally {
      setSaving(false);
    }
  }

  if (error) {
    return (
      <p role="alert" className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">
        {error}
      </p>
    );
  }

  if (!state) {
    return <p className="text-sm text-slate-500">Connecting to crew quarters IoT...</p>;
  }

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm text-slate-500">Crew quarters environment · {user.name}</p>
          <h1 className="text-3xl font-bold text-[#0a1b4d]">Ready to Sleep</h1>
        </div>
        {saving && (
          <span className="rounded-full bg-[#eaf1fd] px-3 py-1 text-xs font-semibold text-[#1d4fc4]">
            Syncing cabin IoT...
          </span>
        )}
      </header>

      {/* Cabin Environment Telemetry */}
      <div className="grid gap-4 sm:grid-cols-3">
        <div className={CARD}>
          <p className="text-xs font-medium text-slate-500">Cabin temperature</p>
          <p className="mt-2 text-3xl font-bold text-[#0a1b4d]">{state.cabin_temp_c.toFixed(1)} °C</p>
          <p className="mt-1 text-xs text-emerald-700">Optimal range (18–21 °C)</p>
        </div>
        <div className={CARD}>
          <p className="text-xs font-medium text-slate-500">CO₂ level</p>
          <p className="mt-2 text-3xl font-bold text-[#0a1b4d]">{state.cabin_co2_ppm} ppm</p>
          <p className="mt-1 text-xs text-emerald-700">Air scrubber nominal</p>
        </div>
        <div className={CARD}>
          <p className="text-xs font-medium text-slate-500">Ambient noise</p>
          <p className="mt-2 text-3xl font-bold text-[#0a1b4d]">{state.cabin_noise_db} dBA</p>
          <p className="mt-1 text-xs text-slate-500">Quiet sleep threshold &lt; 45 dBA</p>
        </div>
      </div>

      {/* Controls Grid: Cabin Lamp & Sleep Audio */}
      <div className="grid gap-4 lg:grid-cols-2">
        {/* Cabin Lighting Control */}
        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Quarters lighting</h2>
              <p className="text-xs text-slate-500">Adjust spectrum & brightness before sleep</p>
            </div>
            <span className="rounded-full bg-[#0b2a6f] px-3 py-1 text-xs font-bold text-[#e6f23d]">
              {state.lamp_brightness}%
            </span>
          </div>

          <div className="mt-4 space-y-2.5">
            {LAMP_MODES.map((m) => {
              const active = state.lamp_mode === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() =>
                    handleLampChange({
                      lamp_mode: m.id,
                      lamp_brightness: m.id === "off" ? 0 : state.lamp_brightness || 30,
                    })
                  }
                  className={`flex w-full items-center justify-between rounded-2xl border p-3.5 text-left transition ${
                    active
                      ? "border-[#1d4fc4] bg-[#eaf1fd]"
                      : "border-slate-100 bg-slate-50/70 hover:bg-slate-100"
                  }`}
                >
                  <div>
                    <p className="text-sm font-semibold text-[#0a1b4d]">{m.label}</p>
                    <p className="text-xs text-slate-500">{m.desc}</p>
                  </div>
                  <span
                    className={`size-4 rounded-full border-2 ${
                      active ? "border-[#1d4fc4] bg-[#1d4fc4]" : "border-slate-300"
                    }`}
                  />
                </button>
              );
            })}
          </div>

          <div className="mt-5">
            <div className="flex justify-between text-xs font-medium text-slate-600">
              <span>Brightness</span>
              <span>{state.lamp_brightness}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={state.lamp_brightness}
              onChange={(e) => handleLampChange({ lamp_brightness: Number(e.target.value) })}
              className="mt-2 w-full accent-[#1d4fc4]"
            />
          </div>
        </section>

        {/* Sleep Audio Control */}
        <section className={CARD}>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-[#0a1b4d]">Sleep soundscape</h2>
              <p className="text-xs text-slate-500">Mask station equipment hum during rest</p>
            </div>
            <button
              type="button"
              onClick={() => handleAudioChange({ audio_playing: !state.audio_playing })}
              className={`rounded-full px-4 py-1.5 text-xs font-bold transition ${
                state.audio_playing
                  ? "bg-[#e6f23d] text-[#0a1b4d]"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              {state.audio_playing ? "❚❚ Playing" : "▶ Play"}
            </button>
          </div>

          <div className="mt-4 space-y-2.5">
            {AUDIO_TRACKS.map((t) => {
              const active = state.audio_track === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  onClick={() =>
                    handleAudioChange({
                      audio_track: t.id,
                      audio_playing: t.id !== "off",
                    })
                  }
                  className={`flex w-full items-center justify-between rounded-2xl border p-3.5 text-left transition ${
                    active
                      ? "border-[#1d4fc4] bg-[#eaf1fd]"
                      : "border-slate-100 bg-slate-50/70 hover:bg-slate-100"
                  }`}
                >
                  <div>
                    <p className="text-sm font-semibold text-[#0a1b4d]">{t.label}</p>
                    <p className="text-xs text-slate-500">{t.desc}</p>
                  </div>
                  <span
                    className={`size-4 rounded-full border-2 ${
                      active ? "border-[#1d4fc4] bg-[#1d4fc4]" : "border-slate-300"
                    }`}
                  />
                </button>
              );
            })}
          </div>
        </section>
      </div>
    </div>
  );
}