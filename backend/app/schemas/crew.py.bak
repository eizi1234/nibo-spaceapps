"""Skema untuk login, check-in, tugas, crew, permintaan istirahat, dan sleep plan.
Samakan dengan frontend/src/types/crew.ts.
"""
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .prediction import PredictionResponse, ReadinessGate

Role = Literal["commander", "crew"]
Sharing = Literal["status", "full"]  # status = commander hanya lihat GO/CAUTION/HOLD
Drink = Literal["coffee", "tea", "water", "nothing"]


# ---------- auth ----------
class UserPublic(BaseModel):
    id: str
    username: str
    name: str
    title: str
    role: Role
    sharing: Sharing


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    pin: str = Field(pattern=r"^\d{6}$")


class LoginResponse(BaseModel):
    token: str
    user: UserPublic


class SharingUpdate(BaseModel):
    sharing: Sharing


# ---------- check-in & tugas ----------
class Baseline(BaseModel):
    sleep_hours: float
    hrv_rmssd_ms: float
    resting_hr_bpm: float
    reaction_ms: float


class CheckInCreate(BaseModel):
    reaction_ms: float = Field(gt=0, lt=5000)
    mood: int = Field(ge=1, le=5)
    drink: Drink
    took_sleep_medication: bool


class Adjustment(BaseModel):
    """Penyesuaian skor BERBASIS ATURAN (bukan dari model ML)."""
    source: str  # reaction_test | mood | caffeine | sleep_medication
    points: float
    note: str


class TaskStatus(BaseModel):
    id: str
    name: str
    needs_score: int
    when_label: str
    day_offset: int
    hour: int
    assigned_to: str
    status: ReadinessGate
    projected_score: Optional[float] = None


class CheckInResult(BaseModel):
    user_id: str
    day: int
    base_score: float
    readiness_score: float
    readiness_gate: ReadinessGate
    adjustments: List[Adjustment]
    unreliable_signals: List[str]
    sleep_hours: float
    reaction_ms: float
    reaction_baseline_ms: float
    what_helps: List[str]
    tasks: List[TaskStatus]
    is_simulated: bool = True


# ---------- overview & riwayat ----------
class SleepDay(BaseModel):
    day: int
    label: str
    planned_bed: str
    planned_wake: str
    actual_bed: str
    actual_wake: str
    hours: float


class BodyClockPoint(BaseModel):
    day: int
    shift_hours: float


class OverviewResponse(BaseModel):
    user: UserPublic
    day: int
    scenario: str
    checkin_done: bool
    readiness_score: float
    readiness_gate: ReadinessGate
    thresholds: Dict[str, int]
    prediction: PredictionResponse
    adjustments: List[Adjustment]
    tasks: List[TaskStatus]
    next_critical_task: Optional[TaskStatus] = None
    sleep_7d: List[SleepDay]
    baseline: Baseline
    recommended_actions: List[str]


# ---------- crew (commander) ----------
class ForecastBlock(BaseModel):
    index: int
    day_offset: int
    hour: int  # 0, 6, 12, 18
    score: Optional[float] = None  # None jika crew hanya membagikan status
    gate: ReadinessGate


class CrewMember(BaseModel):
    user: UserPublic
    gate: ReadinessGate
    checkin_done: bool
    score: Optional[float] = None
    sleep_hours: Optional[float] = None
    hrv_rmssd_ms: Optional[float] = None
    reaction_ms: Optional[float] = None
    mood: Optional[str] = None
    clock_shift_hours: Optional[float] = None
    forecast: List[ForecastBlock]


class CrewResponse(BaseModel):
    day: int
    scenario: str
    members: List[CrewMember]


class SwapSuggestion(BaseModel):
    task_id: str
    task_name: str
    when_label: str
    needs_score: int
    from_user_id: str
    from_user_name: str
    from_gate: ReadinessGate
    from_score: Optional[float] = None
    to_user_id: str
    to_user_name: str
    to_gate: ReadinessGate
    to_score: Optional[float] = None


# ---------- permintaan istirahat ----------
class RestRequestCreate(BaseModel):
    kind: Literal["short_rest", "change_schedule"]
    duration_minutes: int = Field(120, ge=30, le=240)
    reason: str = Field(max_length=500)
    task_id: Optional[str] = None


