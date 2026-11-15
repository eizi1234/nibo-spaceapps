// Samakan dengan backend/app/schemas/crew.py
import type { ReadinessGate, PredictionResponse } from "./astronaut";

export type Role = "commander" | "crew";
export type Sharing = "status" | "full";
export type Drink = "coffee" | "tea" | "water" | "nothing";

export interface UserPublic { id: string; username: string; name: string; title: string; role: Role; sharing: Sharing }
export interface LoginResponse { token: string; user: UserPublic }

export interface CheckInCreate { reaction_ms: number; mood: 1 | 2 | 3 | 4 | 5; drink: Drink; took_sleep_medication: boolean }
export interface Adjustment { source: string; points: number; note: string }

export interface TaskStatus {
  id: string; name: string; needs_score: number; when_label: string; day_offset: number; hour: number;
  assigned_to: string; status: ReadinessGate; projected_score: number | null;
}

export interface CheckInResult {
  user_id: string; day: number; base_score: number; readiness_score: number; readiness_gate: ReadinessGate;
  adjustments: Adjustment[]; unreliable_signals: string[]; sleep_hours: number; reaction_ms: number;
  reaction_baseline_ms: number; what_helps: string[]; tasks: TaskStatus[]; is_simulated: boolean;
}

export interface SleepDay { day: number; label: string; planned_bed: string; planned_wake: string; actual_bed: string; actual_wake: string; hours: number; forecast?: boolean }
export interface BodyClockPoint { day: number; shift_hours: number; projected?: boolean }
export interface Baseline { sleep_hours: number; hrv_rmssd_ms: number; resting_hr_bpm: number; reaction_ms: number }

export interface OverviewResponse {
  user: UserPublic; day: number; scenario: string; checkin_done: boolean;
  readiness_score: number; readiness_gate: ReadinessGate; thresholds: { go: number; caution: number };
  prediction: PredictionResponse; adjustments: Adjustment[]; tasks: TaskStatus[];
  next_critical_task: TaskStatus | null; sleep_7d: SleepDay[]; baseline: Baseline; recommended_actions: string[];
}

export interface ForecastBlock { index: number; day_offset: number; hour: number; score: number | null; gate: ReadinessGate }
export interface CrewMember {
  user: UserPublic; gate: ReadinessGate; checkin_done: boolean; score: number | null; sleep_hours: number | null;
  hrv_rmssd_ms: number | null; reaction_ms: number | null; mood: string | null; clock_shift_hours: number | null;
  forecast: ForecastBlock[];
}
export interface CrewResponse { day: number; scenario: string; members: CrewMember[] }

export interface SwapSuggestion {
  task_id: string; task_name: string; when_label: string; needs_score: number;
  from_user_id: string; from_user_name: string; from_gate: ReadinessGate; from_score: number | null;
  to_user_id: string; to_user_name: string; to_gate: ReadinessGate; to_score: number | null;
}

export interface RestRequestCreate { kind: "short_rest" | "change_schedule"; duration_minutes: number; reason: string; task_id?: string }
export interface Candidate {
  user_id: string; name: string; title: string; gate: ReadinessGate; score: number | null;
  eligible: boolean; ai_pick: boolean; reason: string;
}
export interface RestSuggestion {
  minutes: number; predicted_score: number; predicted_gate: ReadinessGate; confidence: number;
  enough_for_task: boolean; note: string; candidates: Candidate[];
}
export interface RestRequest {
  id: string; requester_id: string; requester_name: string; requester_gate: ReadinessGate;
  kind: "short_rest" | "change_schedule"; duration_minutes: number; reason: string;
  task_id: string | null; task_name: string | null; task_when: string | null;
  status: "pending" | "approved" | "declined"; routed_to: "commander" | "mission_control";
  created_at: string; decided_at: string | null; approved_minutes: number | null;
  replacement_user_id: string | null; suggestion: RestSuggestion | null;
}
export type LocalRestRequest = RestRequest & { day?: number };
export interface Decision { decision: "approve" | "decline"; approved_minutes?: number; replacement_user_id?: string }

export interface SleepPlanInput { user_id: string; bedtime_earlier_minutes: number; recovery_sleep_minutes: number }
export interface PlanOutcome {
  score: number; gate: ReadinessGate; body_clock_hours: number; predicted_sleep_hours: number;
  schedule_shift_minutes: number; sleep_debt_hours: number;
}
export interface SleepPlanResult {
  user_id: string; current: PlanOutcome; with_change: PlanOutcome;
  task_changes: { task_id: string; name: string; needs_score: number; before: ReadinessGate; after: ReadinessGate }[];
  clock_projection: { day: number; current_plan: number; with_change: number }[];
  bedtime_before: string; bedtime_after: string; wake_before: string; wake_after: string; applied: boolean;
}

export type LampMode = "warm" | "night" | "off";

export interface CabinEnvironment {
  temperature_c: number;
  temperature_status: "optimal" | "warm" | "cool";
  ideal_temp_range_c: [number, number];
  temperature_history_60m: number[];
  air_quality_aqi: number;
  air_quality_status: "good" | "moderate" | "poor";
  humidity_pct: number;
  pm25_ugm3: number;
  noise_db: number;
  noise_status: "quiet" | "moderate" | "loud";
  noise_target_max_db: number;
}

export interface LampState {
  mode: LampMode;
  kelvin: number;
  brightness_pct: number;
  auto_dim_time: string;
}

export interface LightScheduleItem {
  time: string;
  title: string;
  subtitle: string;
  icon: "bright" | "normal" | "dim" | "off";
  active: boolean;
}

export interface SleepPlaylist {
  id: string;
  title: string;
  subtitle: string;
  genre: string;
  tracks_count: number;
  duration_label: string;
  recommended: boolean;
}

export interface AudioPlayerState {
  active_playlist_id: string;
  is_playing: boolean;
  sleep_timer_minutes: number;
  playlists: SleepPlaylist[];
}

export interface ReadyToSleepResponse {
  user_id: string;
  day: number;
  scenario: string;
  environment: CabinEnvironment;
  lamp: LampState;
  light_plan: LightScheduleItem[];
  light_plan_applied: boolean;
  audio: AudioPlayerState;
}