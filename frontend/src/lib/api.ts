// Pembungkus pemanggil API backend + penyimpanan token login.
import type {
<<<<<<< HEAD
  BodyClockPoint, CheckInCreate, CheckInResult, CrewResponse, LoginResponse, OverviewResponse,
  RestRequest, RestRequestCreate, SleepDay, SleepPlanInput, SleepPlanResult, UserPublic,
=======
  BodyClockPoint,
  CheckInCreate,
  CheckInResult,
  LoginResponse,
  OverviewResponse,
  RestRequest,
  RestRequestCreate,
  SleepDay,
  UserPublic,
>>>>>>> f155cda5894b54ca4ec5d1db6c53ffbf4ab44cd3
} from "@/types/crew";
import type { Scenario } from "@/types/astronaut";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "astro_token";

export const tokenStore = {
  get: (): string | null =>
    typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY),
  set: (token: string): void => window.localStorage.setItem(TOKEN_KEY, token),
  clear: (): void => window.localStorage.removeItem(TOKEN_KEY),
};

export interface ReadyToSleepState {
  lamp_mode: "warm_dim" | "off" | "bright";
  lamp_brightness: number;
  cabin_temp_c: number;
  cabin_co2_ppm: number;
  cabin_noise_db: number;
  audio_track: "brown_noise" | "deep_space" | "off";
  audio_playing: boolean;
  light_plan_applied: boolean;
}

export interface CrewMemberSummary {
  id: string;
  name: string;
  title: string;
  role: "crew" | "commander";
  readiness_score: number;
  readiness_gate: "GO" | "CAUTION" | "HOLD";
  sleep_debt_hours: number;
  phase_shift_hours: number;
  checkin_done: boolean;
  next_task?: string;
}

export interface TaskSwapSuggestion {
  id: string;
  task_name: string;
  when_label: string;
  from_user_id: string;
  from_user_name: string;
  to_user_id: string;
  to_user_name: string;
  reason: string;
  applied?: boolean;
}

export interface SleepPlanSimulation {
  shift_minutes: number;
  nap_minutes: number;
  crew: {
    id: string;
    name: string;
    current_score: number;
    projected_score: number;
    current_gate: "GO" | "CAUTION" | "HOLD";
    projected_gate: "GO" | "CAUTION" | "HOLD";
  }[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Query = Record<string, string | number | undefined>;

async function request<T>(path: string, init: RequestInit = {}, query?: Query): Promise<T> {
  const url = new URL(`/api/v1${path}`, BASE);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = tokenStore.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let res: Response;
  try {
    res = await fetch(url, { ...init, headers });
  } catch {
    throw new ApiError(0, `Cannot reach the server at ${BASE}. Is the backend running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // body bukan JSON, pakai statusText
    }
    if (res.status === 401) tokenStore.clear();
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export interface Ctx {
  scenario: Scenario;
  day: number;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const patch = (body: unknown): RequestInit => ({ method: "PATCH", body: JSON.stringify(body) });

export const api = {
  // Auth
  login: (username: string, pin: string) =>
    request<LoginResponse>("/auth/login", post({ username, pin })),
  me: () => request<UserPublic>("/auth/me"),

  // Overview & Daily Check-in
  overview: (ctx: Ctx) => request<OverviewResponse>("/overview", {}, { ...ctx }),
  checkinToday: (ctx: Ctx) => request<CheckInResult | null>("/checkin/today", {}, { ...ctx }),
  submitCheckin: (body: CheckInCreate, ctx: Ctx) =>
    request<CheckInResult>("/checkin", post(body), { ...ctx }),
  createRestRequest: (body: RestRequestCreate, ctx: Ctx) =>
    request<RestRequest>("/rest-requests", post(body), { ...ctx }),

  // Sleep & Circadian
  sleepHistory: (userId: string, ctx: Ctx, days = 7) =>
    request<SleepDay[]>(`/users/${userId}/sleep-history`, {}, { ...ctx, days }),
  bodyClock: (userId: string, ctx: Ctx, days = 14) =>
    request<BodyClockPoint[]>(`/users/${userId}/body-clock`, {}, { ...ctx, days }),

  // Ready to Sleep (Crew IoT)
  readyToSleep: (day: number) =>
    request<ReadyToSleepState>("/ready-to-sleep", {}, { day }),
  updateLamp: (body: { lamp_mode?: string; lamp_brightness?: number }, day: number) =>
    request<ReadyToSleepState>("/ready-to-sleep/lamp", patch(body), { day }),
  updateAudio: (body: { audio_track?: string; audio_playing?: boolean }, day: number) =>
    request<ReadyToSleepState>("/ready-to-sleep/audio", patch(body), { day }),
  applyLightPlan: (day: number) =>
<<<<<<< HEAD
    request<{ ok: boolean; applied: boolean; day: number }>("/ready-to-sleep/light-plan/apply", post({}), { day }),
  crew: (ctx: Ctx) => request<CrewResponse>("/crew", {}, { ...ctx }),
  simulateSleepPlan: (body: SleepPlanInput, ctx: Ctx) =>
    request<SleepPlanResult>("/sleep-plan/simulate", post(body), { ...ctx }),
  applySleepPlan: (body: SleepPlanInput, ctx: Ctx) =>
    request<SleepPlanResult>("/sleep-plan/apply", post(body), { ...ctx }),
};
=======
    request<{ ok: boolean; applied: boolean; day: number }>(
      "/ready-to-sleep/light-plan/apply",
      post({}),
      { day }
    ),

  // Crew Mission (Commander)
  crewRoster: (ctx: Ctx) =>
    request<CrewMemberSummary[]>("/crew", {}, { ...ctx }),
  crewSwaps: (ctx: Ctx) =>
    request<TaskSwapSuggestion[]>("/crew/swaps", {}, { ...ctx }),
  applySwap: (swapId: string, ctx: Ctx) =>
    request<{ ok: boolean }>(`/crew/swaps/${swapId}/apply`, post({}), { ...ctx }),
  restRequests: (ctx: Ctx) =>
    request<RestRequest[]>("/rest-requests", {}, { ...ctx }),
  decideRestRequest: (rid: string, decision: "approved" | "declined", ctx: Ctx) =>
    request<RestRequest>(
      `/rest-requests/${rid}/decision`,
      post({
        approved: decision === "approved",
        status: decision,
      }),
      { ...ctx }
    ),
>>>>>>> f155cda5894b54ca4ec5d1db6c53ffbf4ab44cd3

  // Sleep Management (Commander)
  simulateSleepPlan: (body: { shift_minutes: number; nap_minutes: number }, ctx: Ctx) =>
    request<SleepPlanSimulation>(
      "/sleep-plan/simulate",
      post({
        bedtime_shift_minutes: body.shift_minutes,
        shift_minutes: body.shift_minutes,
        nap_minutes: body.nap_minutes,
      }),
      { ...ctx }
    ),
  applySleepPlan: (body: { shift_minutes: number; nap_minutes: number }, ctx: Ctx) =>
    request<{ ok: boolean }>(
      "/sleep-plan/apply",
      post({
        bedtime_shift_minutes: body.shift_minutes,
        shift_minutes: body.shift_minutes,
        nap_minutes: body.nap_minutes,
      }),
      { ...ctx }
    ),
};