"use client";

import { useEffect, useRef, useState } from "react";
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

  // Ref untuk Web Audio API synthesizer
  const audioCtxRef = useRef<AudioContext | null>(null);
  const activeNodesRef = useRef<AudioNode[]>([]);

  function stopWebAudio() {
    activeNodesRef.current.forEach((node) => {
      try {
        if ("stop" in node && typeof (node as AudioScheduledSourceNode).stop === "function") {
          (node as AudioScheduledSourceNode).stop();
        }
        node.disconnect();
      } catch {
        // Abaikan jika node sudah berhenti
      }
    });
    activeNodesRef.current = [];
  }

  function startWebAudio(track: ReadyToSleepState["audio_track"]) {
    stopWebAudio();
    if (track === "off" || typeof window === "undefined") return;

    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AudioCtx) return;

    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioCtx();
    }
    const ctx = audioCtxRef.current;
    if (ctx.state === "suspended") {
      ctx.resume();
    }

    const masterGain = ctx.createGain();
    masterGain.gain.setValueAtTime(0.12, ctx.currentTime);
    masterGain.connect(ctx.destination);

    if (track === "brown_noise") {
      // Generator Brown Noise lembut (meredam suara kipas kabin)
      const bufferSize = 2 * ctx.sampleRate;
      const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const output = noiseBuffer.getChannelData(0);
      let lastOut = 0.0;
      for (let i = 0; i < bufferSize; i++) {
        const white = Math.random() * 2 - 1;
        output[i] = (lastOut + 0.02 * white) / 1.02;
        lastOut = output[i];
        output[i] *= 3.5;
      }

      const whiteNoise = ctx.createBufferSource();
      whiteNoise.buffer = noiseBuffer;
      whiteNoise.loop = true;

      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.setValueAtTime(320, ctx.currentTime);

      whiteNoise.connect(filter);
      filter.connect(masterGain);
      whiteNoise.start(0);

      activeNodesRef.current = [whiteNoise, filter, masterGain];
    } else if (track === "deep_space") {
      // Pad frekuensi rendah harmonik (65.4 Hz C2 + 98 Hz G2)
      const osc1 = ctx.createOscillator();
      const osc2 = ctx.createOscillator();
      osc1.type = "sine";
      osc2.type = "triangle";
      osc1.frequency.setValueAtTime(65.41, ctx.currentTime);
      osc2.frequency.setValueAtTime(98.0, ctx.currentTime);

      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.setValueAtTime(180, ctx.currentTime);

      const osc2Gain = ctx.createGain();
      osc2Gain.gain.setValueAtTime(0.35, ctx.currentTime);

      osc1.connect(filter);
      osc2.connect(osc2Gain);
      osc2Gain.connect(filter);
      filter.connect(masterGain);

      osc1.start(0);
      osc2.start(0);

      activeNodesRef.current = [osc1, osc2, osc2Gain, filter, masterGain];
    }
  }

  // Hentikan audio otomatis saat keluar dari halaman
  useEffect(() => {
    return () => {
      stopWebAudio();
    };
  }, []);

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

    const nextMode = (patchData.lamp_mode as ReadyToSleepState["lamp_mode"]) ?? state.lamp_mode ?? "warm_dim";
    const nextBrightness =
      patchData.lamp_brightness !== undefined
        ? patchData.lamp_brightness
        : nextMode === "off"
        ? 0
        : state.lamp_brightness ?? 30;

    setState((prev) =>
      prev
        ? {
            ...prev,
            lamp_mode: nextMode,
            lamp_brightness: nextBrightness,
          }
        : prev
    );

    setSaving(true);
    try {
      await api.updateLamp({ lamp_mode: nextMode, lamp_brightness: nextBrightness }, day);
    } catch {
      // Pertahankan state UI lokal
    } finally {
      setSaving(false);
    }
  }

  async function handleAudioChange(patchData: { audio_track?: string; audio_playing?: boolean }) {
    if (!state) return;

    const nextTrack = (patchData.audio_track as ReadyToSleepState["audio_track"]) ?? state.audio_track ?? "brown_noise";
    const nextPlaying =
      patchData.audio_playing !== undefined ? patchData.audio_playing : nextTrack !== "off";

    if (nextPlaying && nextTrack !== "off") {
      startWebAudio(nextTrack);
    } else {
      stopWebAudio();
    }

    setState((prev) =>
      prev
        ? {
            ...prev,
            audio_track: nextTrack,
            audio_playing: nextPlaying && nextTrack !== "off",
          }
        : prev
    );

    setSaving(true);
    try {
      await api.updateAudio({ audio_track: nextTrack, audio_playing: nextPlaying }, day);
    } catch {
      // Pertahankan state UI lokal
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

  const cabinTemp = state.cabin_temp_c ?? 19.5;
  const cabinCo2 = state.cabin_co2_ppm ?? 620;
  const cabinNoise = state.cabin_noise_db ?? 38;
  const lampMode = state.lamp_mode ?? "warm_dim";
  const lampBrightness = state.lamp_brightness ?? 30;
  const audioTrack = state.audio_track ?? "brown_noise";
  const audioPlaying = state.audio_playing ?? false;

  const lampPreviewStyle =
    lampMode === "off" || lampBrightness === 0
      ? "bg-slate-900 text-white"
      : lampMode === "warm_dim"
      ? "bg-amber-100 text-amber-950"
      : "bg-sky-100 text-sky-950";

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
          <p className="mt-2 text-3xl font-bold text-[#0a1b4d]">{cabinTemp.toFixed(1)} °C</p>
          <p className="mt-1 text-xs text-emerald-700">Optimal range (18–21 °C)</p>
        </div>
        <div className={CARD}>
          <p className="text-xs font-medium text-slate-500">CO₂ level</p>
          <p className="mt-2 text-3xl font-bold text-[#0a1b4d]">{cabinCo2} ppm</p>
          <p className="mt-1 text-xs text-emerald-700">Air scrubber nominal</p>
        </div>
        <div className={CARD}>
          <p className="text-xs font-medium text-slate-500">Ambient noise</p>
          <p className="mt-2 text-3xl font-bold text-[#0a1b4d]">{cabinNoise} dBA</p>
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
              <p className="text-xs text-slate-500">Adjust spectrum &amp; brightness before sleep</p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-bold transition-colors ${lampPreviewStyle}`}>
              {lampMode === "off" ? "OFF" : `${lampBrightness}%`}
            </span>
          </div>

          <div className="mt-4 space-y-2.5">
            {LAMP_MODES.map((m) => {
              const active = lampMode === m.id;
              return (
                <button
                  key={m.id}
                  type="button"
                  onClick={() =>
                    handleLampChange({
                      lamp_mode: m.id,
                      lamp_brightness: m.id === "off" ? 0 : lampBrightness === 0 ? 35 : lampBrightness,
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
              <span>{lampBrightness}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={lampBrightness}
              onChange={(e) => {
                const val = Number(e.target.value);
                handleLampChange({
                  lamp_brightness: val,
                  lamp_mode: val === 0 ? "off" : lampMode === "off" ? "warm_dim" : lampMode,
                });
              }}
              className="mt-2 w-full cursor-pointer accent-[#1d4fc4]"
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
              onClick={() =>
                handleAudioChange({
                  audio_track: audioTrack === "off" ? "brown_noise" : audioTrack,
                  audio_playing: !audioPlaying,
                })
              }
              className={`rounded-full px-4 py-1.5 text-xs font-bold transition ${
                audioPlaying
                  ? "bg-[#e6f23d] text-[#0a1b4d]"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              {audioPlaying ? "❚❚ Playing" : "▶ Play"}
            </button>
          </div>

          <div className="mt-4 space-y-2.5">
            {AUDIO_TRACKS.map((t) => {
              const active = audioTrack === t.id;
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