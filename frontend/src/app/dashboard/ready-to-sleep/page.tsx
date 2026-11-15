"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import Icon from "@/components/Icon";
import type { IconName } from "@/components/Icon";
import { api } from "@/lib/api";
import { useDashboard } from "@/lib/dashboard-context";

const CARD = "glass-card rounded-[24px] p-6";

type LampMode = "warm_dim" | "night" | "off";

const LAMP_MODES: {
  id: LampMode;
  chipLabel: string;
  title: string;
  subtitle: string;
  icon: IconName;
  defaultBrightness: number;
  activeClass: string;
}[] = [
  {
    id: "warm_dim",
    chipLabel: "Warm",
    title: "Dim, warm light",
    subtitle: "2,700 K · Wind down for sleep",
    icon: "sun",
    defaultBrightness: 30,
    activeClass: "bg-[#f59e0b] text-white shadow-xs",
  },
  {
    id: "night",
    chipLabel: "Night",
    title: "Low amber night light",
    subtitle: "1,900 K · Zero blue spectrum",
    icon: "moon-sm",
    defaultBrightness: 10,
    activeClass: "bg-[#0a1b4d] text-[#e6f23d] shadow-xs",
  },
  {
    id: "off",
    chipLabel: "Off",
    title: "Lights off",
    subtitle: "0 K · Complete cabin darkness",
    icon: "moon-sm",
    defaultBrightness: 0,
    activeClass: "bg-slate-800 text-white shadow-xs",
  },
];

const PLAYLISTS: {
  id: string;
  title: string;
  meta: string;
  duration: string;
  notes: number[];
  icon: IconName;
}[] = [
  {
    id: "deep-space",
    title: "Deep Space Drift",
    meta: "Ambient · 12 tracks",
    duration: "1 hr 30 min",
    notes: [220, 277.18, 329.63],
    icon: "moon-sm",
  },
  {
    id: "rain-window",
    title: "Rain on the Window",
    meta: "Nature sounds · 8 tracks",
    duration: "45 min",
    notes: [261.63, 329.63, 392.0],
    icon: "sun",
  },
  {
    id: "soft-piano",
    title: "Soft Piano Nights",
    meta: "Instrumental · 15 tracks",
    duration: "1 hr",
    notes: [293.66, 349.23, 440.0],
    icon: "info-circle",
  },
];

const LIGHT_PLAN: {
  time: string;
  title: string;
  subtitle: string;
  icon: IconName;
  mode: LampMode;
}[] = [
  { time: "07:30", title: "Bright light", subtitle: "Helps you wake up", icon: "sun", mode: "warm_dim" },
  { time: "13:00", title: "Normal light", subtitle: "Daytime work", icon: "sun", mode: "warm_dim" },
  { time: "22:30", title: "Dim, warm light", subtitle: "Gets you ready for sleep", icon: "moon-sm", mode: "warm_dim" },
  { time: "01:00", title: "Lights off", subtitle: "Demo schedule", icon: "moon-sm", mode: "off" },
];

const TEMP_BARS = [42, 46, 44, 48, 50, 46, 44, 48, 52, 56, 62, 68, 72, 70];
const NOISE_WAVE = [32, 58, 44, 78, 52, 90, 64, 48, 82, 60, 42, 70, 50, 36, 48, 30];