class Candidate(BaseModel):
    user_id: str
    name: str
    title: str
    gate: ReadinessGate
    score: Optional[float] = None
    eligible: bool
    ai_pick: bool = False
    reason: str


class RestSuggestion(BaseModel):
    minutes: int
    predicted_score: float
    predicted_gate: ReadinessGate
    confidence: float
    enough_for_task: bool
    note: str
    candidates: List[Candidate]


class RestRequest(BaseModel):
    id: str
    requester_id: str
    requester_name: str
    requester_gate: ReadinessGate
    kind: Literal["short_rest", "change_schedule"]
    duration_minutes: int
    reason: str
    task_id: Optional[str] = None
    task_name: Optional[str] = None
    task_when: Optional[str] = None
    status: Literal["pending", "approved", "declined"]
    routed_to: Literal["commander", "mission_control"]
    created_at: datetime
    decided_at: Optional[datetime] = None
    approved_minutes: Optional[int] = None
    replacement_user_id: Optional[str] = None
    suggestion: Optional[RestSuggestion] = None


class Decision(BaseModel):
    decision: Literal["approve", "decline"]
    approved_minutes: Optional[int] = Field(None, ge=30, le=240)
    replacement_user_id: Optional[str] = None


# ---------- sleep management (what-if) ----------
class SleepPlanInput(BaseModel):
    user_id: str
    bedtime_earlier_minutes: int = Field(0, ge=0, le=180)
    recovery_sleep_minutes: int = Field(0, ge=0, le=180)


class PlanOutcome(BaseModel):
    score: float
    gate: ReadinessGate
    body_clock_hours: float
    predicted_sleep_hours: float
    schedule_shift_minutes: float
    sleep_debt_hours: float


class TaskChange(BaseModel):
    task_id: str
    name: str
    needs_score: int
    before: ReadinessGate
    after: ReadinessGate


class ClockPoint(BaseModel):
    day: int
    current_plan: float
    with_change: float


class SleepPlanResult(BaseModel):
    user_id: str
    current: PlanOutcome
    with_change: PlanOutcome
    task_changes: List[TaskChange]
    clock_projection: List[ClockPoint]
    bedtime_before: str
    bedtime_after: str
    wake_before: str
    wake_after: str
    applied: bool = False


class MissionEvent(BaseModel):
    at: datetime
    kind: str
    message: str

# ---------- ready to sleep (cabin IoT & audio) ----------
LampMode = Literal["warm", "night", "off"]


class CabinEnvironment(BaseModel):
    temperature_c: float
    temperature_status: Literal["optimal", "warm", "cool"]
    ideal_temp_range_c: tuple[int, int] = (18, 22)
    temperature_history_60m: List[float]  # untuk bar chart 60 menit terakhir
    air_quality_aqi: int
    air_quality_status: Literal["good", "moderate", "poor"]
    humidity_pct: int
    pm25_ugm3: float
    noise_db: int
    noise_status: Literal["quiet", "moderate", "loud"]
    noise_target_max_db: int = 35


class LampState(BaseModel):
    mode: LampMode
    kelvin: int
    brightness_pct: int = Field(ge=0, le=100)
    auto_dim_time: str = "22:30"


class LampUpdate(BaseModel):
    mode: Optional[LampMode] = None
    brightness_pct: Optional[int] = Field(None, ge=0, le=100)


class LightScheduleItem(BaseModel):
    time: str
    title: str
    subtitle: str
    icon: Literal["bright", "normal", "dim", "off"]
    active: bool = False


class SleepPlaylist(BaseModel):
    id: str
    title: str
    subtitle: str
    genre: str
    tracks_count: int
    duration_label: str
    recommended: bool = False


class AudioPlayerState(BaseModel):
    active_playlist_id: str
    is_playing: bool
    sleep_timer_minutes: int = 30
    playlists: List[SleepPlaylist]


class AudioControlUpdate(BaseModel):
    active_playlist_id: Optional[str] = None
    is_playing: Optional[bool] = None
    sleep_timer_minutes: Optional[int] = Field(None, ge=5, le=120)


class ReadyToSleepResponse(BaseModel):
    user_id: str
    day: int
    scenario: str
    environment: CabinEnvironment
    lamp: LampState
    light_plan: List[LightScheduleItem]
    light_plan_applied: bool
    audio: AudioPlayerState