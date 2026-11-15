// Pembungkus pemanggil API backend + penyimpanan token login.
import type {
  CheckInCreate, CheckInResult, LoginResponse, OverviewResponse, RestRequest, RestRequestCreate, UserPublic,
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

export const api = {
  login: (username: string, pin: string) => request<LoginResponse>("/auth/login", post({ username, pin })),
  me: () => request<UserPublic>("/auth/me"),
  overview: (ctx: Ctx) => request<OverviewResponse>("/overview", {}, { ...ctx }),
  checkinToday: (ctx: Ctx) => request<CheckInResult | null>("/checkin/today", {}, { ...ctx }),
  submitCheckin: (body: CheckInCreate, ctx: Ctx) => request<CheckInResult>("/checkin", post(body), { ...ctx }),
  createRestRequest: (body: RestRequestCreate, ctx: Ctx) =>
    request<RestRequest>("/rest-requests", post(body), { ...ctx }),
};
