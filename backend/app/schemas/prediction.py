"""Kontrak JSON antara ML -> Backend -> Frontend.
Ubah file ini HANYA setelah disepakati dengan tim ML, lalu samakan
dengan frontend/src/types/astronaut.ts.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReadinessGate(str, Enum):
    GO = "GO"
    CAUTION = "CAUTION"
    HOLD = "HOLD"


class FeatureImpact(BaseModel):
    name: str
    impact: float = Field(description="Kontribusi ke risiko (SHAP-like). + menaikkan risiko")


class WearableFeatures(BaseModel):
    """Input untuk model. Nama field = kesepakatan dengan tim ML."""
    hrv_rmssd_ms: float = 55
    resting_hr_bpm: float = 62
    sleep_hours: float = 7.0
    sleep_debt_hours: float = 0.5
    schedule_shift_minutes: float = 0  # + = jadwal mundur (delay), - = maju (advance)
    workload_hours: float = 8


class CognitiveStress(BaseModel):
    risk_level: RiskLevel
    risk_score: float = Field(ge=0, le=1)
    readiness_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    top_features: List[FeatureImpact]


class Circadian(BaseModel):
    status: str  # contoh: "ALIGNED", "PHASE_DELAY_1.5H"
    phase_shift_hours: float
    predicted_sleep_hours: float


ModelStatus = Literal["ok", "insufficient_data", "unavailable"]
PredictionSource = Literal["ml_model", "demo_rule"]


class FatiguePrediction(BaseModel):
    """Output Model 1 (next-day fatigue). Samakan dengan FatiguePrediction di astronaut.ts."""
    status: ModelStatus
    source: Optional[PredictionSource] = None
    model_version: Optional[str] = None
    prediction_horizon: Optional[str] = None
    fatigue_risk_score: Optional[float] = None       # skor risiko [0,1], BUKAN probabilitas
    fatigue_risk_probability: Optional[float] = None  # hanya terisi jika kalibrasi terverifikasi
    predicted_elevated_fatigue: Optional[bool] = None
    decision_threshold: Optional[float] = None
    input_coverage: Optional[float] = None            # porsi fitur model yang terisi [0,1]
    explanation_available: bool = False


class SleepPrediction(BaseModel):
    """Output Model 2 (durasi tidur). Samakan dengan SleepPrediction di astronaut.ts."""
    status: ModelStatus
    source: Optional[PredictionSource] = None
    model_version: Optional[str] = None
    predicted_sleep_tst_minutes: Optional[float] = None
    predicted_sleep_midpoint_minutes: Optional[float] = None
    sleep_shortfall_minutes: Optional[float] = None
    sleep_target_minutes: Optional[float] = None
    input_coverage: Optional[float] = None


class PredictionResponse(BaseModel):
    astronaut_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scenario: str = "custom"
    is_simulated: bool = True
    cognitive_stress: CognitiveStress
    circadian: Circadian
    readiness_gate: ReadinessGate
    recommended_actions: List[str]
    fatigue: Optional[FatiguePrediction] = None
    sleep: Optional[SleepPrediction] = None
