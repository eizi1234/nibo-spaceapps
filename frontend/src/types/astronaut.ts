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
  predicted_sleep_hours: number;
  circadian_misalignment_hours: number;
  optimal_sleep_window: string;
}

export interface PredictionResponse {
  astronaut_id: string;
  scenario: string;
  is_simulated: boolean;
  cognitive_stress: CognitiveRiskPrediction;
  circadian: CircadianPrediction;
  readiness_gate: ReadinessGate;
  recommended_actions: string[];
}
