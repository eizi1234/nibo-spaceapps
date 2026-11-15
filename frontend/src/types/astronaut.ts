export type Scenario = "normal" | "sleep_deprived" | "chaotic_schedule";

export type ReadinessGate = "GO" | "CAUTION" | "HOLD";

export interface WearableFeatures {
  hrv_rmssd_ms: number;
  resting_hr_bpm: number;
  sleep_hours: number;
  sleep_debt_hours: number;
  schedule_shift_minutes: number;
  workload_hours: number;
}

export interface FeatureImpact {
  name: string;
  value: number;
  impact: number;
  label: string;
}

export interface CognitiveRiskPrediction {
  readiness_score: number;
  stress_probability: number;
  fatigue_level: "low" | "moderate" | "high";
  confidence: number;
  top_features: FeatureImpact[];
}

export interface CircadianPrediction {
  phase_shift_hours: number;
  predicted_sleep_hours: number;
  circadian_misalignment_hours: number;
  optimal_sleep_window: string;
}

export type ModelStatus = "ok" | "insufficient_data" | "unavailable";
export type PredictionSource = "ml_model" | "demo_rule";

export interface FatiguePrediction {
  status: ModelStatus;
  source?: PredictionSource;
  model_version?: string | null;
  prediction_horizon?: string | null;
  fatigue_risk_score: number | null;
  fatigue_risk_probability?: number | null;
  predicted_elevated_fatigue?: boolean | null;
  decision_threshold?: number | null;
  input_coverage?: number | null;
  explanation_available?: boolean;
}

export interface SleepPrediction {
  status: ModelStatus;
  source?: PredictionSource;
  model_version?: string | null;
  predicted_sleep_tst_minutes: number | null;
  predicted_sleep_midpoint_minutes?: number | null;
  sleep_shortfall_minutes?: number | null;
  sleep_target_minutes?: number | null;
  input_coverage?: number | null;
}

export interface PredictionResponse {
  fatigue?: FatiguePrediction | null;
  sleep?: SleepPrediction | null;
  astronaut_id: string;
  scenario: string;
  is_simulated: boolean;
  cognitive_stress: CognitiveRiskPrediction;
  circadian: CircadianPrediction;
  readiness_gate: ReadinessGate;
  recommended_actions: string[];
}