export default function ReadyToSleepPage() {
  const { scenario, day } = useDashboard();

  const [lampMode, setLampMode] = useState<LampMode>("warm_dim");
  const [brightness, setBrightness] = useState<number>(30);
  const [selectedSlot, setSelectedSlot] = useState<string>("22:30");
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [sleepTimer, setSleepTimer] = useState<number>(30);

  const [refreshingAir, setRefreshingAir] = useState(false);
  const [airOffset, setAirOffset] = useState(0);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const activeNodesRef = useRef<{ oscs: OscillatorNode[]; noiseNode?: AudioBufferSourceNode; gain?: GainNode }>({
    oscs: [],
  });

  const ctxKey = `${scenario}:${day}`;
  const [seenKey, setSeenKey] = useState(ctxKey);
  if (seenKey !== ctxKey) {
    setSeenKey(ctxKey);
    setAirOffset(0);
  }

  useEffect(() => {
    return () => {
      stopAudio();
      if (audioCtxRef.current) {
        audioCtxRef.current.close().catch(() => {});
      }
    };
  }, []);

  function stopAudio() {
    const { oscs, noiseNode } = activeNodesRef.current;
    oscs.forEach((osc) => {
      try {
        osc.stop();
        osc.disconnect();
      } catch {
        // ignore
      }
    });
    if (noiseNode) {
      try {
        noiseNode.stop();
        noiseNode.disconnect();
      } catch {
        // ignore
      }
    }
    activeNodesRef.current = { oscs: [] };
    setPlayingId(null);
  }

  function toggleTrack(trackId: string, notes: number[]) {
    if (playingId === trackId) {
      stopAudio();
      return;
    }
    stopAudio();

    try {
      const AudioCtx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = audioCtxRef.current ?? new AudioCtx();
      audioCtxRef.current = ctx;
      if (ctx.state === "suspended") {
        ctx.resume();
      }

      const masterGain = ctx.createGain();
      masterGain.gain.setValueAtTime(0.001, ctx.currentTime);
      masterGain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + 0.6);

      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.setValueAtTime(680, ctx.currentTime);

      masterGain.connect(filter);
      filter.connect(ctx.destination);

      const oscs: OscillatorNode[] = notes.map((freq, idx) => {
        const osc = ctx.createOscillator();
        const noteGain = ctx.createGain();
        osc.type = idx === 0 ? "sine" : "triangle";
        osc.frequency.setValueAtTime(freq, ctx.currentTime);
        noteGain.gain.setValueAtTime(idx === 0 ? 0.5 : 0.25, ctx.currentTime);
        osc.connect(noteGain);
        noteGain.connect(masterGain);
        osc.start();
        return osc;
      });

      let noiseNode: AudioBufferSourceNode | undefined;
      if (trackId === "rain-window") {
        const bufferSize = ctx.sampleRate * 2;
        const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < bufferSize; i++) {
          data[i] = (Math.random() * 2 - 1) * 0.15;
        }
        noiseNode = ctx.createBufferSource();
        noiseNode.buffer = buffer;
        noiseNode.loop = true;
        noiseNode.connect(masterGain);
        noiseNode.start();
      }

      activeNodesRef.current = { oscs, noiseNode, gain: masterGain };
    } catch {
      // Fallback visual toggle
    }

    setPlayingId(trackId);
  }

  function handleRefreshAir() {
    setRefreshingAir(true);
    setTimeout(() => {
      setAirOffset((prev) => (prev === 0 ? -2 : prev === -2 ? 1 : 0));
      setRefreshingAir(false);
    }, 450);
  }

  async function selectLampMode(mode: LampMode) {
    const meta = LAMP_MODES.find((m) => m.id === mode)!;
    setLampMode(mode);
    setBrightness(meta.defaultBrightness);
    try {
      await api.updateLamp(
        { mode: mode === "warm_dim" ? "warm" : mode, brightness_pct: meta.defaultBrightness },
        day
      );
    } catch {
      // ignore
    }
  }

  async function handleBrightnessChange(val: number) {
    setBrightness(val);
    let nextMode: LampMode = "warm_dim";
    if (val === 0) nextMode = "off";
    else if (val <= 20) nextMode = "night";
    else nextMode = "warm_dim";

    setLampMode(nextMode);
    try {
      await api.updateLamp({ mode: nextMode === "warm_dim" ? "warm" : nextMode, brightness_pct: val }, day);
    } catch {
      // ignore
    }
  }

  const activeLamp = LAMP_MODES.find((m) => m.id === lampMode) ?? LAMP_MODES[0];
  const tempC = scenario === "chaotic_schedule" ? 20 : 19;
  const aqiVal = (scenario === "chaotic_schedule" ? 24 : 18) + airOffset;
  const humidityVal = 48 + airOffset;
  const pm25Val = Math.max(4, 6 + Math.sign(airOffset));
  const noiseDb = scenario === "chaotic_schedule" ? 28 : 24;
  const brightnessStyle = { "--fill": `${brightness}%` } as CSSProperties;

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-0.5">
        <h1 className="text-[28px] font-bold leading-[1.2] tracking-[-0.42px] text-ink">
          Ready to Sleep?
        </h1>
        <p className="text-[13px] font-medium text-ink-secondary">Simulated cabin environment and controls (demo data)</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* 1. Temperature Card */}
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Temperature">
          <div>
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-ink">Temperature</h2>
              <span className="text-xs font-medium text-ink-muted">Celsius</span>
            </div>

            <div className="mt-3 flex items-center justify-between">
              <span className="text-4xl font-extrabold tracking-tight text-ink">{tempC}°</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-go-bg px-3 py-1 text-xs font-bold text-go">
                <span className="size-1.5 rounded-full bg-go" />
                Optimal
              </span>
            </div>

            <p className="mt-2 text-xs text-ink-muted">Comfortable for a restful night</p>
          </div>

          <div className="mt-5">
            <div className="flex h-7 items-end gap-1.5">
              {TEMP_BARS.map((h, i) => (
                <div
                  key={i}
                  className={`flex-1 rounded-full ${
                    i >= TEMP_BARS.length - 4 ? "bg-[#0b3d91]" : "bg-slate-200/80"
                  }`}
                  style={{ height: `${h}%` }}
                />
              ))}
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px] font-medium text-ink-muted">
              <span>Last 60 min</span>
              <span className="font-semibold text-ink">Ideal 18–22°C</span>
            </div>
          </div>
        </section>

        {/* 2. Air Quality Card */}
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Air Quality">
          <div>
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-ink">Air Quality</h2>
              <button
                type="button"
                onClick={handleRefreshAir}
                title="Refresh cabin air quality sensors"
                aria-label="Refresh air quality"
                className="flex size-8 items-center justify-center rounded-full bg-soft text-brand transition hover:bg-[#dce7fc] active:scale-95"
              >
                <Icon name="refresh" className={refreshingAir ? "animate-spin" : ""} />
              </button>
            </div>

            <div className="mt-3 flex items-center justify-between">
              <div className="flex items-baseline gap-1.5">
                <span className="text-4xl font-extrabold tracking-tight text-ink">{aqiVal}</span>
                <span className="text-xs font-semibold text-ink-muted">AQI</span>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-go-bg px-3 py-1 text-xs font-bold text-go">
                <span className="size-1.5 rounded-full bg-go" />
                Good
              </span>
            </div>

            <p className="mt-2 text-xs text-ink-muted">Clean air. Breathe easy tonight.</p>
          </div>

          <div className="mt-4 space-y-3">
            <div>
              <div className="relative h-2 w-full rounded-full bg-slate-100">
                <div
                  className="h-2 rounded-full bg-[#12935f] transition-all"
                  style={{ width: `${Math.min(90, Math.max(15, aqiVal))}%` }}
                />
                <span
                  className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#12935f] bg-white shadow-xs transition-all"
                  style={{ left: `${Math.min(90, Math.max(15, aqiVal))}%` }}
                />
              </div>
              <div className="mt-1.5 flex justify-between text-[11px] font-medium text-ink-muted">
                <span>Good</span>
                <span>Unhealthy</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 border-t border-slate-100 pt-2.5 text-xs">
              <div>
                <p className="text-[11px] text-ink-muted">Humidity</p>
                <p className="font-bold text-ink">{humidityVal}%</p>
              </div>
              <div>
                <p className="text-[11px] text-ink-muted">PM2.5</p>
                <p className="font-bold text-ink">{pm25Val} µg/m³</p>
              </div>
            </div>
          </div>
        </section>

        {/* 3. Lamp Mode Card */}
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Lamp Mode">
          <div>
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-ink">Lamp Mode</h2>
              <span className="flex size-8 items-center justify-center rounded-full bg-soft text-brand">
                <Icon name="moon-sm" />
              </span>
            </div>

            <p className="mt-3 text-lg font-bold text-ink">{activeLamp.title}</p>
            <p className="text-xs text-ink-muted">{activeLamp.subtitle}</p>

            <div className="mt-3.5 grid grid-cols-3 gap-2">
              {LAMP_MODES.map((m) => {
                const active = lampMode === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => selectLampMode(m.id)}
                    className={`flex items-center justify-center gap-1.5 rounded-full py-2 text-xs font-bold transition ${
                      active
                        ? m.activeClass
                        : "bg-[#f4f7fe] text-ink-secondary hover:bg-slate-200/70"
                    }`}
                  >
                    <Icon name={m.icon} />
                    {m.chipLabel}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-4">
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="font-medium text-ink-muted">Brightness</span>
              <span className="font-bold text-ink">{brightness}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={brightness}
              onChange={(e) => handleBrightnessChange(Number(e.target.value))}
              className="nibo-range"
              style={brightnessStyle}
            />
            <p className="mt-1.5 text-[11px] font-medium text-ink-muted">Auto-dim at 22:30</p>
          </div>
        </section>
      </div>

      {/* Bottom Row: Music Playlist + Light Plan & Noise Quality */}
      <div className="grid items-stretch gap-5 lg:grid-cols-[1fr_360px]">
        <section className={`${CARD} flex flex-col justify-between`} aria-label="Music for Better Sleep">
          <div>
            <div className="flex items-baseline gap-2">
              <h2 className="text-base font-semibold text-ink">Music for Better Sleep</h2>
              <span className="text-xs font-medium text-ink-muted">Playlist</span>
            </div>
            <p className="text-xs text-ink-muted">A calmer soundtrack for your nightly wind-down.</p>

            <div className="brand-glow relative mt-4 overflow-hidden rounded-[20px] p-5 text-white">
              <div className="flex items-start justify-between gap-3">
                <span className="inline-block rounded-full bg-[#f9fcd1] px-3 py-1 text-[10px] font-extrabold tracking-wider text-on-accent">
                  RECOMMENDED TONIGHT
                </span>
                <span className="flex size-9 items-center justify-center rounded-full bg-[#e6f23d] text-[#0a1b4d]">
                  <Icon name="moon-sm" />
                </span>
              </div>

              <h3 className="mt-3 text-xl font-extrabold">Deep Space Drift</h3>
              <p className="mt-1 text-xs text-white/85">Slow ambient layers to help you unwind.</p>

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                <span className="text-[11px] font-medium text-white/75">
                  12 tracks · 1 hr 30 min · No vocals
                </span>
                <button
                  type="button"
                  onClick={() => toggleTrack("deep-space", PLAYLISTS[0].notes)}
                  className="inline-flex items-center gap-2 rounded-full bg-white px-4 py-2 text-xs font-bold text-ink shadow-xs transition hover:brightness-95"
                >
                  {playingId === "deep-space" ? "❚❚ Pause playlist" : "Play playlist ▶"}
                </button>
              </div>
            </div>

            <div className="mt-5">
              <div className="flex items-center justify-between text-xs">
                <h3 className="font-bold text-ink">Your sleep playlists</h3>
                <span className="text-ink-muted">{PLAYLISTS.length} playlists</span>
              </div>

              <div className="mt-3 space-y-2.5">
                {PLAYLISTS.map((pl) => {
                  const isPlaying = playingId === pl.id;
                  return (
                    <div
                      key={pl.id}
                      onClick={() => toggleTrack(pl.id, pl.notes)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") toggleTrack(pl.id, pl.notes);
                      }}
                      className={`flex cursor-pointer items-center justify-between gap-3 rounded-2xl px-4 py-3 transition ${
                        isPlaying
                          ? "border border-brand/30 bg-soft"
                          : "bg-[#f4f7fe] hover:bg-slate-200/60"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white text-brand shadow-2xs">
                          <Icon name={pl.icon} />
                        </span>
                        <div>
                          <p className="text-xs font-bold text-ink">{pl.title}</p>
                          <p className="text-[11px] text-ink-muted">{pl.meta}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        <span className="text-xs font-medium text-ink-muted">{pl.duration}</span>
                        <span className="flex size-7 items-center justify-center rounded-full bg-white text-[10px] font-bold text-brand shadow-2xs">
                          {isPlaying ? "❚❚" : "▶"}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-[11px] font-medium text-ink-muted">
            <button
              type="button"
              onClick={() => setSleepTimer((t) => (t === 30 ? 45 : t === 45 ? 60 : 30))}
              className="font-semibold text-brand hover:underline"
            >
              Sleep timer {sleepTimer} min
            </button>
            <span>Audio fades out gently before stopping</span>
          </div>
        </section>

        <div className="flex flex-col justify-between gap-5">
          {/* Top Right: Light Plan Today */}
          <section className={CARD} aria-label="Light plan today">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-ink">Light plan today</h2>
              <span className="rounded-full bg-soft px-3 py-1 text-[11px] font-semibold text-brand">
                Rule-based, simulated
              </span>
            </div>

            <div className="mt-4 space-y-2.5">
              {LIGHT_PLAN.map((item) => {
                const isSelected = selectedSlot === item.time;
                return (
                  <button
                    key={item.time}
                    type="button"
                    onClick={() => {
                      setSelectedSlot(item.time);
                      selectLampMode(item.mode);
                    }}
                    className={`flex w-full items-center gap-3 rounded-2xl px-3.5 py-2.5 text-left transition ${
                      isSelected
                        ? "accent-glow text-on-accent"
                        : "bg-[#f4f7fe] text-ink hover:bg-slate-200/60"
                    }`}
                  >
                    <span
                      className={`w-11 shrink-0 text-xs font-bold ${
                        isSelected ? "text-on-accent" : "text-ink"
                      }`}
                    >
                      {item.time}
                    </span>

                    <span
                      className={`flex size-8 shrink-0 items-center justify-center rounded-full ${
                        isSelected
                          ? "bg-[#0a1b4d] text-[#e6f23d]"
                          : "bg-white text-brand shadow-2xs"
                      }`}
                    >
                      <Icon name={item.icon} />
                    </span>

                    <div className="min-w-0">
                      <p
                        className={`text-xs font-bold leading-tight ${
                          isSelected ? "text-on-accent" : "text-ink"
                        }`}
                      >
                        {item.title}
                      </p>
                      <p
                        className={`truncate text-[11px] ${
                          isSelected ? "text-on-accent/80" : "text-ink-muted"
                        }`}
                      >
                        {item.subtitle}
                      </p>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Bottom Right: Noise Quality Card */}
          <section className={CARD} aria-label="Noise Quality">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-ink">Noise Quality</h2>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-go-bg px-3 py-1 text-xs font-bold text-go">
                <span className="size-1.5 rounded-full bg-go" />
                Quiet
              </span>
            </div>

            <div className="mt-4 flex items-end justify-between gap-4">
              <div>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-4xl font-extrabold tracking-tight text-ink">{noiseDb}</span>
                  <span className="text-xs font-semibold text-ink-muted">dB</span>
                </div>
                <p className="mt-1 text-xs text-ink-muted">Low noise · Ideal for sleep</p>
                <p className="mt-2 text-xs font-semibold text-brand">Target below 35 dB</p>
              </div>

              <div className="flex flex-col items-end">
                <div className="flex h-10 items-center gap-1">
                  {NOISE_WAVE.map((h, i) => (
                    <span
                      key={i}
                      className={`w-1 rounded-full ${
                        i < 11 ? "bg-[#0b3d91]" : "bg-slate-200"
                      }`}
                      style={{ height: `${h}%` }}
                    />
                  ))}
                </div>
                <span className="mt-1.5 text-[10px] font-medium text-ink-muted">Last 5 min</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}